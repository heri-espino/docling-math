from pathlib import Path

import pytest

from docling_math.rename_literature import rename_literature


def _make_project(tmp_path: Path) -> Path:
    (tmp_path / "bib" / "pdf").mkdir(parents=True)
    (tmp_path / "bib" / "extracted").mkdir()
    (tmp_path / "bib" / "references").mkdir()
    (tmp_path / "bib" / "assets" / "123").mkdir(parents=True)

    (tmp_path / "bib" / "pdf" / "123.pdf").write_bytes(b"%PDF-fake")
    (tmp_path / "bib" / "assets" / "123" / "figure.png").write_bytes(b"png")

    (tmp_path / "bib" / "extracted" / "123.md").write_text(
        """---
id: "123"
source_pdf: "../pdf/123.pdf"
source_filename: "123.pdf"
references_file: "../references/123.references.md"
assets_dir: "../assets/123"
---

# Paper

Source PDF: 123.pdf
""",
        encoding="utf-8",
    )
    (tmp_path / "bib" / "references" / "123.references.md").write_text(
        """---
id: "123-references"
source_pdf: "../pdf/123.pdf"
---

# References
""",
        encoding="utf-8",
    )
    (tmp_path / "bib" / "INDEX.md").write_text(
        """# Literature corpus

- Markdown: `extracted/123.md`
- PDF: `pdf/123.pdf`
- Assets: `assets/123/`
- References: `references/123.references.md`
""",
        encoding="utf-8",
    )
    (tmp_path / "bib" / "bundle.md").write_text(
        """# Bundle

- Source Markdown: extracted/123.md
- Source PDF: pdf/123.pdf
- References: references/123.references.md
""",
        encoding="utf-8",
    )
    (tmp_path / "bib" / "notes.md").write_text(
        "Cross reference to pdf/123.pdf and extracted/123.md.\n",
        encoding="utf-8",
    )
    (tmp_path / "bib" / ".backups").mkdir()
    (tmp_path / "bib" / ".backups" / "INDEX.md.old.md").write_text(
        "pdf/123.pdf",
        encoding="utf-8",
    )
    return tmp_path


def test_rename_updates_files_and_all_active_markdown(tmp_path):
    repo = _make_project(tmp_path)
    new = "CortesToto_Espino-2011-Estimacion_de_tendencia"

    report = rename_literature({"123.pdf": f"{new}.pdf"}, repo=repo)

    assert not (repo / "bib" / "pdf" / "123.pdf").exists()
    assert (repo / "bib" / "pdf" / f"{new}.pdf").exists()
    assert (repo / "bib" / "extracted" / f"{new}.md").exists()
    assert (repo / "bib" / "references" / f"{new}.references.md").exists()
    assert (repo / "bib" / "assets" / new / "figure.png").exists()

    active_markdown = [
        path
        for path in (repo / "bib").rglob("*.md")
        if ".backups" not in path.relative_to(repo / "bib").parts
    ]
    for path in active_markdown:
        text = path.read_text(encoding="utf-8")
        assert "123.pdf" not in text
        assert "extracted/123.md" not in text
        assert "references/123.references.md" not in text
        assert "assets/123" not in text

    extracted = (repo / "bib" / "extracted" / f"{new}.md").read_text(encoding="utf-8")
    refs = (repo / "bib" / "references" / f"{new}.references.md").read_text(encoding="utf-8")
    assert f'id: "{new}"' in extracted
    assert f'id: "{new}-references"' in refs
    assert len(report.markdown_files_changed) >= 4

    # Historical backups are intentionally immutable.
    backup = repo / "bib" / ".backups" / "INDEX.md.old.md"
    assert backup.read_text(encoding="utf-8") == "pdf/123.pdf"


def test_dry_run_changes_nothing(tmp_path):
    repo = _make_project(tmp_path)
    report = rename_literature(
        {"123.pdf": "NewName.pdf"},
        repo=repo,
        dry_run=True,
    )

    assert report.dry_run is True
    assert (repo / "bib" / "pdf" / "123.pdf").exists()
    assert not (repo / "bib" / "pdf" / "NewName.pdf").exists()
    assert (repo / "bib" / "extracted" / "123.md").exists()


def test_refuses_existing_destination_without_partial_changes(tmp_path):
    repo = _make_project(tmp_path)
    (repo / "bib" / "pdf" / "Already.pdf").write_bytes(b"other")

    with pytest.raises(FileExistsError):
        rename_literature({"123.pdf": "Already.pdf"}, repo=repo)

    assert (repo / "bib" / "pdf" / "123.pdf").exists()
    assert (repo / "bib" / "pdf" / "Already.pdf").exists()
    assert (repo / "bib" / "extracted" / "123.md").exists()


def test_swap_is_safe(tmp_path):
    bib = tmp_path / "bib"
    (bib / "pdf").mkdir(parents=True)
    (bib / "extracted").mkdir()

    (bib / "pdf" / "A.pdf").write_bytes(b"A")
    (bib / "pdf" / "B.pdf").write_bytes(b"B")
    (bib / "extracted" / "A.md").write_text(
        '---\nid: "A"\nsource_pdf: "../pdf/A.pdf"\n---\n',
        encoding="utf-8",
    )
    (bib / "extracted" / "B.md").write_text(
        '---\nid: "B"\nsource_pdf: "../pdf/B.pdf"\n---\n',
        encoding="utf-8",
    )

    rename_literature(
        {"A.pdf": "B.pdf", "B.pdf": "A.pdf"},
        repo=tmp_path,
    )

    assert (bib / "pdf" / "A.pdf").read_bytes() == b"B"
    assert (bib / "pdf" / "B.pdf").read_bytes() == b"A"
    assert 'id: "B"' in (bib / "extracted" / "B.md").read_text(encoding="utf-8")
    assert 'id: "A"' in (bib / "extracted" / "A.md").read_text(encoding="utf-8")


def test_mapping_accepts_stems_without_pdf_extension(tmp_path):
    repo = _make_project(tmp_path)
    rename_literature({"123": "Readable_Name"}, repo=repo)
    assert (repo / "bib" / "pdf" / "Readable_Name.pdf").exists()
