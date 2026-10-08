"""Desktop launcher and process orchestration for docling-math.

This module deliberately imports neither Tk nor Docling at module import time. It can
therefore be tested and used for metadata-only jobs without GPU/model initialization.
"""

from __future__ import annotations

import builtins
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping, Sequence

from .corpus_upgrade import resolve_corpus_dir


JobKind = Literal["extract", "upgrade", "rename"]


@dataclass(frozen=True)
class WorkerStep:
    kind: JobKind
    arguments: tuple[str, ...]
    label: str


def resolve_or_create_library(folder: str | Path, *, create: bool = False) -> Path:
    """Resolve a selected project/bib folder; only create new libraries on request."""
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")

    try:
        return resolve_corpus_dir(folder)
    except FileNotFoundError:
        if not create:
            raise

    if folder.name.casefold() == "bib":
        bib = folder
    else:
        bib = folder / "bib"
    (bib / "pdf").mkdir(parents=True, exist_ok=True)
    (bib / "extracted").mkdir(parents=True, exist_ok=True)
    (bib / "references").mkdir(parents=True, exist_ok=True)
    return bib.resolve()


def plan_extract(
    bib: str | Path,
    *,
    strategy: str = "compare",
    device: str = "auto",
    rename_pdfs: bool = False,
    write_pdf_metadata: bool = False,
    assets: bool = False,
    create_vault: bool = True,
    obsidian: bool = True,
    vault_path: str | Path | None = None,
) -> tuple[WorkerStep, ...]:
    """Build safe, explicit commands for extraction and optional vault synchronization."""
    corpus = resolve_corpus_dir(bib)
    if strategy not in {"compare", "smart", "hybrid", "ocr"}:
        raise ValueError(f"Unknown extraction strategy: {strategy}")
    if device not in {"auto", "cuda", "mps", "cpu"}:
        raise ValueError(f"Unknown device: {device}")

    extract_args = [
        "--repo",
        str(corpus.parent),
        "--strategy",
        strategy,
        "--device",
        device,
    ]
    if rename_pdfs:
        extract_args.append("--rename-pdfs")
    if write_pdf_metadata:
        extract_args.append("--write-pdf-metadata")
    if assets:
        extract_args.append("--assets")
    if obsidian:
        extract_args.append("--obsidian")

    steps = [WorkerStep("extract", tuple(extract_args), "Extracting PDFs")]
    if create_vault or obsidian:
        steps.append(
            plan_upgrade(
                corpus,
                create_vault=create_vault,
                obsidian=obsidian,
                vault_path=vault_path,
            )
        )
    return tuple(steps)


def plan_upgrade(
    bib: str | Path,
    *,
    create_vault: bool = True,
    obsidian: bool = True,
    write_pdf_metadata: bool = False,
    vault_path: str | Path | None = None,
) -> WorkerStep:
    corpus = resolve_corpus_dir(bib)
    if vault_path is not None and not create_vault:
        raise ValueError("A custom vault path requires vault creation.")

    args = ["--corpus-dir", str(corpus)]
    if not obsidian:
        args.append("--no-obsidian")
    if not create_vault:
        args.append("--no-vault")
    if vault_path is not None:
        args.extend(["--obsidian-vault", str(Path(vault_path).expanduser().resolve())])
    if write_pdf_metadata:
        args.append("--write-pdf-metadata")
    return WorkerStep("upgrade", tuple(args), "Upgrading corpus")


def plan_rename(
    bib: str | Path,
    mapping_file: str | Path,
    *,
    dry_run: bool,
) -> WorkerStep:
    corpus = resolve_corpus_dir(bib)
    path = Path(mapping_file).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Rename mapping not found: {path}")
    with path.open(encoding="utf-8") as handle:
        mapping = json.load(handle)
    if not isinstance(mapping, dict) or not mapping:
        raise ValueError("Rename mapping must be a non-empty JSON object.")
    if not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items()):
        raise ValueError("Rename mapping must contain only string filename pairs.")

    args = ["--repo", str(corpus.parent), "--map", str(path)]
    if dry_run:
        args.append("--dry-run")
    return WorkerStep("rename", tuple(args), "Previewing renames" if dry_run else "Renaming PDFs")


def worker_command(step: WorkerStep, *, executable: str | None = None) -> list[str]:
    """Build the correct command for source installs and frozen Windows executables."""
    exe = executable or sys.executable
    if getattr(sys, "frozen", False):
        return [exe, "--docling-math-worker", step.kind, *step.arguments]
    return [exe, "-m", "docling_math.desktop", "--docling-math-worker", step.kind, *step.arguments]


def run_worker(kind: str, args: Sequence[str]) -> int:
    """Run a CLI operation in its own process. Heavy Docling import occurs only here."""
    if kind == "extract":
        from . import extractor

        old_argv = sys.argv
        try:
            sys.argv = ["docling-math", *args]
            return extractor.main()
        finally:
            sys.argv = old_argv
    if kind == "upgrade":
        from .corpus_upgrade import main

        return main(list(args))
    if kind == "rename":
        from .rename_literature import main

        return main(list(args))
    print(f"Unknown worker: {kind}", file=sys.stderr)
    return 2


def hidden_process_kwargs(*, log_path: str | Path, allow_cpu: bool = False) -> dict:
    """Spawn a worker without consoles; exchange progress through a UTF-8 log file.

    File-based logging also works when the Windows executable is built in
    PyInstaller windowed mode, where sys.stdout/sys.stdin can be None.
    """
    kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "stdin": subprocess.DEVNULL,
        "env": {
            **os.environ,
            "PYTHONUNBUFFERED": "1",
            "DOCLING_MATH_LOG_FILE": str(Path(log_path).resolve()),
            "DOCLING_MATH_ALLOW_CPU": "1" if allow_cpu else "0",
        },
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--docling-math-worker":
        log_path = os.environ.get("DOCLING_MATH_LOG_FILE")
        if log_path:
            with open(log_path, "a", encoding="utf-8", buffering=1) as stream:
                old_stdout, old_stderr = sys.stdout, sys.stderr
                original_input = builtins.input
                try:
                    sys.stdout = sys.stderr = stream
                    if os.environ.get("DOCLING_MATH_ALLOW_CPU") == "1":
                        builtins.input = lambda _prompt="": "y"
                    if len(args) < 2:
                        print("Missing worker name.", file=sys.stderr)
                        return 2
                    return run_worker(args[1], args[2:])
                finally:
                    builtins.input = original_input
                    sys.stdout, sys.stderr = old_stdout, old_stderr
        if len(args) < 2:
            print("Missing worker name.", file=sys.stderr)
            return 2
        return run_worker(args[1], args[2:])
    if args == ["--self-test"]:
        from . import __version__
        import tkinter
        import pypdf
        import yaml

        assert __version__ and tkinter and pypdf and yaml
        return 0
    if args:
        print(f"Unknown arguments: {args}", file=sys.stderr)
        return 2

    from .desktop_gui import launch

    return launch()


if __name__ == "__main__":
    raise SystemExit(main())
