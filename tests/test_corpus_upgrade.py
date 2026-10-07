from pathlib import Path

import yaml

from docling_math.corpus_upgrade import (
    rebuild_bundle,
    rebuild_index,
    resolve_corpus_dir,
    upgrade_corpus,
)


OLD_MARKDOWN = """---
id: "123"
source_pdf: "../pdf/123.pdf"
source_filename: "123.pdf"
format: "academic-paper"
extraction_mode: "hybrid"
extraction_quality: "good"
extraction_score: 88.2
---

# Estimacion de tendencia

Daniela Cortes-Toto y Heriberto Espino

Journal of Trend Research Vol. 12
© 2011
doi: 10.1234/example.2011.42

## Abstract

This article studies several methods for estimating smooth trends in noisy time series.

Keywords: Trend estimation; Time series analysis

## Introduction

Original body that must remain intact.
"""


def _front(markdown: str) -> dict:
    end = markdown.index("\n---\n", 4)
    return yaml.safe_load(markdown[4:end])


def _make_old_corpus(tmp_path: Path) -> Path:
    bib = tmp_path / "project" / "bib"
    (bib / "pdf").mkdir(parents=True)
    (bib / "extracted").mkdir()
    (bib / "references").mkdir()
    (bib / "pdf" / "123.pdf").write_bytes(b"%PDF-old-placeholder")
    (bib / "extracted" / "123.md").write_text(OLD_MARKDOWN, encoding="utf-8")
    (bib / "references" / "123.references.md").write_text(
        """---
id: "123-references"
source_pdf: "../pdf/123.pdf"
---
# References

Reference A.
""",
        encoding="utf-8",
    )
    (bib / "INDEX.md").write_text("# Old index\n", encoding="utf-8")
    (bib / "bundle.md").write_text("# Old bundle\n", encoding="utf-8")
    return bib


def test_resolve_corpus_accepts_project_bib_and_extracted(tmp_path):
    bib = _make_old_corpus(tmp_path)

    assert resolve_corpus_dir(bib) == bib.resolve()
    assert resolve_corpus_dir(bib.parent) == bib.resolve()
    assert resolve_corpus_dir(bib / "extracted") == bib.resolve()


def test_upgrade_corpus_migrates_metadata_without_touching_body(tmp_path):
    bib = _make_old_corpus(tmp_path)
    body_marker = "Original body that must remain intact."

    report = upgrade_corpus(bib)

    assert report.papers_seen == 1
    assert report.markdown_updated == 1
    assert report.pdf_metadata_updated == 0
    assert report.missing_pdfs == ()

    upgraded = (bib / "extracted" / "123.md").read_text(encoding="utf-8")
    front = _front(upgraded)

    assert body_marker in upgraded
    assert front["title"] == "Estimacion de tendencia"
    assert front["authors"] == ["Daniela Cortes-Toto", "Heriberto Espino"]
    assert front["year"] == 2011
    assert front["doi"] == "10.1234/example.2011.42"
    assert front["keywords"] == ["Trend estimation", "Time series analysis"]
    assert "literature" in front["tags"]
    assert "trend-estimation" in front["tags"]
    assert front["aliases"] == ["Estimacion de tendencia"]

    index = (bib / "INDEX.md").read_text(encoding="utf-8")
    bundle = (bib / "bundle.md").read_text(encoding="utf-8")

    assert "Daniela Cortes-Toto; Heriberto Espino" in index
    assert "Trend estimation" in index
    assert "P001" in bundle
    assert body_marker in bundle

    backups = list((bib / ".backups").glob("upgrade-*"))
    assert len(backups) == 1
    assert (backups[0] / "INDEX.md").read_text(encoding="utf-8") == "# Old index\n"
    assert (backups[0] / "bundle.md").read_text(encoding="utf-8") == "# Old bundle\n"


def test_upgrade_with_obsidian_adds_related_without_ocr(tmp_path):
    bib = _make_old_corpus(tmp_path)

    second = """# Another trend paper

Jane Smith and John Doe

Published 2015

Keywords: Time series analysis; Bayesian inference

## Abstract

This is a second paper about time series analysis and Bayesian trend models.
"""
    (bib / "pdf" / "other.pdf").write_bytes(b"%PDF-other")
    (bib / "extracted" / "other.md").write_text(second, encoding="utf-8")

    report = upgrade_corpus(bib, obsidian=True)

    assert report.papers_seen == 2
    assert report.related_notes_updated == 2

    first_front = _front((bib / "extracted" / "123.md").read_text(encoding="utf-8"))
    second_front = _front((bib / "extracted" / "other.md").read_text(encoding="utf-8"))

    assert first_front["pdf"] == "[[123.pdf]]"
    assert second_front["pdf"] == "[[other.pdf]]"
    assert first_front["related"] == ["[[other]]"]
    assert second_front["related"] == ["[[123]]"]


def test_upgrade_reports_missing_pdf_but_still_updates_markdown(tmp_path):
    bib = _make_old_corpus(tmp_path)
    (bib / "pdf" / "123.pdf").unlink()

    report = upgrade_corpus(bib)

    assert report.papers_seen == 1
    assert report.missing_pdfs == ("123.pdf",)
    assert "title:" in (bib / "extracted" / "123.md").read_text(encoding="utf-8")


def test_rebuild_helpers_work_independently(tmp_path):
    bib = _make_old_corpus(tmp_path)
    upgrade_corpus(bib)

    index_path = rebuild_index(bib)
    bundle_path = rebuild_bundle(bib, include_references=True)

    assert index_path.exists()
    assert bundle_path.exists()
    bundle = bundle_path.read_text(encoding="utf-8")
    assert "Reference A." in bundle
