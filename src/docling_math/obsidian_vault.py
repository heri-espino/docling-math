"""Sync the extracted literature corpus into an Obsidian vault."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import yaml

from .markdown_metadata import enrich_markdown_text
from .metadata import infer_paper_metadata, split_front_matter


def _write_front_and_body(front: dict, body: str) -> str:
    dumped = yaml.safe_dump(
        front,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    ).rstrip()
    return f"---\n{dumped}\n---\n\n{body.lstrip()}"


def _rewrite_corpus_paths_for_vault(text: str) -> str:
    """Translate source-corpus paths to the self-contained vault mirror."""
    text = re.sub(r"extracted/([^\s\x60;,)]+\.md)", r"\1", text)
    text = re.sub(r"pdf/([^\s\x60;,)]+\.pdf)", r"Attachments/PDFs/\1", text)
    text = re.sub(
        r"references/([^\s\x60;,)]+\.references\.md)",
        r"References/\1",
        text,
    )
    text = re.sub(
        r"assets/([^\s\x60;,)]+)",
        r"Attachments/Assets/\1",
        text,
    )
    return text


def sync_obsidian_vault(
    *,
    bib_dir: Path,
    vault_dir: Path,
    folder_name: str = "Literature",
) -> tuple[int, int]:
    """Copy the managed corpus into a self-contained Obsidian literature folder.

    Notes go to <vault>/Literature, PDFs to Attachments/PDFs, optional image assets to
    Attachments/Assets, and split bibliographies to References. Existing managed files with
    the same names are replaced; unrelated vault content is untouched.
    """
    vault = vault_dir.expanduser().resolve()
    root = vault / folder_name
    pdf_attachments = root / "Attachments" / "PDFs"
    asset_attachments = root / "Attachments" / "Assets"
    reference_target = root / "References"

    root.mkdir(parents=True, exist_ok=True)
    pdf_attachments.mkdir(parents=True, exist_ok=True)
    reference_target.mkdir(parents=True, exist_ok=True)

    extracted = bib_dir / "extracted"
    pdf_dir = bib_dir / "pdf"
    refs_dir = bib_dir / "references"
    assets_dir = bib_dir / "assets"

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
            pdf_link=f"Attachments/PDFs/{pdf_path.name}",
        )

        front, body = split_front_matter(obsidian_text)
        front["source_pdf"] = f"Attachments/PDFs/{pdf_path.name}"
        front["source_filename"] = pdf_path.name

        refs_path = refs_dir / f"{md_path.stem}.references.md"
        if refs_path.exists():
            front["references_file"] = f"References/{refs_path.name}"
            refs_text = _rewrite_corpus_paths_for_vault(
                refs_path.read_text(encoding="utf-8", errors="replace")
            )
            (reference_target / refs_path.name).write_text(
                refs_text,
                encoding="utf-8",
            )

        source_assets = assets_dir / md_path.stem
        if source_assets.exists():
            asset_attachments.mkdir(parents=True, exist_ok=True)
            target_assets = asset_attachments / md_path.stem
            shutil.copytree(source_assets, target_assets, dirs_exist_ok=True)
            front["assets_dir"] = f"Attachments/Assets/{md_path.stem}"

        copied_note = _write_front_and_body(front, body)
        (root / md_path.name).write_text(copied_note, encoding="utf-8")
        shutil.copy2(pdf_path, pdf_attachments / pdf_path.name)
        notes += 1
        pdfs += 1

    # Copy any split-reference notes that do not have a matching extracted note too.
    # This keeps the vault mirror complete even for partially migrated/legacy corpora.
    for refs_path in sorted(refs_dir.glob("*.references.md"), key=lambda p: p.name.casefold()):
        target = reference_target / refs_path.name
        if target.exists():
            continue
        refs_text = _rewrite_corpus_paths_for_vault(
            refs_path.read_text(encoding="utf-8", errors="replace")
        )
        target.write_text(refs_text, encoding="utf-8")

    index_path = bib_dir / "INDEX.md"
    if index_path.exists():
        text = _rewrite_corpus_paths_for_vault(
            index_path.read_text(encoding="utf-8", errors="replace")
        )
        (root / "_Index.md").write_text(text, encoding="utf-8")

    bundle_path = bib_dir / "bundle.md"
    if bundle_path.exists():
        text = _rewrite_corpus_paths_for_vault(
            bundle_path.read_text(encoding="utf-8", errors="replace")
        )
        (root / "_Bundle.md").write_text(text, encoding="utf-8")

    return notes, pdfs
