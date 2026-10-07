"""Canonical academic filename inference backed by PaperMetadata."""

from __future__ import annotations

from dataclasses import dataclass

from .metadata import (
    PaperMetadata,
    canonical_stem,
    infer_paper_metadata,
    title_slug,
)


@dataclass(frozen=True)
class PaperIdentity:
    """Metadata sufficient for the canonical academic filename."""

    authors: tuple[str, ...]
    year: int
    title: str
    stem: str


def infer_paper_identity(markdown: str) -> PaperIdentity | None:
    """Infer Author1_Author2-Year-Title from extracted academic Markdown."""
    metadata = infer_paper_metadata(markdown)
    stem = canonical_stem(metadata)
    if stem is None or metadata.title is None or metadata.year is None:
        return None

    author_part = stem.split("-", 1)[0]
    surnames = tuple(author_part.split("_"))
    return PaperIdentity(
        authors=surnames,
        year=metadata.year,
        title=metadata.title,
        stem=stem,
    )


__all__ = [
    "PaperIdentity",
    "PaperMetadata",
    "canonical_stem",
    "infer_paper_identity",
    "infer_paper_metadata",
    "title_slug",
]
