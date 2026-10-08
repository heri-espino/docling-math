from pathlib import Path

import yaml

from docling_math.markdown_metadata import (
    enrich_markdown_text,
    enrich_reference_markdown_text,
    update_related_papers,
)
from docling_math.metadata import canonical_stem, infer_paper_metadata
from docling_math.obsidian_vault import sync_obsidian_vault


SAMPLE = """# Estimacion de tendencia

Daniela Cortes-Toto y Heriberto Espino

Universidad de las Americas Puebla

Journal of Trend Research Vol. 12
© 2011
doi: 10.1234/example.2011.42

## Abstract

This article studies several methods for estimating smooth trends in noisy time series
and compares their empirical behavior on controlled examples.

Keywords: Trend estimation; Time series analysis; Nonparametric smoothing

## Introduction

Text.
"""


def _front(markdown: str) -> dict:
    assert markdown.startswith("---\n")
    end = markdown.index("\n---\n", 4)
    return yaml.safe_load(markdown[4:end])


def test_infer_full_metadata_and_canonical_name():
    metadata = infer_paper_metadata(SAMPLE)

    assert metadata.title == "Estimacion de tendencia"
    assert metadata.authors == ("Daniela Cortes-Toto", "Heriberto Espino")
    assert metadata.year == 2011
    assert metadata.journal == "Journal of Trend Research"
    assert metadata.doi == "10.1234/example.2011.42"
    assert metadata.keywords == (
        "Trend estimation",
        "Time series analysis",
        "Nonparametric smoothing",
    )
    assert "literature" in metadata.tags
    assert "year/2011" in metadata.tags
    assert "author/cortestoto" in metadata.tags
    assert "author/espino" in metadata.tags
    assert "trend-estimation" in metadata.tags
    assert "time-series" in metadata.tags
    assert metadata.aliases == ("Estimacion de tendencia",)
    assert canonical_stem(metadata) == (
        "CortesToto_Espino-2011-Estimacion_de_tendencia"
    )


def test_existing_yaml_values_are_preferred():
    markdown = """---
title: Curated title
authors:
  - Curated Author
year: 2020
journal: Curated Journal
doi: 10.9999/curated
keywords:
  - curated keyword
tags:
  - literature
  - curated-tag
aliases:
  - My alias
---

# Wrong extracted title

Wrong Person

Published 1999
Keywords: wrong keyword
"""
    metadata = infer_paper_metadata(markdown)
    assert metadata.title == "Curated title"
    assert metadata.authors == ("Curated Author",)
    assert metadata.year == 2020
    assert metadata.journal == "Curated Journal"
    assert metadata.doi == "10.9999/curated"
    assert metadata.keywords == ("curated keyword",)
    assert metadata.tags == ("literature", "curated-tag")
    assert metadata.aliases == ("My alias",)


def test_obsidian_front_matter_is_structured():
    metadata = infer_paper_metadata(SAMPLE)
    enriched = enrich_markdown_text(
        SAMPLE,
        paper_id="CortesToto_Espino-2011-Estimacion_de_tendencia",
        pdf_name="CortesToto_Espino-2011-Estimacion_de_tendencia.pdf",
        metadata=metadata,
        obsidian=True,
    )
    front = _front(enriched)

    assert front["title"] == "Estimacion de tendencia"
    assert front["authors"] == ["Daniela Cortes-Toto", "Heriberto Espino"]
    assert front["year"] == 2011
    assert front["keywords"][0] == "Trend estimation"
    assert "trend-estimation" in front["tags"]
    assert front["aliases"] == ["Estimacion de tendencia"]
    assert front["pdf"] == (
        "[[CortesToto_Espino-2011-Estimacion_de_tendencia.pdf]]"
    )
    assert "literature-note" in front["cssclasses"]
    assert "trend-estimation" in front["topics"]


def test_related_papers_use_shared_topic_tags(tmp_path: Path):
    extracted = tmp_path / "extracted"
    extracted.mkdir()

    papers = {
        "A.md": """---
title: A
tags:
  - literature
  - time-series
  - trend-estimation
---
# A
""",
        "B.md": """---
title: B
tags:
  - literature
  - time-series
  - bayesian
---
# B
""",
        "C.md": """---
title: C
tags:
  - literature
  - computer-vision
---
# C
""",
    }
    for name, text in papers.items():
        (extracted / name).write_text(text, encoding="utf-8")

    changed = update_related_papers(extracted)
    assert changed == 2

    front_a = _front((extracted / "A.md").read_text(encoding="utf-8"))
    front_b = _front((extracted / "B.md").read_text(encoding="utf-8"))
    front_c = _front((extracted / "C.md").read_text(encoding="utf-8"))

    assert front_a["related"] == ["[[B]]"]
    assert front_b["related"] == ["[[A]]"]
    assert "related" not in front_c


def test_obsidian_vault_sync_copies_notes_and_pdfs(tmp_path: Path):
    bib = tmp_path / "project" / "bib"
    (bib / "pdf").mkdir(parents=True)
    (bib / "extracted").mkdir()
    stem = "CortesToto_Espino-2011-Estimacion_de_tendencia"

    (bib / "pdf" / f"{stem}.pdf").write_bytes(b"pdf")
    note = enrich_markdown_text(
        SAMPLE,
        paper_id=stem,
        pdf_name=f"{stem}.pdf",
        metadata=infer_paper_metadata(SAMPLE),
        obsidian=True,
    )
    (bib / "extracted" / f"{stem}.md").write_text(note, encoding="utf-8")
    (bib / "INDEX.md").write_text("# Index", encoding="utf-8")
    (bib / "bundle.md").write_text("# Bundle", encoding="utf-8")

    vault = tmp_path / "vault"
    notes, pdfs = sync_obsidian_vault(bib_dir=bib, vault_dir=vault)

    assert (notes, pdfs) == (1, 1)
    copied_note = vault / "Literature" / f"{stem}.md"
    copied_pdf = vault / "Literature" / "Attachments" / "PDFs" / f"{stem}.pdf"
    assert copied_note.exists()
    assert copied_pdf.exists()
    assert (vault / "Literature" / "_Index.md").exists()
    assert (vault / "Literature" / "_Bundle.md").exists()

    front = _front(copied_note.read_text(encoding="utf-8"))
    assert front["pdf"] == f"[[Attachments/PDFs/{stem}.pdf]]"
    assert front["source_pdf"] == f"Attachments/PDFs/{stem}.pdf"


def test_reference_markdown_inherits_parent_metadata():
    metadata = infer_paper_metadata(SAMPLE)
    refs = """---
id: old-references
source_pdf: ../pdf/old.pdf
---
# References

Reference A.
"""

    enriched = enrich_reference_markdown_text(
        refs,
        paper_id="CortesToto_Espino-2011-Estimacion_de_tendencia",
        pdf_name="CortesToto_Espino-2011-Estimacion_de_tendencia.pdf",
        paper_metadata=metadata,
        obsidian=True,
    )
    front = _front(enriched)

    assert front["content"] == "references-only"
    assert front["paper_title"] == "Estimacion de tendencia"
    assert front["authors"] == ["Daniela Cortes-Toto", "Heriberto Espino"]
    assert front["year"] == 2011
    assert front["paper"] == "[[CortesToto_Espino-2011-Estimacion_de_tendencia]]"
    assert front["pdf"] == "[[CortesToto_Espino-2011-Estimacion_de_tendencia.pdf]]"
    assert "references" in front["tags"]
    assert "Reference A." in enriched
