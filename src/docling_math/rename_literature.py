"""Safe, explicit renaming of an already-extracted literature corpus.

The public API accepts a mapping such as::

    rename_literature(
        {
            "123456.pdf": "CortesToto_Espino-2011-Estimacion_de_tendencia.pdf",
            "download.pdf": "Smith_Jones-2024-Another_paper.pdf",
        },
        repo=".",
    )

PDFs, extracted Markdown, split references, assets, and references inside every active
Markdown file under bib/ are updated together. Renames are validated first and filesystem
moves use a two-phase temporary staging scheme, so swaps such as A -> B and B -> A are safe.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


WINDOWS_INVALID_CHARS = set('<>:"/\\|?*')
WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


@dataclass(frozen=True)
class RenamePair:
    old_stem: str
    new_stem: str

    @property
    def old_pdf(self) -> str:
        return f"{self.old_stem}.pdf"

    @property
    def new_pdf(self) -> str:
        return f"{self.new_stem}.pdf"


@dataclass(frozen=True)
class Move:
    source: Path
    destination: Path
    kind: str


@dataclass(frozen=True)
class RenameReport:
    mapping: tuple[RenamePair, ...]
    moves: tuple[Move, ...]
    markdown_files_changed: tuple[Path, ...]
    dry_run: bool


def discover_repo_root(start: Path | None = None) -> Path:
    """Find the nearest parent containing bib/pdf or Bib/pdf."""
    cwd = (start or Path.cwd()).expanduser().resolve()
    for candidate in (cwd, *cwd.parents):
        for bib_name in ("bib", "Bib"):
            if (candidate / bib_name / "pdf").is_dir():
                return candidate
    raise FileNotFoundError(
        "No pude localizar bib/pdf. Ejecuta rename_literature dentro del proyecto "
        "o usa --repo /ruta/al/proyecto."
    )


def resolve_bib_dir(repo: Path) -> Path:
    for name in ("bib", "Bib"):
        candidate = repo / name
        if candidate.is_dir():
            return candidate
    return repo / "bib"


def _validate_basename(value: str, *, field: str) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError(f"{field}: el nombre no puede estar vacío.")
    if "/" in raw or "\\" in raw:
        raise ValueError(f"{field}: usa sólo el nombre del archivo, no una ruta: {raw!r}")

    if raw.casefold().endswith(".pdf"):
        raw = raw[:-4]

    raw = raw.strip()
    if not raw:
        raise ValueError(f"{field}: el stem quedó vacío.")
    if raw.endswith((" ", ".")):
        raise ValueError(f"{field}: Windows no permite nombres terminados en espacio o punto.")
    if any(ord(ch) < 32 or ch in WINDOWS_INVALID_CHARS for ch in raw):
        raise ValueError(f"{field}: contiene caracteres inválidos para Windows: {raw!r}")
    if raw.upper() in WINDOWS_RESERVED:
        raise ValueError(f"{field}: nombre reservado por Windows: {raw!r}")
    return raw


def normalize_mapping(mapping: Mapping[str, str]) -> tuple[RenamePair, ...]:
    """Normalize mapping keys/values to PDF stems and reject ambiguous mappings."""
    pairs: list[RenamePair] = []
    seen_sources: dict[str, str] = {}
    seen_targets: dict[str, str] = {}

    for old, new in mapping.items():
        old_stem = _validate_basename(old, field="input")
        new_stem = _validate_basename(new, field="output")
        old_key = old_stem.casefold()
        new_key = new_stem.casefold()

        if old_key in seen_sources:
            raise ValueError(
                f"El input {old_stem!r} aparece más de una vez "
                f"(también como {seen_sources[old_key]!r})."
            )
        if new_key in seen_targets and old_key != new_key:
            raise ValueError(
                f"Dos inputs quieren terminar en {new_stem!r}: "
                f"{seen_targets[new_key]!r} y {old_stem!r}."
            )

        seen_sources[old_key] = old_stem
        seen_targets[new_key] = old_stem
        pairs.append(RenamePair(old_stem=old_stem, new_stem=new_stem))

    if not pairs:
        raise ValueError("El mapping de renombrados está vacío.")

    return tuple(pairs)


def _path_key(path: Path) -> str:
    # casefold intentionally models Windows collision semantics even when tests run on Linux.
    return str(path.absolute()).casefold()


def _planned_moves(bib: Path, pairs: tuple[RenamePair, ...]) -> tuple[Move, ...]:
    pdf_dir = bib / "pdf"
    extracted_dir = bib / "extracted"
    references_dir = bib / "references"
    assets_dir = bib / "assets"

    moves: list[Move] = []
    for pair in pairs:
        if pair.old_stem.casefold() == pair.new_stem.casefold() and pair.old_stem == pair.new_stem:
            continue

        old_pdf = pdf_dir / pair.old_pdf
        new_pdf = pdf_dir / pair.new_pdf
        if not old_pdf.exists():
            # Support case-insensitive lookup on case-sensitive filesystems so behavior
            # matches Windows and user mappings do not fail only because of capitalization.
            candidates = [
                path for path in pdf_dir.glob("*.pdf")
                if path.name.casefold() == pair.old_pdf.casefold()
            ]
            if len(candidates) == 1:
                old_pdf = candidates[0]
            else:
                raise FileNotFoundError(f"No existe el PDF fuente: {pdf_dir / pair.old_pdf}")

        moves.append(Move(old_pdf, new_pdf, "pdf"))

        companions = (
            (
                extracted_dir / f"{pair.old_stem}.md",
                extracted_dir / f"{pair.new_stem}.md",
                "extracted",
            ),
            (
                references_dir / f"{pair.old_stem}.references.md",
                references_dir / f"{pair.new_stem}.references.md",
                "references",
            ),
            (
                assets_dir / pair.old_stem,
                assets_dir / pair.new_stem,
                "assets",
            ),
        )
        for source, destination, kind in companions:
            if source.exists():
                moves.append(Move(source, destination, kind))

    return tuple(moves)


def _validate_moves(moves: tuple[Move, ...]) -> None:
    source_keys = {_path_key(move.source) for move in moves}
    target_to_move: dict[str, Move] = {}

    for move in moves:
        target_key = _path_key(move.destination)
        previous = target_to_move.get(target_key)
        if previous is not None and _path_key(previous.source) != _path_key(move.source):
            raise FileExistsError(
                f"Dos movimientos tienen el mismo destino: {move.destination}"
            )
        target_to_move[target_key] = move

    for move in moves:
        target_key = _path_key(move.destination)
        if move.destination.exists() and target_key not in source_keys:
            raise FileExistsError(
                f"El destino ya existe y no será movido por este mapping: {move.destination}"
            )


def _active_markdown_files(bib: Path) -> list[Path]:
    files: list[Path] = []
    for path in bib.rglob("*.md"):
        try:
            rel = path.relative_to(bib)
        except ValueError:
            continue
        if ".backups" in rel.parts:
            continue
        files.append(path)
    return sorted(files, key=lambda path: str(path).casefold())


def _simultaneous_replace(text: str, replacements: list[tuple[str, str]]) -> str:
    """Apply literal replacements without cascades, including A->B / B->A swaps."""
    unique: dict[str, str] = {}
    for old, new in replacements:
        if old == new:
            continue
        existing = unique.get(old)
        if existing is not None and existing != new:
            raise ValueError(f"Reemplazos internos conflictivos para {old!r}.")
        unique[old] = new

    placeholders: list[tuple[str, str]] = []
    updated = text
    for index, old in enumerate(sorted(unique, key=len, reverse=True)):
        token = f"\x00RENAME_LITERATURE_{index}_{uuid.uuid4().hex}\x00"
        updated = updated.replace(old, token)
        placeholders.append((token, unique[old]))

    for token, new in placeholders:
        updated = updated.replace(token, new)
    return updated


def _rewrite_front_matter_ids(
    text: str,
    pairs: tuple[RenamePair, ...],
) -> str:
    if not text.startswith("---\n"):
        return text
    end = text.find("\n---\n", 4)
    if end == -1:
        return text

    front = text[: end + len("\n---\n")]
    body = text[end + len("\n---\n") :]

    id_map: dict[str, str] = {}
    for pair in pairs:
        id_map[pair.old_stem.casefold()] = pair.new_stem
        id_map[f"{pair.old_stem}-references".casefold()] = (
            f"{pair.new_stem}-references"
        )

    pattern = re.compile(
        r'(?m)^(?P<prefix>\s*id:\s*["\']?)(?P<value>[^"\'\n]+)(?P<suffix>["\']?\s*)$'
    )

    def replace_id(match: re.Match[str]) -> str:
        value = match.group("value")
        new_value = id_map.get(value.casefold())
        if new_value is None:
            return match.group(0)
        return f"{match.group('prefix')}{new_value}{match.group('suffix')}"

    front = pattern.sub(replace_id, front)
    return front + body


def rewrite_markdown_text(text: str, pairs: tuple[RenamePair, ...]) -> str:
    """Rewrite file/path references without blindly replacing arbitrary paper text."""
    replacements: list[tuple[str, str]] = []
    for pair in pairs:
        replacements.extend(
            [
                (f"{pair.old_stem}.references.md", f"{pair.new_stem}.references.md"),
                (f"{pair.old_stem}.md", f"{pair.new_stem}.md"),
                (pair.old_pdf, pair.new_pdf),
                (f"assets/{pair.old_stem}", f"assets/{pair.new_stem}"),
                (f"assets\\{pair.old_stem}", f"assets\\{pair.new_stem}"),
            ]
        )

    updated = _simultaneous_replace(text, replacements)
    return _rewrite_front_matter_ids(updated, pairs)


def _stage_moves(moves: tuple[Move, ...]) -> list[tuple[Move, Path]]:
    staged: list[tuple[Move, Path]] = []
    try:
        for move in moves:
            if move.source == move.destination:
                continue
            token = uuid.uuid4().hex
            temp = move.source.with_name(
                f".rename-literature-{token}-{move.source.name}"
            )
            move.source.rename(temp)
            staged.append((move, temp))
    except Exception:
        for move, temp in reversed(staged):
            if temp.exists():
                temp.rename(move.source)
        raise
    return staged


def _finish_moves(staged: list[tuple[Move, Path]]) -> None:
    finished: list[tuple[Move, Path]] = []
    try:
        for move, temp in staged:
            temp.rename(move.destination)
            finished.append((move, temp))
    except Exception:
        # Move finalized destinations back to their temp slots, then all temps to sources.
        for move, temp in reversed(finished):
            if move.destination.exists():
                move.destination.rename(temp)
        for move, temp in reversed(staged):
            if temp.exists():
                temp.rename(move.source)
        raise


def _rollback_completed_moves(staged: list[tuple[Move, Path]]) -> None:
    """Undo a fully completed two-phase move set."""
    for move, temp in reversed(staged):
        if move.destination.exists():
            move.destination.rename(temp)
    for move, temp in reversed(staged):
        if temp.exists():
            temp.rename(move.source)


def _preview_markdown_changes(
    bib: Path,
    pairs: tuple[RenamePair, ...],
) -> tuple[Path, ...]:
    changed: list[Path] = []
    for path in _active_markdown_files(bib):
        original = path.read_text(encoding="utf-8", errors="replace")
        if rewrite_markdown_text(original, pairs) != original:
            changed.append(path)
    return tuple(changed)


def rename_literature(
    mapping: Mapping[str, str],
    *,
    repo: str | Path | None = None,
    dry_run: bool = False,
) -> RenameReport:
    """Rename literature files and all active Markdown references consistently.

    Parameters
    ----------
    mapping:
        Dictionary mapping current PDF filename/stem -> desired PDF filename/stem.
    repo:
        Project root containing bib/pdf. If omitted, search upward from cwd.
    dry_run:
        Validate and report changes without modifying the filesystem.
    """
    pairs = normalize_mapping(mapping)
    root = (
        Path(repo).expanduser().resolve()
        if repo is not None
        else discover_repo_root()
    )
    bib = resolve_bib_dir(root)
    if not (bib / "pdf").is_dir():
        raise FileNotFoundError(f"No existe {bib / 'pdf'}")

    moves = _planned_moves(bib, pairs)
    _validate_moves(moves)
    markdown_preview = _preview_markdown_changes(bib, pairs)

    if dry_run:
        return RenameReport(
            mapping=pairs,
            moves=moves,
            markdown_files_changed=markdown_preview,
            dry_run=True,
        )

    # Snapshot Markdown before any filesystem operation so a rewrite failure can restore
    # the exact original corpus after rolling filenames back.
    markdown_snapshot = {
        path: path.read_text(encoding="utf-8", errors="replace")
        for path in _active_markdown_files(bib)
    }

    staged = _stage_moves(moves)
    try:
        _finish_moves(staged)

        changed_after_move: list[Path] = []
        for path in _active_markdown_files(bib):
            original = path.read_text(encoding="utf-8", errors="replace")
            updated = rewrite_markdown_text(original, pairs)
            if updated != original:
                tmp = path.with_name(f".{path.name}.rename-literature.tmp")
                tmp.write_text(updated, encoding="utf-8")
                tmp.replace(path)
                changed_after_move.append(path)

    except Exception:
        _rollback_completed_moves(staged)
        for path, text in markdown_snapshot.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        raise

    return RenameReport(
        mapping=pairs,
        moves=moves,
        markdown_files_changed=tuple(changed_after_move),
        dry_run=False,
    )


def _load_json_mapping(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("El archivo JSON debe contener un objeto/diccionario old -> new.")
    mapping: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Todas las claves y valores del mapping JSON deben ser strings.")
        mapping[key] = value
    return mapping


def _parse_rename_arg(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError(
            "--rename requiere OLD=NEW, por ejemplo 123.pdf=Smith-2024-Paper.pdf"
        )
    old, new = value.split("=", 1)
    if not old.strip() or not new.strip():
        raise argparse.ArgumentTypeError("--rename requiere OLD=NEW con ambos nombres.")
    return old.strip(), new.strip()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="rename_literature",
        description=(
            "Renombra PDFs de bib/pdf y sincroniza Markdown, referencias, assets, "
            "INDEX.md y bundle.md."
        ),
    )
    parser.add_argument("--repo", type=Path, default=None)
    parser.add_argument(
        "--map",
        dest="map_file",
        type=Path,
        default=None,
        help='JSON con {"old.pdf": "new.pdf", ...}.',
    )
    parser.add_argument(
        "--rename",
        action="append",
        type=_parse_rename_arg,
        default=[],
        metavar="OLD=NEW",
        help="Renombrado individual; puede repetirse.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Valida y muestra el plan sin modificar archivos.",
    )
    return parser.parse_args(argv)


def _mapping_from_args(args: argparse.Namespace) -> dict[str, str]:
    mapping: dict[str, str] = {}
    if args.map_file is not None:
        mapping.update(_load_json_mapping(args.map_file.expanduser().resolve()))

    for old, new in args.rename:
        existing = mapping.get(old)
        if existing is not None and existing != new:
            raise ValueError(f"Mapping conflictivo para {old!r}: {existing!r} vs {new!r}")
        mapping[old] = new

    if not mapping:
        raise ValueError("Usa --map renames.json o al menos un --rename OLD=NEW.")
    return mapping


def _print_report(report: RenameReport) -> None:
    label = "DRY RUN" if report.dry_run else "DONE"
    print(f"[{label}] {len(report.mapping)} paper(s)")
    for pair in report.mapping:
        print(f"  {pair.old_pdf} -> {pair.new_pdf}")

    if report.moves:
        print(f"[FILES] {len(report.moves)} filesystem move(s)")
        for move in report.moves:
            print(f"  [{move.kind}] {move.source.name} -> {move.destination.name}")

    print(f"[MARKDOWN] {len(report.markdown_files_changed)} file(s) {'would change' if report.dry_run else 'updated'}")
    for path in report.markdown_files_changed:
        print(f"  {path}")


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        mapping = _mapping_from_args(args)
        report = rename_literature(
            mapping,
            repo=args.repo,
            dry_run=args.dry_run,
        )
        _print_report(report)
        return 0
    except KeyboardInterrupt:
        print("[INTERRUPTED]", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
