#!/usr/bin/env python3
"""
Convierte una biblioteca de artículos PDF a Markdown estructurado con Docling.

Diseñado para el repositorio CMAT/CMAT2 y para recuperación "repo-native"
por ChatGPT Codex mediante búsquedas de texto (`rg`, `grep`, búsqueda del IDE, etc.).

Pipeline por defecto
--------------------
PDF born-digital
    -> Docling
    -> detección de layout
    -> reconstrucción precisa de tablas
    -> Markdown limpio
    -> INDEX.md

Por defecto NO se ejecutan:
    - OCR
    - formula enrichment
    - generación de imágenes de página
    - extracción de figuras rasterizadas
    - JSON de Docling

Esto reduce tiempo, VRAM y almacenamiento para un corpus compuesto
principalmente por papers académicos born-digital.

Ejemplos
--------
Procesamiento normal:

    python scripts/extract_bibliography.py

Forzar reprocesamiento:

    python scripts/extract_bibliography.py --force

Usar explícitamente CUDA:

    python scripts/extract_bibliography.py --device cuda

Activar reconocimiento LaTeX de fórmulas:

    python scripts/extract_bibliography.py --formulas

Activar OCR para PDFs escaneados:

    python scripts/extract_bibliography.py --ocr

Guardar además el DoclingDocument como JSON:

    python scripts/extract_bibliography.py --json

Procesar un directorio específico:

    python scripts/extract_bibliography.py \
        --input Bib/pdf \
        --output Bib/extracted

Dependencias
------------
    pip install -U docling

En un entorno CUDA funcional, Docling puede utilizar la GPU mediante
AcceleratorDevice.AUTO o AcceleratorDevice.CUDA.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from docling.datamodel.accelerator_options import (
    AcceleratorDevice,
    AcceleratorOptions,
)
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import (
    DocumentConverter,
    PdfFormatOption,
)
from docling_core.types.doc import ImageRefMode


# ============================================================
# Configuration
# ============================================================

DEFAULT_THREADS = 8

# Para este corpus es mejor conservar las tablas con precisión.
DEFAULT_TABLE_MODE = TableFormerMode.ACCURATE

# Extensión canónica de salida.
MARKDOWN_SUFFIX = ".md"

# Máximo de encabezados mostrados por paper en INDEX.md.
MAX_INDEX_HEADINGS = 10


# ============================================================
# Data structures
# ============================================================


@dataclass
class ConversionStats:
    total: int = 0
    converted: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed_seconds: float = 0.0


# ============================================================
# Path resolution
# ============================================================


def discover_default_paths() -> tuple[Path, Path]:
    """
    Detecta automáticamente las rutas del corpus CMAT.

    Casos soportados:

        repo/
            Bib/
                pdf/

        Bib/
            pdf/

        pdf/

    Si no puede deducirlas desde cwd, utiliza la ruta canónica de CMAT2
    dentro del home del usuario.
    """

    cwd = Path.cwd().resolve()

    # Ejecutado directamente desde Bib/pdf/
    if cwd.name.lower() == "pdf":
        input_dir = cwd
        output_dir = cwd.parent / "extracted"
        return input_dir, output_dir

    # Ejecutado desde la raíz del repositorio.
    if (cwd / "Bib" / "pdf").is_dir():
        input_dir = cwd / "Bib" / "pdf"
        output_dir = cwd / "Bib" / "extracted"
        return input_dir, output_dir

    # Ejecutado desde Bib/.
    if (cwd / "pdf").is_dir():
        input_dir = cwd / "pdf"
        output_dir = cwd / "extracted"
        return input_dir, output_dir

    # Fallback correspondiente a tu estructura WSL2.
    repo = Path.home() / "projects" / "docling"

    input_dir = repo / "Bib" / "pdf"
    output_dir = repo / "Bib" / "extracted"

    return input_dir, output_dir


# ============================================================
# CLI
# ============================================================


def parse_args() -> argparse.Namespace:
    default_input, default_output = discover_default_paths()

    parser = argparse.ArgumentParser(
        description=(
            "Convierte una biblioteca PDF a Markdown estructurado "
            "con Docling para recuperación eficiente desde Codex."
        )
    )

    parser.add_argument(
        "--input",
        type=Path,
        default=default_input,
        help=f"Directorio de PDFs. Default: {default_input}",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=default_output,
        help=f"Directorio de salida. Default: {default_output}",
    )

    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu", "mps"),
        default="auto",
        help=(
            "Acelerador para Docling. "
            "'auto' selecciona automáticamente el hardware disponible."
        ),
    )

    parser.add_argument(
        "--threads",
        type=int,
        default=DEFAULT_THREADS,
        help=f"Número de threads CPU. Default: {DEFAULT_THREADS}",
    )

    parser.add_argument(
        "--ocr",
        action="store_true",
        help=(
            "Activa OCR. No recomendado para los papers born-digital "
            "del corpus CMAT salvo que algún PDF sea escaneado."
        ),
    )

    parser.add_argument(
        "--formulas",
        action="store_true",
        help=(
            "Activa formula enrichment para obtener representaciones "
            "LaTeX de ecuaciones. Es más costoso."
        ),
    )

    parser.add_argument(
        "--json",
        action="store_true",
        dest="save_json",
        help=(
            "Guarda además el DoclingDocument como JSON. "
            "No es necesario para la recuperación repo-native."
        ),
    )

    parser.add_argument(
        "--figures",
        action="store_true",
        help=(
            "Genera imágenes de figuras. No se generan imágenes "
            "de página completas."
        ),
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Reprocesa PDFs aunque el Markdown existente esté actualizado.",
    )

    parser.add_argument(
        "--recursive",
        action="store_true",
        help="Busca PDFs recursivamente dentro del directorio de entrada.",
    )

    parser.add_argument(
        "--no-index",
        action="store_true",
        help="No genera Bib/INDEX.md.",
    )

    return parser.parse_args()


# ============================================================
# Docling configuration
# ============================================================


def resolve_accelerator(device_name: str) -> AcceleratorDevice:
    mapping = {
        "auto": AcceleratorDevice.AUTO,
        "cuda": AcceleratorDevice.CUDA,
        "cpu": AcceleratorDevice.CPU,
        "mps": AcceleratorDevice.MPS,
    }

    return mapping[device_name]


def build_converter(
    *,
    device: AcceleratorDevice,
    num_threads: int,
    enable_ocr: bool,
    enable_formulas: bool,
    generate_figures: bool,
) -> DocumentConverter:
    """
    Construye una única instancia de DocumentConverter reutilizable.

    Mantener el mismo converter para toda la cohorte evita reinicializar
    los modelos de Docling para cada PDF.
    """

    accelerator_options = AcceleratorOptions(
        num_threads=num_threads,
        device=device,
    )

    pipeline_options = PdfPipelineOptions()

    # --------------------------------------------------------
    # Hardware
    # --------------------------------------------------------

    pipeline_options.accelerator_options = accelerator_options

    # --------------------------------------------------------
    # OCR
    # --------------------------------------------------------

    # Los papers actuales del corpus CMAT son primordialmente
    # PDFs born-digital, de manera que el OCR añade costo sin
    # proporcionar normalmente nueva información.
    pipeline_options.do_ocr = enable_ocr

    # --------------------------------------------------------
    # Tables
    # --------------------------------------------------------

    # Este componente sí es importante para papers empíricos:
    # odds ratios, regresiones, descriptivos, sample sizes, etc.
    pipeline_options.do_table_structure = True

    pipeline_options.table_structure_options = TableStructureOptions(
        do_cell_matching=True
    )

    pipeline_options.table_structure_options.mode = DEFAULT_TABLE_MODE

    # --------------------------------------------------------
    # Formula enrichment
    # --------------------------------------------------------

    # Desactivado por defecto porque la mayor parte del corpus
    # pertenece a higher education / educational research.
    pipeline_options.do_formula_enrichment = enable_formulas

    # --------------------------------------------------------
    # Images
    # --------------------------------------------------------

    # Nunca necesitamos imágenes completas de página para el
    # flujo normal de Codex.
    pipeline_options.generate_page_images = False

    # Opcional para papers donde las figuras sean informativamente
    # importantes.
    pipeline_options.generate_picture_images = generate_figures

    if generate_figures:
        pipeline_options.images_scale = 2.0

    # --------------------------------------------------------
    # Converter
    # --------------------------------------------------------

    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=pipeline_options
            )
        },
    )


# ============================================================
# File discovery
# ============================================================


def discover_pdfs(
    input_dir: Path,
    recursive: bool = False,
) -> list[Path]:
    if recursive:
        files = input_dir.rglob("*.pdf")
    else:
        files = input_dir.glob("*.pdf")

    return sorted(
        (p for p in files if p.is_file()),
        key=lambda p: p.name.lower(),
    )


def markdown_path_for(
    pdf_path: Path,
    input_dir: Path,
    output_dir: Path,
    recursive: bool,
) -> Path:
    """
    Si se procesa recursivamente, conserva la estructura relativa.
    """

    if recursive:
        relative = pdf_path.relative_to(input_dir)
        return (output_dir / relative).with_suffix(MARKDOWN_SUFFIX)

    return output_dir / f"{pdf_path.stem}{MARKDOWN_SUFFIX}"


def json_path_for(md_path: Path) -> Path:
    return md_path.with_suffix(".json")


# ============================================================
# Incremental processing
# ============================================================


def needs_processing(
    pdf_path: Path,
    md_path: Path,
    force: bool,
) -> bool:
    """
    Reprocesa si:
        - --force;
        - no existe el Markdown;
        - el PDF es más reciente que el Markdown.
    """

    if force:
        return True

    if not md_path.exists():
        return True

    try:
        return pdf_path.stat().st_mtime > md_path.stat().st_mtime
    except OSError:
        return True


# ============================================================
# Markdown metadata
# ============================================================


def yaml_escape(value: str) -> str:
    """
    Escapado mínimo y seguro para valores YAML como strings.
    """

    value = value.replace("\\", "\\\\")
    value = value.replace('"', '\\"')
    value = value.replace("\n", " ")

    return f'"{value}"'


def build_front_matter(
    *,
    pdf_path: Path,
    md_path: Path,
) -> str:
    """
    Añade metadata extremadamente barata que Codex puede buscar
    mediante rg sin necesidad de cargar el documento completo.

    No intentamos inferir aquí autores, método o temática:
    sería preferible mantener esa metadata en un índice curado
    si posteriormente quieres clasificación semántica.
    """

    doc_id = pdf_path.stem

    relative_pdf = Path("..") / "pdf" / pdf_path.name

    return (
        "---\n"
        f"id: {yaml_escape(doc_id)}\n"
        f"source_pdf: {yaml_escape(relative_pdf.as_posix())}\n"
        f"source_filename: {yaml_escape(pdf_path.name)}\n"
        "format: \"academic-paper\"\n"
        "---\n\n"
    )


def remove_existing_front_matter(markdown: str) -> str:
    """
    Previene duplicación si por alguna razón se reutiliza un Markdown
    previamente generado.
    """

    if not markdown.startswith("---\n"):
        return markdown

    end = markdown.find("\n---\n", 4)

    if end == -1:
        return markdown

    return markdown[end + len("\n---\n") :].lstrip()


# ============================================================
# Markdown cleanup
# ============================================================


def normalize_markdown(text: str) -> str:
    """
    Limpieza conservadora.

    No modifica contenido académico ni intenta corregir la extracción;
    solamente normaliza espacios y saltos de línea para que los archivos
    sean más fáciles de buscar y comparar en Git.
    """

    text = text.replace("\r\n", "\n")
    text = text.replace("\r", "\n")

    # Elimina espacios al final de línea.
    text = "\n".join(line.rstrip() for line in text.splitlines())

    # Evita cantidades excesivas de líneas vacías.
    text = re.sub(r"\n{4,}", "\n\n\n", text)

    return text.strip() + "\n"


# ============================================================
# Conversion
# ============================================================


def convert_pdf(
    *,
    converter: DocumentConverter,
    pdf_path: Path,
    md_path: Path,
    save_json: bool,
    generate_figures: bool,
) -> None:
    """
    Convierte un PDF individual y escribe sus artefactos.
    """

    md_path.parent.mkdir(parents=True, exist_ok=True)

    # --------------------------------------------------------
    # Convert PDF locally with Docling
    # --------------------------------------------------------

    result = converter.convert(pdf_path)
    document = result.document

    # --------------------------------------------------------
    # Markdown
    # --------------------------------------------------------

    if generate_figures:
        # save_as_markdown() sí acepta artifacts_dir.
        artifacts_dir = (
            md_path.parent
            / f"{md_path.stem}_artifacts"
        )

        artifacts_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        document.save_as_markdown(
            md_path,
            artifacts_dir=artifacts_dir,
            image_mode=ImageRefMode.REFERENCED,
            compact_tables=True,
        )

        markdown_body = md_path.read_text(
            encoding="utf-8",
            errors="replace",
        )

    else:
        # Para nuestro caso normal:
        #
        # PDF -> Markdown textual
        #
        # No necesitamos generar ningún artifact de imágenes.
        markdown_body = document.export_to_markdown(
            image_mode=ImageRefMode.PLACEHOLDER,
            compact_tables=True,
        )

    # --------------------------------------------------------
    # Normalize Markdown
    # --------------------------------------------------------

    markdown_body = remove_existing_front_matter(
        markdown_body
    )

    markdown_body = normalize_markdown(
        markdown_body
    )

    # --------------------------------------------------------
    # Add searchable metadata for Codex
    # --------------------------------------------------------

    front_matter = build_front_matter(
        pdf_path=pdf_path,
        md_path=md_path,
    )

    md_path.write_text(
        front_matter + markdown_body,
        encoding="utf-8",
    )

    # --------------------------------------------------------
    # Optional structured JSON
    # --------------------------------------------------------

    if save_json:
        json_path = json_path_for(md_path)

        document.save_as_json(
            json_path,
            image_mode=ImageRefMode.PLACEHOLDER,
            ensure_ascii=False,
            sort_keys=True,
        )

# ============================================================
# INDEX.md generation
# ============================================================


HEADING_PATTERN = re.compile(
    r"^(#{1,3})\s+(.+?)\s*$",
    flags=re.MULTILINE,
)


def extract_headings(
    markdown: str,
    limit: int = MAX_INDEX_HEADINGS,
) -> list[tuple[int, str]]:
    """
    Extrae encabezados H1-H3 para ofrecer a Codex una descripción
    barata de la estructura del documento.
    """

    headings: list[tuple[int, str]] = []

    # Ignorar front matter.
    body = remove_existing_front_matter(markdown)

    for match in HEADING_PATTERN.finditer(body):
        level = len(match.group(1))
        title = match.group(2).strip()

        if not title:
            continue

        headings.append((level, title))

        if len(headings) >= limit:
            break

    return headings


def infer_display_title(
    markdown: str,
    fallback_stem: str,
) -> str:
    """
    Utiliza el primer H1 como título cuando Docling lo detecta.
    En caso contrario transforma el nombre normalizado del PDF
    en un título legible.
    """

    headings = extract_headings(markdown, limit=3)

    for level, title in headings:
        if level == 1:
            return title

    fallback = fallback_stem.replace("_", " ").replace("-", " ")
    fallback = re.sub(r"\s+", " ", fallback).strip()

    return fallback


def sanitize_index_text(text: str) -> str:
    """
    Evita que caracteres peculiares rompan líneas del índice.
    """

    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def generate_index(
    output_dir: Path,
    *,
    recursive: bool,
) -> Path:
    """
    Genera un índice compacto para que un agente pueda decidir qué
    papers necesita abrir antes de gastar contexto leyendo contenido.
    """

    md_files = sorted(
        (
            p
            for p in output_dir.rglob("*.md")
            if p.name.upper() != "INDEX.MD"
        ),
        key=lambda p: p.name.lower(),
    )

    index_path = output_dir.parent / "INDEX.md"

    lines: list[str] = [
        "# CMAT literature corpus",
        "",
        (
            "Índice generado automáticamente a partir de los artículos "
            "convertidos con Docling. Los PDFs originales están en "
            "`Bib/pdf/` y las representaciones textuales en `Bib/extracted/`."
        ),
        "",
        "## Papers",
        "",
    ]

    for md_path in md_files:
        try:
            markdown = md_path.read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            continue

        title = infer_display_title(
            markdown,
            fallback_stem=md_path.stem,
        )

        title = sanitize_index_text(title)

        relative_md = md_path.relative_to(output_dir.parent)
        relative_pdf = Path("pdf") / f"{md_path.stem}.pdf"

        headings = extract_headings(markdown)

        lines.append(f"### {title}")
        lines.append("")

        lines.append(
            f"- Markdown: `{relative_md.as_posix()}`"
        )

        # Sólo añadimos la ruta PDF esperada si estamos en la estructura
        # estándar. No pasa nada si un corpus recursivo utiliza otra.
        if not recursive:
            lines.append(
                f"- PDF: `{relative_pdf.as_posix()}`"
            )

        if headings:
            lines.append("- Sections:")

            # Omitimos el H1 si coincide aproximadamente con el título.
            shown = 0

            for level, heading in headings:
                heading = sanitize_index_text(heading)

                if level == 1 and heading == title:
                    continue

                indent = "  "

                lines.append(
                    f"{indent}- {heading}"
                )

                shown += 1

                if shown >= MAX_INDEX_HEADINGS:
                    break

        lines.append("")

    index_path.write_text(
        "\n".join(lines).rstrip() + "\n",
        encoding="utf-8",
    )

    return index_path


# ============================================================
# Reporting
# ============================================================


def human_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes = seconds / 60

    if minutes < 60:
        return f"{minutes:.2f} min"

    hours = minutes / 60
    return f"{hours:.2f} h"


def print_header(
    *,
    input_dir: Path,
    output_dir: Path,
    pdf_count: int,
    args: argparse.Namespace,
) -> None:
    print("=" * 76)
    print(" CMAT — PDF → MARKDOWN CORPUS")
    print("=" * 76)
    print(f"PDFs             : {pdf_count}")
    print(f"Origen           : {input_dir}")
    print(f"Destino          : {output_dir}")
    print(f"Device           : {args.device}")
    print(f"Threads          : {args.threads}")
    print(f"OCR              : {args.ocr}")
    print(f"Formula enrich.  : {args.formulas}")
    print(f"TableFormer      : ACCURATE")
    print(f"Figuras          : {args.figures}")
    print(f"JSON             : {args.save_json}")
    print(f"Force            : {args.force}")
    print("=" * 76)
    print()


def print_summary(stats: ConversionStats) -> None:
    print()
    print("=" * 76)
    print(" RESUMEN")
    print("=" * 76)

    print(f"PDFs detectados  : {stats.total}")
    print(f"Convertidos      : {stats.converted}")
    print(f"Omitidos         : {stats.skipped}")
    print(f"Fallidos         : {stats.failed}")
    print(
        f"Tiempo total     : "
        f"{human_duration(stats.elapsed_seconds)}"
    )

    if stats.converted:
        mean = stats.elapsed_seconds / stats.converted
        print(
            f"Promedio aprox.  : "
            f"{human_duration(mean)} / PDF convertido"
        )

    print("=" * 76)


# ============================================================
# Main pipeline
# ============================================================


def process_corpus(args: argparse.Namespace) -> int:
    input_dir = args.input.expanduser().resolve()
    output_dir = args.output.expanduser().resolve()

    if not input_dir.exists():
        print(
            f"[ERROR] No existe el directorio de entrada:\n"
            f"        {input_dir}",
            file=sys.stderr,
        )
        return 1

    if not input_dir.is_dir():
        print(
            f"[ERROR] La entrada no es un directorio:\n"
            f"        {input_dir}",
            file=sys.stderr,
        )
        return 1

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    pdf_files = discover_pdfs(
        input_dir,
        recursive=args.recursive,
    )

    if not pdf_files:
        print(
            f"[ERROR] No se encontraron PDFs en:\n"
            f"        {input_dir}",
            file=sys.stderr,
        )
        return 1

    print_header(
        input_dir=input_dir,
        output_dir=output_dir,
        pdf_count=len(pdf_files),
        args=args,
    )

    # Inicializamos Docling sólo una vez.
    converter = build_converter(
        device=resolve_accelerator(args.device),
        num_threads=args.threads,
        enable_ocr=args.ocr,
        enable_formulas=args.formulas,
        generate_figures=args.figures,
    )

    stats = ConversionStats(
        total=len(pdf_files)
    )

    total_start = time.perf_counter()

    for index, pdf_path in enumerate(pdf_files, start=1):
        md_path = markdown_path_for(
            pdf_path,
            input_dir=input_dir,
            output_dir=output_dir,
            recursive=args.recursive,
        )

        prefix = (
            f"[{index:02d}/{len(pdf_files):02d}]"
        )

        if not needs_processing(
            pdf_path,
            md_path,
            force=args.force,
        ):
            print(
                f"{prefix} [SKIP] "
                f"{pdf_path.name}"
            )

            stats.skipped += 1
            continue

        print(
            f"{prefix} [....] "
            f"{pdf_path.name}"
        )

        file_start = time.perf_counter()

        try:
            convert_pdf(
                converter=converter,
                pdf_path=pdf_path,
                md_path=md_path,
                save_json=args.save_json,
                generate_figures=args.figures,
            )

            elapsed = (
                time.perf_counter()
                - file_start
            )

            stats.converted += 1

            print(
                f"{prefix} [ OK ] "
                f"{human_duration(elapsed):>10}  "
                f"→ {md_path.name}"
            )

        except KeyboardInterrupt:
            print(
                "\n[INTERRUPTED] Procesamiento cancelado "
                "por el usuario.",
                file=sys.stderr,
            )
            return 130

        except Exception as exc:
            elapsed = (
                time.perf_counter()
                - file_start
            )

            stats.failed += 1

            print(
                f"{prefix} [FAIL] "
                f"{human_duration(elapsed):>10}  "
                f"{pdf_path.name}",
                file=sys.stderr,
            )

            print(
                f"       {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    stats.elapsed_seconds = (
        time.perf_counter()
        - total_start
    )

    # --------------------------------------------------------
    # Generate repo-native corpus index
    # --------------------------------------------------------

    if not args.no_index:
        try:
            index_path = generate_index(
                output_dir,
                recursive=args.recursive,
            )

            print()
            print(
                f"[INDEX] {index_path}"
            )

        except Exception as exc:
            print(
                f"[WARN] No se pudo generar INDEX.md: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )

    print_summary(stats)

    # Código distinto de cero si hubo algún fallo.
    return 2 if stats.failed else 0


def main() -> int:
    args = parse_args()

    if args.threads < 1:
        print(
            "[ERROR] --threads debe ser >= 1",
            file=sys.stderr,
        )
        return 1

    return process_corpus(args)


if __name__ == "__main__":
    raise SystemExit(main())