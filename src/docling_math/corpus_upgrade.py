"""Upgrade an existing docling-math corpus without re-running extraction or OCR."""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .markdown_metadata import enrich_markdown_text, update_related_papers
from .metadata import infer_paper_metadata, split_front_matter
from .obsidian_vault import sync_obsidian_vault
from .pdf_metadata import write_pdf_metadata


@dataclass(frozen=True)
class UpgradeReport:
    corpus_dir: Path
    papers_seen: int
    markdown_updated: int
    pdf_metadata_updated: int
    missing_pdfs: tuple[str, ...]
    related_notes_updated: int
    index_path: Path
    bundle_path: Path
    obsidian_notes: int = 0
    obsidian_pdfs: int = 0


def resolve_corpus_dir(path: str | Path) -> Path:
    """Resolve project root, bib directory, or extracted directory to corpus bib."""
    selected = Path(path).expanduser().resolve()

    candidates: list[Path] = [selected]
    if selected.name.casefold() == "extracted":
        candidates.append(selected.parent)
    candidates.extend([selected / "bib", selected / "Bib"])

    seen: set[Path] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        if (candidate / "pdf").is_dir() and (candidate / "extracted").is_dir():
            return candidate

    raise FileNotFoundError(
        "La carpeta seleccionada no parece un corpus docling-math. "
        "Selecciona la raiz del proyecto, su carpeta bib, o bib/extracted."
    )


def discover_corpus_from_cwd() -> Path:
    """Search upward from cwd for a usable literature corpus."""
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        try:
            return resolve_corpus_dir(candidate)
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        "No pude localizar un corpus con bib/pdf y bib/extracted. "
        "Usa --corpus-dir o --select-folder."
    )


def select_corpus_folder() -> Path:
    """Open a native directory picker and resolve the selected folder."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception as exc:
        raise RuntimeError(
            "El selector grafico de carpetas no esta disponible en este Python. "
            "Usa --corpus-dir C:\\ruta\\al\\proyecto."
        ) from exc

    root = tk.Tk()
    root.withdraw()
    try:
        selected = filedialog.askdirectory(
            title="Select docling-math corpus",
            mustexist=True,
        )
    finally:
        root.destroy()

    if not selected:
        raise RuntimeError("No se selecciono ninguna carpeta.")
    return resolve_corpus_dir(selected)


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.upgrade.tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _backup_managed_files(corpus_dir: Path) -> Path | None:
    managed = [corpus_dir / "INDEX.md", corpus_dir / "bundle.md"]
    existing = [path for path in managed if path.exists()]
    if not existing:
        return None

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir = corpus_dir / ".backups" / f"upgrade-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)
    for path in existing:
        shutil.copy2(path, backup_dir / path.name)
    return backup_dir


def _metadata_for(path: Path):
    return infer_paper_metadata(path.read_text(encoding="utf-8", errors="replace"))


def rebuild_index(corpus_dir: Path) -> Path:
    """Rebuild INDEX.md from upgraded Markdown without extraction diagnostics."""
    extracted_dir = corpus_dir / "extracted"
    pdf_dir = corpus_dir / "pdf"
    refs_dir = corpus_dir / "references"
    assets_dir = corpus_dir / "assets"
    index_path = corpus_dir / "INDEX.md"

    lines = [
        "# Literature corpus",
        "",
        "Index rebuilt by docling-math --upgrade-corpus from existing extracted Markdown.",
        "",
        "## Papers",
        "",
    ]

    for md_path in sorted(extracted_dir.glob("*.md"), key=lambda p: p.name.casefold()):
        pdf_path = pdf_dir / f"{md_path.stem}.pdf"
        raw = md_path.read_text(encoding="utf-8", errors="replace")
        metadata = infer_paper_metadata(raw)
        title = metadata.title or md_path.stem.replace("_", " ").replace("-", " ")
        front, _body = split_front_matter(raw)

        lines.extend(
            [
                f"### {title}",
                "",
                f"- Markdown: extracted/{md_path.name}",
            ]
        )
        if pdf_path.exists():
            lines.append(f"- PDF: pdf/{pdf_path.name}")
        if metadata.authors:
            lines.append("- Authors: " + "; ".join(metadata.authors))
        if metadata.year is not None:
            lines.append(f"- Year: {metadata.year}")
        if metadata.journal:
            lines.append(f"- Journal: {metadata.journal}")
        if metadata.doi:
            lines.append(f"- DOI: {metadata.doi}")
        if metadata.keywords:
            lines.append("- Keywords: " + "; ".join(metadata.keywords))
        if metadata.tags:
            lines.append("- Tags: " + ", ".join(metadata.tags))

        extraction_mode = front.get("extraction_mode")
        extraction_quality = front.get("extraction_quality")
        extraction_score = front.get("extraction_score")
        if extraction_mode:
            lines.append(f"- Extraction: {extraction_mode}")
        if extraction_quality:
            quality = str(extraction_quality)
            if extraction_score is not None:
                quality += f" ({extraction_score})"
            lines.append(f"- Quality: {quality}")

        refs_path = refs_dir / f"{md_path.stem}.references.md"
        if refs_path.exists():
            lines.append(f"- References: references/{refs_path.name}")

        asset_path = assets_dir / md_path.stem
        if asset_path.exists():
            lines.append(f"- Assets: assets/{md_path.stem}/")

        lines.append("")

    _write_atomic(index_path, "\n".join(lines).rstrip() + "\n")
    return index_path


def rebuild_bundle(
    corpus_dir: Path,
    *,
    include_references: bool = False,
) -> Path:
    """Rebuild an AI-readable bundle from the upgraded corpus."""
    extracted_dir = corpus_dir / "extracted"
    pdf_dir = corpus_dir / "pdf"
    refs_dir = corpus_dir / "references"
    bundle_path = corpus_dir / "bundle.md"

    md_files = sorted(extracted_dir.glob("*.md"), key=lambda p: p.name.casefold())
    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")

    lines = [
        "---",
        'format: "docling-math-corpus-bundle"',
        f'generated_at: "{generated_at}"',
        f"paper_count: {len(md_files)}",
        f"references_included: {'true' if include_references else 'false'}",
        'source_directory: "extracted/"',
        "---",
        "",
        "# Literature bundle",
        "",
        "Machine-oriented corpus rebuilt from existing docling-math Markdown without OCR.",
        "",
        "## Corpus map",
        "",
    ]

    blocks: list[str] = []
    for index, md_path in enumerate(md_files, 1):
        paper_id = f"P{index:03d}"
        raw = md_path.read_text(encoding="utf-8", errors="replace")
        metadata = infer_paper_metadata(raw)
        _front, body = split_front_matter(raw)
        title = metadata.title or md_path.stem.replace("_", " ").replace("-", " ")
        pdf_path = pdf_dir / f"{md_path.stem}.pdf"
        refs_path = refs_dir / f"{md_path.stem}.references.md"

        lines.append(f"{index}. **{paper_id} — {title}**")
        if metadata.authors:
            lines.append("   - Authors: " + "; ".join(metadata.authors))
        if metadata.year is not None:
            lines.append(f"   - Year: {metadata.year}")
        if metadata.keywords:
            lines.append("   - Keywords: " + "; ".join(metadata.keywords))
        if metadata.tags:
            lines.append("   - Tags: " + ", ".join(metadata.tags))

        block = [
            "",
            f"<!-- ===== BEGIN PAPER {paper_id} ===== -->",
            "",
            f"# {paper_id} — {title}",
            "",
            f"- Source Markdown: extracted/{md_path.name}",
        ]
        if pdf_path.exists():
            block.append(f"- Source PDF: pdf/{pdf_path.name}")
        if metadata.authors:
            block.append("- Authors: " + "; ".join(metadata.authors))
        if metadata.year is not None:
            block.append(f"- Year: {metadata.year}")
        if metadata.journal:
            block.append(f"- Journal: {metadata.journal}")
        if metadata.doi:
            block.append(f"- DOI: {metadata.doi}")
        if metadata.keywords:
            block.append("- Keywords: " + "; ".join(metadata.keywords))
        if metadata.tags:
            block.append("- Tags: " + ", ".join(metadata.tags))
        if refs_path.exists():
            block.append(f"- References: references/{refs_path.name}")

        block.extend(
            [
                "",
                "<!-- BEGIN EXTRACTED CONTENT -->",
                "",
                body.strip(),
                "",
                "<!-- END EXTRACTED CONTENT -->",
            ]
        )

        if include_references and refs_path.exists():
            refs_raw = refs_path.read_text(encoding="utf-8", errors="replace")
            _refs_front, refs_body = split_front_matter(refs_raw)
            block.extend(
                [
                    "",
                    f"## {paper_id} — References",
                    "",
                    refs_body.strip(),
                ]
            )

        block.extend(
            [
                "",
                f"<!-- ===== END PAPER {paper_id} ===== -->",
                "",
            ]
        )
        blocks.append("\n".join(block))

    content = "\n".join(lines).rstrip() + "\n"
    if blocks:
        content += "\n## Papers\n" + "".join(blocks)
    _write_atomic(bundle_path, content.rstrip() + "\n")
    return bundle_path


def upgrade_corpus(
    corpus: str | Path,
    *,
    obsidian: bool = False,
    related_papers: bool = True,
    write_pdf_metadata_enabled: bool = False,
    obsidian_vault: str | Path | None = None,
    include_references_in_bundle: bool = False,
) -> UpgradeReport:
    """Upgrade a v0.1+ corpus in place without extraction, OCR, or model loading."""
    corpus_dir = resolve_corpus_dir(corpus)
    extracted_dir = corpus_dir / "extracted"
    pdf_dir = corpus_dir / "pdf"

    _backup_managed_files(corpus_dir)

    papers_seen = 0
    markdown_updated = 0
    pdf_metadata_updated = 0
    missing_pdfs: list[str] = []

    for md_path in sorted(extracted_dir.glob("*.md"), key=lambda p: p.name.casefold()):
        papers_seen += 1
        pdf_path = pdf_dir / f"{md_path.stem}.pdf"
        original = md_path.read_text(encoding="utf-8", errors="replace")
        metadata = infer_paper_metadata(original)

        enriched = enrich_markdown_text(
            original,
            paper_id=md_path.stem,
            pdf_name=pdf_path.name,
            metadata=metadata,
            obsidian=obsidian,
        )
        if enriched != original:
            _write_atomic(md_path, enriched)
            markdown_updated += 1

        if not pdf_path.exists():
            missing_pdfs.append(pdf_path.name)
            continue

        if write_pdf_metadata_enabled:
            if write_pdf_metadata(pdf_path, metadata):
                pdf_metadata_updated += 1
                latest = md_path.read_text(encoding="utf-8", errors="replace")
                _write_atomic(md_path, latest)

    related_changed = 0
    if obsidian and related_papers:
        related_changed = update_related_papers(extracted_dir)

    index_path = rebuild_index(corpus_dir)
    bundle_path = rebuild_bundle(
        corpus_dir,
        include_references=include_references_in_bundle,
    )

    obsidian_notes = 0
    obsidian_pdfs = 0
    if obsidian_vault is not None:
        obsidian_notes, obsidian_pdfs = sync_obsidian_vault(
            bib_dir=corpus_dir,
            vault_dir=Path(obsidian_vault),
        )

    return UpgradeReport(
        corpus_dir=corpus_dir,
        papers_seen=papers_seen,
        markdown_updated=markdown_updated,
        pdf_metadata_updated=pdf_metadata_updated,
        missing_pdfs=tuple(missing_pdfs),
        related_notes_updated=related_changed,
        index_path=index_path,
        bundle_path=bundle_path,
        obsidian_notes=obsidian_notes,
        obsidian_pdfs=obsidian_pdfs,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="upgrade-corpus",
        description="Upgrade an existing docling-math corpus without re-running OCR.",
    )
    parser.add_argument(
        "--corpus-dir",
        type=Path,
        default=None,
        help="Project root, bib directory, or bib/extracted directory.",
    )
    parser.add_argument(
        "--select-folder",
        action="store_true",
        help="Open a native folder picker instead of typing a path.",
    )
    parser.add_argument("--obsidian", action="store_true")
    parser.add_argument(
        "--related-papers",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument("--write-pdf-metadata", action="store_true")
    parser.add_argument("--obsidian-vault", type=Path, default=None)
    parser.add_argument("--bundle-references", action="store_true")
    return parser.parse_args(argv)


def resolve_cli_corpus(args: argparse.Namespace) -> Path:
    if args.select_folder and args.corpus_dir is not None:
        raise ValueError("Usa --select-folder o --corpus-dir, no ambos.")
    if args.select_folder:
        return select_corpus_folder()
    if args.corpus_dir is not None:
        return resolve_corpus_dir(args.corpus_dir)
    return discover_corpus_from_cwd()


def print_report(report: UpgradeReport) -> None:
    print("=" * 72)
    print(" DOCLING-MATH — CORPUS UPGRADE")
    print("=" * 72)
    print(f"Corpus             : {report.corpus_dir}")
    print(f"Papers             : {report.papers_seen}")
    print(f"Markdown updated   : {report.markdown_updated}")
    print(f"PDF metadata       : {report.pdf_metadata_updated}")
    print(f"Related notes      : {report.related_notes_updated}")
    print(f"Missing PDFs       : {len(report.missing_pdfs)}")
    print(f"INDEX              : {report.index_path}")
    print(f"Bundle             : {report.bundle_path}")
    if report.obsidian_notes or report.obsidian_pdfs:
        print(
            f"Obsidian sync      : {report.obsidian_notes} notes, "
            f"{report.obsidian_pdfs} PDFs"
        )
    if report.missing_pdfs:
        print("Missing PDF names:")
        for name in report.missing_pdfs:
            print(f"  - {name}")
    print("=" * 72)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        corpus_dir = resolve_cli_corpus(args)
        obsidian = bool(args.obsidian or args.obsidian_vault is not None)
        report = upgrade_corpus(
            corpus_dir,
            obsidian=obsidian,
            related_papers=args.related_papers,
            write_pdf_metadata_enabled=args.write_pdf_metadata,
            obsidian_vault=args.obsidian_vault,
            include_references_in_bundle=args.bundle_references,
        )
        print_report(report)
        return 0
    except KeyboardInterrupt:
        print("[INTERRUPTED]", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
