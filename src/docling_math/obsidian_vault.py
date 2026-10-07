"""Sync the extracted literature corpus into an Obsidian vault."""

from __future__ import annotations

import shutil
from pathlib import Path

from .markdown_metadata import enrich_markdown_text
from .metadata import infer_paper_metadata


def sync_obsidian_vault(
    *,
    bib_dir: Path,
    vault_dir: Path,
    folder_name: str = "Literature",
) -> tuple[int, int]:
    """Copy notes and PDFs into a self-contained Obsidian literature folder.

    Notes go to <vault>/Literature and PDFs to <vault>/Literature/Attachments.
    Existing files with the same names are replaced; unrelated vault content is untouched.
    """
    vault = vault_dir.expanduser().resolve()
    root = vault / folder_name
    attachments = root / "Attachments"
    root.mkdir(parents=True, exist_ok=True)
    attachments.mkdir(parents=True, exist_ok=True)

    extracted = bib_dir / "extracted"
    pdf_dir = bib_dir / "pdf"

    notes = 0
    pdfs = 0

    for md_path in sorted(extracted.glob("*.md"), key=lambda p: p.name.casefold()):
        pdf_path = pdf_dir / f"{md_path.stem}.pdf"
        if not pdf_path.exists():
            continue

        text = md_path.read_text(encoding="utf-8", errors="replace")
        metadata = infer_paper_metadata(text)
        obsidian_text = enrich_markdown_text(
            text,
            paper_id=md_path.stem,
            pdf_name=pdf_path.name,
            metadata=metadata,
            obsidian=True,
            pdf_link=f"Attachments/{pdf_path.name}",
        )
        (root / md_path.name).write_text(obsidian_text, encoding="utf-8")
        shutil.copy2(pdf_path, attachments / pdf_path.name)
        notes += 1
        pdfs += 1

    index_path = bib_dir / "INDEX.md"
    if index_path.exists():
        shutil.copy2(index_path, root / "_Index.md")

    bundle_path = bib_dir / "bundle.md"
    if bundle_path.exists():
        shutil.copy2(bundle_path, root / "_Bundle.md")

    return notes, pdfs
