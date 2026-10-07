"""Write bibliographic metadata into PDF Info and XMP metadata."""

from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.xmp import XmpInformation

from .metadata import PaperMetadata


def _keyword_values(metadata: PaperMetadata) -> list[str]:
    """Combine original article keywords with normalized library tags."""
    values: list[str] = []
    seen: set[str] = set()
    for value in (*metadata.keywords, *metadata.tags):
        clean = str(value).strip()
        key = clean.casefold()
        if not clean or key in seen:
            continue
        seen.add(key)
        values.append(clean)
    return values


def write_pdf_metadata(
    pdf_path: Path,
    metadata: PaperMetadata,
) -> bool:
    """Update PDF Info + XMP atomically while preserving pages and existing metadata."""
    if not pdf_path.exists():
        raise FileNotFoundError(pdf_path)

    if not any(
        (
            metadata.title,
            metadata.authors,
            metadata.year,
            metadata.journal,
            metadata.doi,
            metadata.keywords,
            metadata.tags,
        )
    ):
        return False

    writer = PdfWriter(clone_from=str(pdf_path))

    info: dict[str, str] = {}
    if metadata.title:
        info["/Title"] = metadata.title
    if metadata.authors:
        info["/Author"] = "; ".join(metadata.authors)

    keywords = _keyword_values(metadata)
    if keywords:
        info["/Keywords"] = ", ".join(keywords)
        subject_values = list(metadata.keywords) or keywords
        info["/Subject"] = "; ".join(subject_values)

    if metadata.doi:
        info["/DOI"] = metadata.doi
    if metadata.journal:
        info["/Journal"] = metadata.journal
    if metadata.year is not None:
        info["/PublicationYear"] = str(metadata.year)

    info["/Creator"] = "docling-math"
    if info:
        writer.add_metadata(info)

    xmp = writer.xmp_metadata or XmpInformation.create()
    if metadata.title:
        titles = dict(xmp.dc_title or {})
        titles["x-default"] = metadata.title
        xmp.dc_title = titles
    if metadata.authors:
        xmp.dc_creator = list(metadata.authors)
    if keywords:
        xmp.dc_subject = keywords
        xmp.pdf_keywords = ", ".join(keywords)
    if metadata.doi:
        xmp.dc_identifier = metadata.doi
    if metadata.abstract:
        descriptions = dict(xmp.dc_description or {})
        descriptions["x-default"] = metadata.abstract
        xmp.dc_description = descriptions
    if metadata.journal:
        xmp.dc_source = metadata.journal
    xmp.xmp_creator_tool = "docling-math"
    writer.xmp_metadata = xmp

    temp = pdf_path.with_name(f".{pdf_path.name}.metadata.tmp.pdf")
    try:
        with temp.open("wb") as handle:
            writer.write(handle)
        temp.replace(pdf_path)
    finally:
        if temp.exists():
            temp.unlink()

    return True
