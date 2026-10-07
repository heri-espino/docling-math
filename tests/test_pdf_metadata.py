from pathlib import Path

from pypdf import PdfReader, PdfWriter

from docling_math.metadata import PaperMetadata
from docling_math.pdf_metadata import write_pdf_metadata


def test_write_pdf_info_and_xmp(tmp_path: Path):
    pdf = tmp_path / "paper.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=300, height=300)
    writer.write(pdf)

    metadata = PaperMetadata(
        title="Estimacion de tendencia",
        authors=("Daniela Cortes-Toto", "Heriberto Espino"),
        year=2011,
        journal="Journal of Trend Research",
        doi="10.1234/example",
        abstract="A sufficiently descriptive abstract for XMP metadata.",
        keywords=("Trend estimation", "Time series"),
        tags=("literature", "year/2011", "trend-estimation"),
        aliases=("Estimacion de tendencia",),
    )

    assert write_pdf_metadata(pdf, metadata) is True

    reader = PdfReader(pdf)
    info = reader.metadata
    assert info is not None
    assert info.title == "Estimacion de tendencia"
    assert info.author == "Daniela Cortes-Toto; Heriberto Espino"
    assert "Trend estimation" in (info.get("/Keywords") or "")
    assert "trend-estimation" in (info.get("/Keywords") or "")
    assert info.get("/DOI") == "10.1234/example"
    assert info.get("/Journal") == "Journal of Trend Research"
    assert info.get("/PublicationYear") == "2011"

    xmp = reader.xmp_metadata
    assert xmp is not None
    assert xmp.dc_title["x-default"] == "Estimacion de tendencia"
    assert xmp.dc_creator == ["Daniela Cortes-Toto", "Heriberto Espino"]
    assert "Trend estimation" in xmp.dc_subject
    assert "trend-estimation" in xmp.dc_subject
    assert xmp.dc_identifier == "10.1234/example"
