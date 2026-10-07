"""High-fidelity academic PDF extraction built on Docling.

Default profile
---------------
- text-first Markdown
- CodeFormulaV2 formula enrichment
- TableFormer ACCURATE table reconstruction
- compact page provenance markers
- no persisted image assets unless --assets is requested

The original PDFs remain the source of truth.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import os
import re
import shutil
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from docling.datamodel.accelerator_options import (
    AcceleratorDevice,
    AcceleratorOptions,
)
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    CodeFormulaVlmOptions,
    HeadingHierarchyOptions,
    LayoutObjectDetectionOptions,
    NativePdfPipelineOptions,
    OcrMode,
    PdfPipelineOptions,
    RapidOcrOptions,
    TableFormerMode,
    TableStructureOptions,
)
from docling.document_converter import (
    DocumentConverter,
    NativePdfFormatOption,
    PdfFormatOption,
)
from docling_core.types.doc import ImageRefMode, PictureItem, TableItem

from .markdown_metadata import enrich_markdown_file, enrich_markdown_text, update_related_papers
from .metadata import PaperMetadata, infer_paper_metadata
from .naming import infer_paper_identity
from .obsidian_vault import sync_obsidian_vault
from .pdf_metadata import write_pdf_metadata


# =============================================================================
# Defaults
# =============================================================================

DEFAULT_THREADS = 8
DEFAULT_IMAGE_SCALE = 3.0
DEFAULT_LAYOUT_PRESET = "layout_egret_large"
DEFAULT_OCR_BACKEND = "torch"
DEFAULT_OCR_LANG = "en"
DEFAULT_STRATEGY = "compare"
DEFAULT_MODEL_CACHE = Path.home() / ".cache" / "docling" / "models"
MAX_INDEX_HEADINGS = 10

# Figure filtering is intentionally conservative: false positives are cheaper than
# deleting an informative scientific figure.
DEFAULT_MIN_FIGURE_AREA = 0.004       # 0.4% of a page
DEFAULT_SMALL_MARGIN_AREA = 0.025     # 2.5% of a page
DEFAULT_FIRST_PAGE_SMALL_AREA = 0.06  # 6% of a page

# A late section matching one of these headings is moved to bib/references/.
REFERENCE_HEADINGS = {
    "references",
    "bibliography",
    "works cited",
    "literature cited",
    "referencias",
}

# Single-line boilerplate patterns that are safe to discard for scholarly retrieval.
# This is intentionally much more conservative than a generic "clean PDF" routine.
BOILERPLATE_LINE_PATTERNS = [
    re.compile(r"^please scroll down for article\s*$", re.I),
    re.compile(r"^view related articles\s*$", re.I),
    re.compile(r"^view crossmark data\s*$", re.I),
    re.compile(r"^submit your article to this journal\s*$", re.I),
    re.compile(r"^full terms\s*&\s*conditions of access and use can be found at\s*$", re.I),
    re.compile(r"^this article was downloaded by:\s*.*$", re.I),
    re.compile(r"^downloaded by\s*\[.*\]\s*.*$", re.I),
]

# Common corruption / mojibake signals.
MOJIBAKE_MARKERS = (
    "Ã",
    "Â",
    "â€",
    "â€™",
    "â€œ",
    "â€˜",
    "ðŸ",
    "�",
)

# Strongly non-informative picture labels. Classification strings are normalized
# and matched by substring to remain compatible with classifier naming changes.
PICTURE_REJECT_KEYWORDS = {
    "logo",
    "signature",
    "barcode",
    "qr",
    "icon",
    "decorative",
    "decoration",
}

# Strongly informative picture labels.
PICTURE_KEEP_KEYWORDS = {
    "chart",
    "plot",
    "graph",
    "diagram",
    "flow",
    "map",
    "scientific",
}


# =============================================================================
# Data classes
# =============================================================================

@dataclass
class TextDiagnostics:
    chars: int
    chars_per_page: float
    words: int
    alpha_words: int
    control_ratio: float
    c1_ratio: float
    replacement_count: int
    mojibake_count: int
    formula_not_decoded: int
    single_char_token_ratio: float
    alphabetic_ratio: float
    common_word_ratio: float
    score: float
    grade: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class Candidate:
    mode: str
    result: Any
    markdown: str
    diagnostics: TextDiagnostics
    confidence_mean: str | None
    confidence_low: str | None
    combined_score: float
    seconds: float


@dataclass
class AssetStats:
    tables: int = 0
    pictures_seen: int = 0
    figures_kept: int = 0
    figures_dropped: int = 0
    duplicate_figures_dropped: int = 0


# =============================================================================
# CLI and paths
# =============================================================================


def discover_repo_root() -> Path:
    """Find the nearest project containing bib/pdf (case-insensitive Bib)."""
    cwd = Path.cwd().resolve()
    candidates = [cwd, *cwd.parents]
    for candidate in candidates:
        for bib_name in ("bib", "Bib"):
            if (candidate / bib_name / "pdf").is_dir():
                return candidate
    raise FileNotFoundError(
        "No pude localizar bib/pdf. Ejecuta docling-math dentro del proyecto "
        "o usa --repo /ruta/al/proyecto."
    )


def resolve_bib_dir(repo: Path) -> Path:
    for name in ("bib", "Bib"):
        candidate = repo / name
        if candidate.is_dir():
            return candidate
    return repo / "bib"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="docling-math",
        description=(
            "Extrae papers PDF a Markdown de alta fidelidad. "
            "Por defecto prioriza texto, matemáticas y tablas, sin guardar imágenes."
        ),
    )
    parser.add_argument("--repo", type=Path, default=None, help="Raíz del proyecto.")
    parser.add_argument(
        "--paper",
        type=str,
        default=None,
        help="Procesa sólo un PDF; acepta filename, stem o substring único.",
    )
    parser.add_argument(
        "--strategy",
        choices=("compare", "smart", "hybrid", "ocr"),
        default=DEFAULT_STRATEGY,
        help=(
            "compare: compara hybrid y full-page OCR; smart: OCR sólo si hace falta; "
            "hybrid: no fuerza OCR; ocr: full-page OCR."
        ),
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu", "mps"),
        default="auto",
        help="auto prioriza CUDA, luego MPS; CPU requiere confirmación interactiva.",
    )
    parser.add_argument("--threads", type=int, default=DEFAULT_THREADS)
    parser.add_argument(
        "--math",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Activa/desactiva CodeFormulaV2. Default: activado.",
    )
    parser.add_argument(
        "--tables",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Activa/desactiva TableFormer ACCURATE. Default: activado.",
    )
    parser.add_argument(
        "--assets",
        action="store_true",
        help="Guarda crops PNG de tablas y figuras informativas. Default: no.",
    )
    parser.add_argument(
        "--ocr-backend",
        choices=("torch", "onnxruntime", "openvino", "paddle"),
        default=DEFAULT_OCR_BACKEND,
    )
    parser.add_argument("--ocr-lang", default=DEFAULT_OCR_LANG)
    parser.add_argument("--layout-preset", default=DEFAULT_LAYOUT_PRESET)
    parser.add_argument("--image-scale", type=float, default=DEFAULT_IMAGE_SCALE)
    parser.add_argument("--min-figure-area", type=float, default=DEFAULT_MIN_FIGURE_AREA)
    parser.add_argument("--keep-all-figures", action="store_true")
    parser.add_argument("--no-reference-split", action="store_true")
    parser.add_argument("--no-index", action="store_true")
    parser.add_argument("--no-agents", action="store_true")
    parser.add_argument(
        "--rename-pdfs",
        action="store_true",
        help=(
            "Renombra PDFs y outputs como Author1_Author2-Year-Title_of_article. "
            "Sólo renombra cuando puede inferir autores, año y título."
        ),
    )
    parser.add_argument(
        "--metadata",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Añade metadata bibliográfica, keywords, tags y aliases al YAML. Default: sí.",
    )
    parser.add_argument(
        "--refresh-metadata",
        action="store_true",
        help="Actualiza metadata de Markdown ya extraídos sin volver a ejecutar OCR.",
    )
    parser.add_argument(
        "--write-pdf-metadata",
        action="store_true",
        help="Escribe Title/Author/Keywords y XMP dentro del PDF. Modifica el PDF fuente.",
    )
    parser.add_argument(
        "--obsidian",
        action="store_true",
        help="Añade propiedades Obsidian, wikilink al PDF y relaciones entre papers.",
    )
    parser.add_argument(
        "--related-papers",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Con --obsidian, genera hasta 5 enlaces related por tags compartidos.",
    )
    parser.add_argument(
        "--obsidian-vault",
        type=Path,
        default=None,
        help="Sincroniza una copia Obsidian-ready al vault indicado.",
    )
    parser.add_argument(
        "--no-bundle",
        action="store_true",
        help="No genera bib/bundle.md al terminar. Default: sí lo genera.",
    )
    parser.add_argument(
        "--bundle-references",
        action="store_true",
        help="Incluye bibliografías separadas dentro de bundle.md. Default: no.",
    )
    parser.add_argument(
        "--artifacts-path",
        type=Path,
        default=None,
        help="Cache persistente de pesos. Default: ~/.cache/docling/models.",
    )
    parser.add_argument(
        "--refresh-models",
        action="store_true",
        help="Fuerza revalidación/descarga de los pesos del cache.",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args()


def resolve_artifacts_path(explicit: Path | None) -> Path:
    """Return the persistent Docling model cache used across projects and runs."""
    if explicit is not None:
        path = explicit.expanduser().resolve()
    elif os.environ.get("DOCLING_ARTIFACTS_PATH"):
        path = Path(os.environ["DOCLING_ARTIFACTS_PATH"]).expanduser().resolve()
    else:
        path = DEFAULT_MODEL_CACHE

    path.mkdir(parents=True, exist_ok=True)
    return path


def _installed_docling_version() -> str:
    try:
        from importlib.metadata import version
        return version("docling")
    except Exception:
        return "unknown"


def ensure_model_cache(
    *,
    artifacts_path: Path,
    layout_preset: str,
    refresh: bool = False,
) -> None:
    """Prefetch Docling weights once and reuse the same local artifacts afterwards."""
    docling_version = _installed_docling_version()
    safe_version = re.sub(r"[^A-Za-z0-9_.-]+", "-", docling_version)
    core_marker = artifacts_path / f".docling-math-core-{safe_version}.ready"

    if refresh or not core_marker.exists():
        print(f"[MODELS] preparing persistent cache: {artifacts_path}")
        from docling.utils.model_downloader import download_models

        download_models(
            output_dir=artifacts_path,
            force=refresh,
            progress=True,
            with_layout=False,
        )
        core_marker.write_text(
            f"docling={docling_version}\n",
            encoding="utf-8",
        )
    else:
        print(f"[MODELS] reusing persistent cache: {artifacts_path}")

    layout_options = LayoutObjectDetectionOptions.from_preset(layout_preset)
    model_spec = getattr(layout_options, "model_spec", None)
    repo_id = getattr(model_spec, "repo_id", None)
    revision = getattr(model_spec, "revision", None)
    if not repo_id:
        return

    marker_name = re.sub(
        r"[^A-Za-z0-9_.-]+",
        "-",
        f".docling-math-layout-{repo_id}-{revision or 'default'}.ready",
    )
    layout_marker = artifacts_path / marker_name
    if refresh or not layout_marker.exists():
        print(f"[MODELS] caching layout preset {layout_preset}: {repo_id}")
        from docling.models.utils.hf_model_download import download_hf_model

        download_hf_model(
            repo_id=repo_id,
            revision=revision,
            local_dir=artifacts_path / repo_id.replace("/", "--"),
            force=refresh,
            progress=True,
        )
        layout_marker.write_text(
            f"preset={layout_preset}\nrepo_id={repo_id}\nrevision={revision or ''}\n",
            encoding="utf-8",
        )


def _available_accelerators() -> tuple[bool, bool, str]:
    try:
        import torch
    except Exception as exc:
        return False, False, f"PyTorch no se pudo importar: {exc}"

    cuda = bool(torch.cuda.is_available())
    mps_backend = getattr(torch.backends, "mps", None)
    mps = bool(mps_backend and mps_backend.is_available())
    details = "PyTorch detectó CPU únicamente."

    if cuda:
        try:
            details = f"CUDA: {torch.cuda.get_device_name(0)}"
        except Exception:
            details = "CUDA disponible"
    elif mps:
        details = "Apple MPS disponible"

    return cuda, mps, details


def _confirm_cpu(reason: str) -> None:
    print(f"[WARNING] No se usará GPU: {reason}", file=sys.stderr)
    if not sys.stdin.isatty():
        raise RuntimeError(
            "El fallback a CPU requiere confirmación interactiva. "
            "Ejecuta el comando en una terminal."
        )

    answer = input(
        "¿Continuar con CPU? Esto puede ser mucho más lento. [y/N]: "
    ).strip().casefold()

    if answer not in {"y", "yes"}:
        raise RuntimeError("Ejecución cancelada antes de usar CPU.")


def resolve_device(name: str) -> AcceleratorDevice:
    """Resolve a device with a strict GPU-first policy."""
    cuda, mps, details = _available_accelerators()

    if name == "auto":
        if cuda:
            print(f"[DEVICE] {details}")
            return AcceleratorDevice.CUDA
        if mps:
            print(f"[DEVICE] {details}")
            return AcceleratorDevice.MPS
        _confirm_cpu(details)
        return AcceleratorDevice.CPU

    if name == "cuda":
        if cuda:
            print(f"[DEVICE] {details}")
            return AcceleratorDevice.CUDA
        _confirm_cpu("se solicitó CUDA, pero torch.cuda.is_available() == False")
        return AcceleratorDevice.CPU

    if name == "mps":
        if mps:
            print(f"[DEVICE] {details}")
            return AcceleratorDevice.MPS
        _confirm_cpu("se solicitó MPS, pero no está disponible")
        return AcceleratorDevice.CPU

    _confirm_cpu("se solicitó --device cpu explícitamente")
    return AcceleratorDevice.CPU


def discover_pdfs(pdf_dir: Path, query: str | None) -> list[Path]:
    files = sorted(pdf_dir.glob("*.pdf"), key=lambda p: p.name.casefold())
    if query is None:
        return files
    needle = query.casefold()
    matches = [p for p in files if needle in p.name.casefold() or needle in p.stem.casefold()]
    if not matches:
        raise FileNotFoundError(f"No encontré un PDF que coincida con: {query}")
    if len(matches) > 1:
        listing = "\n".join(f"  - {p.name}" for p in matches)
        raise RuntimeError(f"La búsqueda coincide con varios PDFs:\n{listing}")
    return matches


def needs_processing(pdf_path: Path, md_path: Path, force: bool) -> bool:
    if force or not md_path.exists():
        return True
    try:
        return pdf_path.stat().st_mtime > md_path.stat().st_mtime
    except OSError:
        return True


# =============================================================================
# Canonical PDF / corpus renaming
# =============================================================================


def _rewrite_front_matter_names(
    path: Path,
    *,
    old_pdf_name: str,
    new_pdf_name: str,
    old_stem: str,
    new_stem: str,
) -> None:
    """Update only YAML front matter paths/IDs after moving an extracted file."""
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---\n"):
        return

    end = text.find("\n---\n", 4)
    if end == -1:
        return

    front = text[: end + len("\n---\n")]
    body = text[end + len("\n---\n") :]
    front = front.replace(old_pdf_name, new_pdf_name)
    front = front.replace(old_stem, new_stem)
    write_atomic(path, front + body)


def _replace_index_paths(
    index_path: Path,
    *,
    old_pdf_name: str,
    new_pdf_name: str,
    old_stem: str,
    new_stem: str,
) -> None:
    if not index_path.exists():
        return

    text = index_path.read_text(encoding="utf-8", errors="replace")
    replacements = {
        f"pdf/{old_pdf_name}": f"pdf/{new_pdf_name}",
        f"extracted/{old_stem}.md": f"extracted/{new_stem}.md",
        f"references/{old_stem}.references.md": f"references/{new_stem}.references.md",
        f"assets/{old_stem}/": f"assets/{new_stem}/",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    write_atomic(index_path, text)


def rename_corpus_entry(
    *,
    pdf_path: Path,
    md_path: Path,
    refs_dir: Path,
    assets_root: Path,
    index_path: Path,
    markdown_for_identity: str,
) -> tuple[Path, Path, bool]:
    """Rename one paper and any already-existing companion outputs atomically enough to retry."""
    identity = infer_paper_identity(markdown_for_identity)
    if identity is None:
        print(
            f"  [RENAME-SKIP] {pdf_path.name}: no pude inferir autores + año + título"
        )
        return pdf_path, md_path, False

    old_stem = pdf_path.stem
    new_stem = identity.stem
    if old_stem == new_stem:
        return pdf_path, md_path, False

    new_pdf = pdf_path.with_name(f"{new_stem}.pdf")
    new_md = md_path.with_name(f"{new_stem}.md")
    old_refs = refs_dir / f"{old_stem}.references.md"
    new_refs = refs_dir / f"{new_stem}.references.md"
    old_assets = assets_root / old_stem
    new_assets = assets_root / new_stem

    moves = [
        (pdf_path, new_pdf),
        (md_path, new_md),
        (old_refs, new_refs),
        (old_assets, new_assets),
    ]

    collisions = [
        dst
        for src, dst in moves
        if src != dst and dst.exists()
    ]
    if collisions:
        names = ", ".join(str(path) for path in collisions)
        print(
            f"  [RENAME-SKIP] {pdf_path.name}: destino ya existe ({names})",
            file=sys.stderr,
        )
        return pdf_path, md_path, False

    # The source PDF must move. Companion files/directories move only when present.
    pdf_path.rename(new_pdf)
    for src, dst in moves[1:]:
        if src.exists() and src != dst:
            src.rename(dst)

    _rewrite_front_matter_names(
        new_md,
        old_pdf_name=pdf_path.name,
        new_pdf_name=new_pdf.name,
        old_stem=old_stem,
        new_stem=new_stem,
    )
    _rewrite_front_matter_names(
        new_refs,
        old_pdf_name=pdf_path.name,
        new_pdf_name=new_pdf.name,
        old_stem=old_stem,
        new_stem=new_stem,
    )
    _replace_index_paths(
        index_path,
        old_pdf_name=pdf_path.name,
        new_pdf_name=new_pdf.name,
        old_stem=old_stem,
        new_stem=new_stem,
    )

    print(
        f"  [RENAME] {pdf_path.name} -> {new_pdf.name} "
        f"(authors={','.join(identity.authors)}; year={identity.year})"
    )
    return new_pdf, new_md, True


# =============================================================================
# GPU / memory cleanup
# =============================================================================


def cleanup_memory() -> None:
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


# =============================================================================
# Docling pipeline construction
# =============================================================================


def build_native_converter() -> DocumentConverter:
    """Cheap native parser used only for diagnostics, never for final output."""
    options = NativePdfPipelineOptions()
    options.generate_page_images = False
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: NativePdfFormatOption(pipeline_options=options),
        },
    )


def build_fidelity_converter(
    *,
    device: AcceleratorDevice,
    threads: int,
    full_page_ocr: bool,
    ocr_backend: str,
    ocr_lang: str,
    layout_preset: str,
    image_scale: float,
    math_enrichment: bool,
    table_enrichment: bool,
    assets_enabled: bool,
    artifacts_path: Path,
) -> DocumentConverter:
    """Build the high-fidelity Docling PDF pipeline."""
    accelerator = AcceleratorOptions(num_threads=threads, device=device)

    ocr_kwargs: dict[str, Any] = {
        "backend": ocr_backend,
        "lang": [ocr_lang],
    }
    if full_page_ocr:
        ocr_kwargs["mode"] = OcrMode.FULL_PAGE
    ocr_options = RapidOcrOptions(**ocr_kwargs)

    pipeline = PdfPipelineOptions(
        do_ocr=True,
        ocr_options=ocr_options,
        do_table_structure=table_enrichment,
        table_structure_options=TableStructureOptions(
            mode=TableFormerMode.ACCURATE,
            do_cell_matching=True,
        ),
    )
    pipeline.accelerator_options = accelerator
    pipeline.artifacts_path = artifacts_path
    pipeline.layout_options = LayoutObjectDetectionOptions.from_preset(layout_preset)
    pipeline.heading_hierarchy_options = HeadingHierarchyOptions(enabled=True)
    pipeline.generate_parsed_pages = True

    pipeline.do_formula_enrichment = math_enrichment
    pipeline.do_code_enrichment = math_enrichment
    if math_enrichment:
        pipeline.code_formula_options = CodeFormulaVlmOptions.from_preset("codeformulav2")

    # Page renders stay in memory because they improve layout/table analysis.
    # They are never persisted unless --assets is requested.
    pipeline.generate_page_images = True
    pipeline.generate_picture_images = assets_enabled
    pipeline.images_scale = image_scale
    pipeline.do_picture_classification = assets_enabled

    return DocumentConverter(
        allowed_formats=[InputFormat.PDF],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline),
        },
    )

# =============================================================================
# Markdown serialization and cleaning
# =============================================================================


def normalize_unicode(text: str) -> str:
    # Converts Unicode ligatures such as ﬁ/ﬂ to fi/fl, among other compatibility forms.
    return unicodedata.normalize("NFKC", text)


def remove_known_boilerplate_lines(text: str) -> str:
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(pattern.match(stripped) for pattern in BOILERPLATE_LINE_PATTERNS):
            continue
        out.append(line)
    return "\n".join(out)


def remove_generic_picture_placeholders(text: str) -> str:
    # Visual evidence lives under bib/assets. Generic placeholders only waste retrieval tokens.
    text = re.sub(r"(?im)^\s*<!--\s*image\s*-->\s*$", "", text)
    text = re.sub(r"(?im)^\s*<!--\s*picture\s*-->\s*$", "", text)
    return text


def remove_consecutive_duplicate_lines(text: str) -> str:
    out: list[str] = []
    previous_nonempty: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped and previous_nonempty == stripped:
            continue
        out.append(line)
        if stripped:
            previous_nonempty = stripped
    return "\n".join(out)


def normalize_markdown(text: str) -> str:
    text = normalize_unicode(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = remove_known_boilerplate_lines(text)
    text = remove_generic_picture_placeholders(text)
    text = remove_consecutive_duplicate_lines(text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text.strip() + "\n"


def serialize_candidate_markdown(document: Any, *, full_page_ocr: bool) -> str:
    """
    Serialize to a text-first Markdown representation for scoring and final cleanup.
    traverse_pictures=True is required for full-page OCR scans in current Docling.
    """
    raw = document.export_to_markdown(
        image_mode=ImageRefMode.PLACEHOLDER,
        compact_tables=False,
        traverse_pictures=full_page_ocr,
        page_break_placeholder="\n\n<!-- PAGE_BREAK -->\n\n",
        enable_chart_tables=True,
        include_picture_classification=False,
    )
    return normalize_markdown(raw)


def number_page_breaks(markdown: str) -> str:
    """Turn generic page breaks into compact page provenance markers."""
    counter = 1

    def repl(_: re.Match[str]) -> str:
        nonlocal counter
        counter += 1
        return f"<!-- p:{counter} -->"

    markdown = re.sub(r"<!--\s*PAGE_BREAK\s*-->", repl, markdown)
    return "<!-- p:1 -->\n\n" + markdown.lstrip()


# =============================================================================
# Quality diagnostics and candidate selection
# =============================================================================


def _confidence_grade_to_bonus(value: str | None) -> float:
    if not value:
        return 0.0
    lower = value.casefold()
    if "excellent" in lower:
        return 4.0
    if "good" in lower:
        return 2.0
    if "fair" in lower:
        return -2.0
    if "poor" in lower:
        return -6.0
    return 0.0


def extract_confidence_grades(result: Any) -> tuple[str | None, str | None]:
    conf = getattr(result, "confidence", None)
    if conf is None:
        return None, None
    mean_grade = getattr(conf, "mean_grade", None)
    low_grade = getattr(conf, "low_grade", None)
    return (
        str(mean_grade) if mean_grade is not None else None,
        str(low_grade) if low_grade is not None else None,
    )


def diagnose_text(markdown: str, pages: int, language: str = "en") -> TextDiagnostics:
    text = markdown
    chars = len(text)
    pages = max(pages, 1)
    chars_per_page = chars / pages

    nonspace_chars = [c for c in text if not c.isspace()]
    denom = max(len(nonspace_chars), 1)

    control = 0
    c1 = 0
    alphabetic = 0
    for ch in nonspace_chars:
        if ch.isalpha():
            alphabetic += 1
        code = ord(ch)
        if 0x80 <= code <= 0x9F:
            c1 += 1
        category = unicodedata.category(ch)
        if category in {"Cc", "Cs"}:
            control += 1

    control_ratio = control / denom
    c1_ratio = c1 / denom
    alphabetic_ratio = alphabetic / denom

    replacement_count = text.count("�")
    mojibake_count = sum(text.count(marker) for marker in MOJIBAKE_MARKERS)
    formula_not_decoded = len(
        re.findall(r"formula[-_ ]?not[-_ ]?decoded", text, flags=re.I)
    )

    tokens = re.findall(r"\S+", text)
    words = len(tokens)
    alpha_word_list = re.findall(r"\b[A-Za-z]{2,}\b", text)
    alpha_words = len(alpha_word_list)
    single_char = sum(1 for t in tokens if len(re.sub(r"\W", "", t)) == 1)

    common_word_ratio = 0.0
    if language.casefold().startswith("en") and alpha_words:
        common_words = {
            "the", "of", "and", "to", "in", "a", "is", "for", "that", "with",
            "as", "on", "by", "are", "this", "we", "be", "from", "or", "an",
            "was", "were", "which", "at", "it", "these", "their", "has", "have",
        }
        common_count = sum(1 for word in alpha_word_list if word.casefold() in common_words)
        common_word_ratio = common_count / alpha_words
    single_char_token_ratio = single_char / max(words, 1)

    score = 100.0
    reasons: list[str] = []

    if chars_per_page < 150:
        score -= 45
        reasons.append(f"very little text ({chars_per_page:.0f} chars/page)")
    elif chars_per_page < 350:
        score -= 25
        reasons.append(f"little text ({chars_per_page:.0f} chars/page)")
    elif chars_per_page < 600:
        score -= 8
        reasons.append(f"somewhat sparse text ({chars_per_page:.0f} chars/page)")

    if control_ratio > 0.0005:
        penalty = min(35.0, control_ratio * 5000)
        score -= penalty
        reasons.append(f"control chars ratio={control_ratio:.5f}")

    if c1_ratio > 0.0005:
        penalty = min(35.0, c1_ratio * 5000)
        score -= penalty
        reasons.append(f"C1/mojibake ratio={c1_ratio:.5f}")

    if replacement_count:
        score -= min(20.0, 1.5 * replacement_count)
        reasons.append(f"replacement chars={replacement_count}")

    if mojibake_count:
        score -= min(25.0, 0.8 * mojibake_count)
        reasons.append(f"mojibake signals={mojibake_count}")

    if formula_not_decoded:
        score -= min(20.0, 4.0 * formula_not_decoded)
        reasons.append(f"formula-not-decoded={formula_not_decoded}")

    if single_char_token_ratio > 0.25:
        score -= 18
        reasons.append(f"fragmented-token ratio={single_char_token_ratio:.2f}")
    elif single_char_token_ratio > 0.15:
        score -= 8
        reasons.append(f"fragmented-token ratio={single_char_token_ratio:.2f}")

    # Extremely low alphabetic content is suspicious for ordinary academic papers,
    # but the threshold is intentionally low to avoid punishing mathematics-heavy work.
    if alphabetic_ratio < 0.20 and chars > 500:
        score -= 15
        reasons.append(f"low alphabetic ratio={alphabetic_ratio:.2f}")

    # English function words are a useful corruption signal when a PDF maps glyphs to
    # technically valid but semantically wrong Unicode characters. This catches cases
    # that do not contain replacement/C1 bytes. It is disabled for non-English OCR.
    if language.casefold().startswith("en") and alpha_words >= 100:
        if common_word_ratio < 0.025:
            score -= 24
            reasons.append(f"very low English-function-word ratio={common_word_ratio:.3f}")
        elif common_word_ratio < 0.055:
            score -= 10
            reasons.append(f"low English-function-word ratio={common_word_ratio:.3f}")

    score = max(0.0, min(100.0, score))
    if score >= 92:
        grade = "excellent"
    elif score >= 82:
        grade = "good"
    elif score >= 68:
        grade = "fair"
    else:
        grade = "poor"

    return TextDiagnostics(
        chars=chars,
        chars_per_page=chars_per_page,
        words=words,
        alpha_words=alpha_words,
        control_ratio=control_ratio,
        c1_ratio=c1_ratio,
        replacement_count=replacement_count,
        mojibake_count=mojibake_count,
        formula_not_decoded=formula_not_decoded,
        single_char_token_ratio=single_char_token_ratio,
        alphabetic_ratio=alphabetic_ratio,
        common_word_ratio=common_word_ratio,
        score=score,
        grade=grade,
        reasons=reasons,
    )


def candidate_combined_score(
    diagnostics: TextDiagnostics,
    confidence_mean: str | None,
    confidence_low: str | None,
) -> float:
    # Text diagnostics dominate because they directly reflect what the downstream agent reads.
    score = diagnostics.score
    score += _confidence_grade_to_bonus(confidence_mean)
    score += _confidence_grade_to_bonus(confidence_low)
    return score


def smart_needs_ocr(candidate: Candidate) -> bool:
    if candidate.diagnostics.score < 88:
        return True
    if candidate.diagnostics.formula_not_decoded:
        return True
    low = (candidate.confidence_low or "").casefold()
    if "poor" in low or "fair" in low:
        return True
    if candidate.diagnostics.control_ratio > 0.0005:
        return True
    if candidate.diagnostics.c1_ratio > 0.0005:
        return True
    return False


def convert_candidate(
    *,
    pdf_path: Path,
    mode: str,
    device: AcceleratorDevice,
    threads: int,
    ocr_backend: str,
    ocr_lang: str,
    layout_preset: str,
    image_scale: float,
    math_enrichment: bool,
    table_enrichment: bool,
    assets_enabled: bool,
    artifacts_path: Path,
) -> Candidate:
    full_page_ocr = mode == "full-page-ocr"
    converter = build_fidelity_converter(
        device=device,
        threads=threads,
        full_page_ocr=full_page_ocr,
        ocr_backend=ocr_backend,
        ocr_lang=ocr_lang,
        layout_preset=layout_preset,
        image_scale=image_scale,
        math_enrichment=math_enrichment,
        table_enrichment=table_enrichment,
        assets_enabled=assets_enabled,
        artifacts_path=artifacts_path,
    )

    start = time.perf_counter()
    result = converter.convert(pdf_path)
    seconds = time.perf_counter() - start

    markdown = serialize_candidate_markdown(
        result.document,
        full_page_ocr=full_page_ocr,
    )
    pages = len(result.document.pages)
    diagnostics = diagnose_text(markdown, pages, language=ocr_lang)
    mean_grade, low_grade = extract_confidence_grades(result)
    combined = candidate_combined_score(diagnostics, mean_grade, low_grade)

    del converter
    cleanup_memory()

    return Candidate(
        mode=mode,
        result=result,
        markdown=markdown,
        diagnostics=diagnostics,
        confidence_mean=mean_grade,
        confidence_low=low_grade,
        combined_score=combined,
        seconds=seconds,
    )

def choose_candidate(candidates: list[Candidate]) -> Candidate:
    if len(candidates) == 1:
        return candidates[0]

    # Prefer the higher combined quality. A tiny tie goes to hybrid because native text
    # is usually more exact than OCR when both are genuinely equivalent.
    candidates_sorted = sorted(
        candidates,
        key=lambda c: (c.combined_score, c.mode != "full-page-ocr"),
        reverse=True,
    )
    return candidates_sorted[0]


# =============================================================================
# Reference-section separation
# =============================================================================


HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", flags=re.MULTILINE)


def normalized_heading_title(title: str) -> str:
    title = re.sub(r"[*_`]+", "", title)
    title = re.sub(r"\s+", " ", title).strip().casefold()
    title = re.sub(r"[.:;]+$", "", title)
    return title


def split_reference_section(markdown: str) -> tuple[str, str | None]:
    """
    Move a late References/Bibliography section out of the main retrieval Markdown.
    The split ends at the next heading of the same or higher level, preserving appendices.
    """
    matches = list(HEADING_LINE_RE.finditer(markdown))
    if not matches:
        return markdown, None

    chosen_index: int | None = None
    for i, match in enumerate(matches):
        title = normalized_heading_title(match.group(2))
        # Require a relatively late position to avoid a table of contents or literature-review heading.
        if title in REFERENCE_HEADINGS and match.start() >= int(len(markdown) * 0.35):
            chosen_index = i
            break

    if chosen_index is None:
        return markdown, None

    ref_match = matches[chosen_index]
    ref_level = len(ref_match.group(1))
    start = ref_match.start()
    end = len(markdown)

    for later in matches[chosen_index + 1 :]:
        later_level = len(later.group(1))
        if later_level <= ref_level:
            end = later.start()
            break

    references = markdown[start:end].strip() + "\n"
    main = (markdown[:start].rstrip() + "\n\n" + markdown[end:].lstrip()).strip() + "\n"

    # Do not split implausibly tiny reference sections.
    if len(references) < 300:
        return markdown, None

    return main, references


# =============================================================================
# Picture / table provenance and filtering
# =============================================================================


def item_page_no(item: Any) -> int | None:
    try:
        if item.prov:
            return int(item.prov[0].page_no)
    except Exception:
        return None
    return None


def item_caption(item: Any, document: Any) -> str:
    try:
        text = item.caption_text(document)
        return normalize_unicode(text or "").strip()
    except Exception:
        return ""


def has_real_figure_caption(item: Any, document: Any) -> bool:
    caption = item_caption(item, document)
    if not caption:
        return False
    return bool(
        re.search(
            r"^(?:fig(?:ure)?\.?\s*)[A-Za-z]?\d+\b",
            caption,
            flags=re.I,
        )
    )


def picture_classification(item: Any) -> tuple[str | None, float | None]:
    """Compatible with current meta.classification and older annotation storage."""
    candidates: list[tuple[str, float]] = []

    try:
        meta = getattr(item, "meta", None)
        classification = getattr(meta, "classification", None) if meta is not None else None
        predictions = getattr(classification, "predictions", None) if classification is not None else None
        if predictions:
            for pred in predictions:
                name = getattr(pred, "class_name", None)
                confidence = getattr(pred, "confidence", None)
                if name is not None and confidence is not None:
                    candidates.append((str(name), float(confidence)))
    except Exception:
        pass

    # Fallback for older/current annotation APIs.
    try:
        for annotation in item.get_annotations():
            predictions = getattr(annotation, "predicted_classes", None)
            if not predictions:
                continue
            for pred in predictions:
                name = getattr(pred, "class_name", None)
                confidence = getattr(pred, "confidence", None)
                if name is not None and confidence is not None:
                    candidates.append((str(name), float(confidence)))
    except Exception:
        pass

    if not candidates:
        return None, None
    return max(candidates, key=lambda pair: pair[1])


def normalized_geometry(item: Any, document: Any) -> dict[str, float] | None:
    try:
        if not item.prov:
            return None
        prov = item.prov[0]
        page = document.pages[prov.page_no]
        bbox = prov.bbox.to_top_left_origin(page_height=page.size.height)
        bbox = bbox.normalized(page.size)
        x0, x1 = sorted((float(bbox.l), float(bbox.r)))
        y0, y1 = sorted((float(bbox.t), float(bbox.b)))
        width = max(0.0, x1 - x0)
        height = max(0.0, y1 - y0)
        return {
            "x0": x0,
            "y0": y0,
            "x1": x1,
            "y1": y1,
            "width": width,
            "height": height,
            "area": width * height,
        }
    except Exception:
        return None


def image_dhash(image: Any, hash_size: int = 12) -> str:
    """Small perceptual hash used only to drop repeated uncaptioned logos/decorations."""
    try:
        img = image.convert("L").resize((hash_size + 1, hash_size))
        pixels = list(img.getdata())
        bits: list[str] = []
        row_width = hash_size + 1
        for y in range(hash_size):
            start = y * row_width
            row = pixels[start : start + row_width]
            for x in range(hash_size):
                bits.append("1" if row[x] > row[x + 1] else "0")
        value = int("".join(bits), 2)
        return f"{value:0{(hash_size * hash_size + 3) // 4}x}"
    except Exception:
        # Fallback to exact bytes if PIL operations fail.
        try:
            return hashlib.sha256(image.tobytes()).hexdigest()
        except Exception:
            return ""


def should_keep_picture(
    *,
    item: Any,
    document: Any,
    min_area: float,
    keep_all: bool,
) -> tuple[bool, str]:
    if keep_all:
        return True, "keep-all"

    # Caption is the strongest scientific-signal and overrides every heuristic.
    if has_real_figure_caption(item, document):
        return True, "figure-caption"

    class_name, confidence = picture_classification(item)
    normalized_class = (class_name or "").casefold()

    if confidence is not None and confidence >= 0.50:
        if any(keyword in normalized_class for keyword in PICTURE_REJECT_KEYWORDS):
            return False, f"class={class_name}:{confidence:.2f}"
        if any(keyword in normalized_class for keyword in PICTURE_KEEP_KEYWORDS):
            return True, f"class={class_name}:{confidence:.2f}"

    geometry = normalized_geometry(item, document)
    if geometry is None:
        # Missing geometry is uncertainty, not evidence of irrelevance.
        return True, "no-geometry"

    area = geometry["area"]
    width = geometry["width"]
    height = geometry["height"]
    x0, y0, x1, y1 = (
        geometry["x0"],
        geometry["y0"],
        geometry["x1"],
        geometry["y1"],
    )

    if area < min_area:
        return False, f"tiny-area={area:.4f}"
    if width < 0.035 or height < 0.02:
        return False, f"tiny-dimension={width:.3f}x{height:.3f}"

    near_edge = y0 < 0.07 or y1 > 0.93 or x0 < 0.035 or x1 > 0.965
    if near_edge and area < DEFAULT_SMALL_MARGIN_AREA:
        return False, f"small-margin-object={area:.4f}"

    page_no = item_page_no(item)
    if page_no == 1 and area < DEFAULT_FIRST_PAGE_SMALL_AREA:
        return False, f"small-first-page-object={area:.4f}"

    return True, "conservative-keep"


def safe_image_save(image: Any, output: Path) -> bool:
    if image is None:
        return False
    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, "PNG")
    return True


def export_assets(
    *,
    document: Any,
    assets_dir: Path,
    min_figure_area: float,
    keep_all_figures: bool,
) -> AssetStats:
    if assets_dir.exists():
        shutil.rmtree(assets_dir)
    tables_dir = assets_dir / "tables"
    figures_dir = assets_dir / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    stats = AssetStats()
    seen_picture_hashes: set[str] = set()

    table_counter = 0
    picture_counter = 0
    kept_counter = 0

    for item, _level in document.iterate_items():
        if isinstance(item, TableItem):
            table_counter += 1
            stats.tables += 1
            page_no = item_page_no(item)
            page_part = f"p{page_no:03d}" if page_no is not None else "pUNK"
            output = tables_dir / f"table-{table_counter:03d}-{page_part}.png"
            try:
                image = item.get_image(document)
                if not safe_image_save(image, output):
                    print(f"    [WARN] table {table_counter}: no image available")
            except Exception as exc:
                print(f"    [WARN] table {table_counter}: {exc}")

        elif isinstance(item, PictureItem):
            picture_counter += 1
            stats.pictures_seen += 1
            keep, reason = should_keep_picture(
                item=item,
                document=document,
                min_area=min_figure_area,
                keep_all=keep_all_figures,
            )
            page_no = item_page_no(item)
            page_part = f"p{page_no:03d}" if page_no is not None else "pUNK"

            if not keep:
                stats.figures_dropped += 1
                print(f"    [DROP] picture-{picture_counter:03d}-{page_part}: {reason}")
                continue

            try:
                image = item.get_image(document)
            except Exception as exc:
                stats.figures_dropped += 1
                print(f"    [WARN] picture {picture_counter}: {exc}")
                continue

            if image is None:
                stats.figures_dropped += 1
                print(f"    [DROP] picture-{picture_counter:03d}-{page_part}: no-image")
                continue

            # Duplicate-image filtering is applied only to uncaptioned pictures. An actual
            # Figure N caption always wins, even if a similar image appeared earlier.
            if not has_real_figure_caption(item, document):
                digest = image_dhash(image)
                if digest and digest in seen_picture_hashes:
                    stats.figures_dropped += 1
                    stats.duplicate_figures_dropped += 1
                    print(f"    [DROP] picture-{picture_counter:03d}-{page_part}: duplicate")
                    continue
                if digest:
                    seen_picture_hashes.add(digest)

            kept_counter += 1
            stats.figures_kept += 1
            class_name, confidence = picture_classification(item)
            class_suffix = ""
            if class_name:
                clean_class = re.sub(r"[^A-Za-z0-9_-]+", "-", class_name.strip()).strip("-")
                if clean_class:
                    class_suffix = f"-{clean_class[:30]}"
            output = figures_dir / f"figure-{kept_counter:03d}-{page_part}{class_suffix}.png"
            safe_image_save(image, output)
            conf_text = f" {confidence:.2f}" if confidence is not None else ""
            cls_text = f" [{class_name}{conf_text}]" if class_name else ""
            print(f"    [KEEP] {output.name}{cls_text}: {reason}")

    # Remove empty directories so the repo remains tidy.
    for directory in (tables_dir, figures_dir):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
        except Exception:
            pass
    try:
        if assets_dir.exists() and not any(assets_dir.iterdir()):
            assets_dir.rmdir()
    except Exception:
        pass

    return stats


# =============================================================================
# Final Markdown, front matter, references
# =============================================================================


def yaml_quote(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def build_front_matter(
    *,
    pdf_path: Path,
    winner: Candidate,
    assets_dir: Path,
    refs_path: Path | None,
    asset_stats: AssetStats,
    assets_enabled: bool,
) -> str:
    lines = [
        "---",
        f"id: {yaml_quote(pdf_path.stem)}",
        f"source_pdf: {yaml_quote('../pdf/' + pdf_path.name)}",
        f"source_filename: {yaml_quote(pdf_path.name)}",
        'format: "academic-paper"',
        'extraction_profile: "text-math-tables-high-fidelity"',
        f"extraction_mode: {yaml_quote(winner.mode)}",
        f"extraction_quality: {yaml_quote(winner.diagnostics.grade)}",
        f"extraction_score: {winner.combined_score:.1f}",
    ]

    if assets_enabled:
        lines.extend(
            [
                'visual_assets: "enabled"',
                f"tables_png: {asset_stats.tables}",
                f"figures_png: {asset_stats.figures_kept}",
                f"assets_dir: {yaml_quote('../assets/' + pdf_path.stem)}",
            ]
        )
    else:
        lines.append('visual_assets: "disabled"')

    if refs_path is not None:
        lines.append(f"references_file: {yaml_quote('../references/' + refs_path.name)}")

    lines.extend(["---", ""])
    return "\n".join(lines) + "\n"

def write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def finalize_markdown(
    *,
    pdf_path: Path,
    winner: Candidate,
    md_path: Path,
    refs_dir: Path,
    assets_dir: Path,
    asset_stats: AssetStats,
    split_references: bool,
    assets_enabled: bool,
    paper_metadata: PaperMetadata,
    metadata_enabled: bool,
    obsidian: bool,
) -> Path | None:
    body = number_page_breaks(winner.markdown)

    refs_text: str | None = None
    if split_references:
        body, refs_text = split_reference_section(body)

    refs_path: Path | None = None
    if refs_text:
        refs_path = refs_dir / f"{pdf_path.stem}.references.md"
        refs_front = (
            "---\n"
            f"id: {yaml_quote(pdf_path.stem + '-references')}\n"
            f"source_pdf: {yaml_quote('../pdf/' + pdf_path.name)}\n"
            'content: "references-only"\n'
            "---\n\n"
        )
        write_atomic(refs_path, refs_front + refs_text)
    else:
        stale = refs_dir / f"{pdf_path.stem}.references.md"
        if stale.exists():
            stale.unlink()

    front = build_front_matter(
        pdf_path=pdf_path,
        winner=winner,
        assets_dir=assets_dir,
        refs_path=refs_path,
        asset_stats=asset_stats,
        assets_enabled=assets_enabled,
    )
    final_text = front + body
    if metadata_enabled or obsidian:
        final_text = enrich_markdown_text(
            final_text,
            paper_id=pdf_path.stem,
            pdf_name=pdf_path.name,
            metadata=paper_metadata,
            obsidian=obsidian,
        )
    write_atomic(md_path, final_text)
    return refs_path


# =============================================================================
# INDEX.md
# =============================================================================


INDEX_BLOCK_RE = re.compile(r"(?ms)^### [^\n]+\n.*?(?=^### |\Z)")


def strip_front_matter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return markdown
    return markdown[end + len("\n---\n") :].lstrip()


def clean_heading_for_index(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&")
    text = re.sub(r"[*_`]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_index_headings(md_path: Path, limit: int = MAX_INDEX_HEADINGS) -> list[str]:
    markdown = strip_front_matter(md_path.read_text(encoding="utf-8", errors="replace"))
    headings: list[str] = []
    seen: set[str] = set()
    for match in HEADING_LINE_RE.finditer(markdown):
        heading = clean_heading_for_index(match.group(2))
        if not heading:
            continue
        key = heading.casefold()
        if key in seen:
            continue
        seen.add(key)
        headings.append(heading)
        if len(headings) >= limit:
            break
    return headings


def derive_title(md_path: Path, stem: str) -> str:
    headings = extract_index_headings(md_path, limit=4)
    if headings:
        return headings[0]
    return re.sub(r"[-_]+", " ", stem).strip()


def preserved_curated_index_lines(old_block: str) -> list[str]:
    """Preserve manually curated metadata if it already exists."""
    wanted_prefixes = (
        "- topics:",
        "- methods:",
        "- relevance:",
        "- notes:",
        "- design:",
        "- population:",
    )
    preserved: list[str] = []
    for line in old_block.splitlines():
        if line.strip().casefold().startswith(wanted_prefixes):
            preserved.append(line.rstrip())
    return preserved


def build_index_block(
    *,
    pdf_path: Path,
    md_path: Path,
    refs_path: Path | None,
    winner: Candidate,
    stats: AssetStats,
    assets_enabled: bool,
    preserved_lines: Iterable[str] = (),
) -> str:
    title = derive_title(md_path, pdf_path.stem)
    headings = extract_index_headings(md_path)
    metadata = infer_paper_metadata(
        md_path.read_text(encoding="utf-8", errors="replace")
    )

    lines = [
        f"### {title}",
        "",
        f"- Markdown: `extracted/{md_path.name}`",
        f"- PDF: `pdf/{pdf_path.name}`",
        f"- Extraction: `{winner.mode}`",
        f"- Quality: `{winner.diagnostics.grade}` ({winner.combined_score:.1f})",
    ]

    if metadata.authors:
        lines.append("- Authors: " + "; ".join(metadata.authors))
    if metadata.year is not None:
        lines.append(f"- Year: {metadata.year}")
    if metadata.journal:
        lines.append(f"- Journal: {metadata.journal}")
    if metadata.doi:
        lines.append(f"- DOI: {metadata.doi}")
    if metadata.keywords:
        lines.append("- Keywords: " + "; ".join(metadata.keywords))
    if metadata.tags:
        lines.append("- Tags: " + ", ".join(metadata.tags))

    if assets_enabled:
        lines.extend(
            [
                f"- Assets: `assets/{pdf_path.stem}/`",
                (
                    f"- Visual fallback: {stats.tables} table(s), "
                    f"{stats.figures_kept} informative figure(s)"
                ),
            ]
        )

    if refs_path is not None:
        lines.append(f"- References: `references/{refs_path.name}`")

    for preserved in preserved_lines:
        if preserved not in lines:
            lines.append(preserved)

    if headings:
        lines.append("- Sections:")
        for heading in headings:
            if heading.casefold() == title.casefold():
                continue
            lines.append(f"  - {heading}")

    return "\n".join(lines).rstrip() + "\n"

def update_index_block(
    *,
    index_path: Path,
    pdf_path: Path,
    md_path: Path,
    refs_path: Path | None,
    winner: Candidate,
    stats: AssetStats,
    assets_enabled: bool,
) -> None:
    if index_path.exists():
        original = index_path.read_text(encoding="utf-8")
    else:
        original = (
            "# Literature corpus\n\n"
            "Índice compacto para recuperación. Use Markdown primero; si existen assets, "
            "úsalos sólo como fallback visual. El PDF es la fuente final de verificación.\n\n"
            "## Papers\n\n"
        )

    target: re.Match[str] | None = None
    preserved: list[str] = []
    marker = f"extracted/{md_path.name}"
    for match in INDEX_BLOCK_RE.finditer(original):
        block = match.group(0)
        if marker in block or (pdf_path.stem.casefold() in block.casefold()):
            target = match
            preserved = preserved_curated_index_lines(block)
            break

    new_block = build_index_block(
        pdf_path=pdf_path,
        md_path=md_path,
        refs_path=refs_path,
        winner=winner,
        stats=stats,
        assets_enabled=assets_enabled,
        preserved_lines=preserved,
    )

    if target:
        updated = original[: target.start()] + new_block
        after = original[target.end() :]
        if after and not after.startswith("\n"):
            updated += "\n"
        updated += after
    else:
        updated = original.rstrip() + "\n\n" + new_block

    write_atomic(index_path, updated.rstrip() + "\n")


# =============================================================================
# AI-readable bundle.md
# =============================================================================


def build_bundle(
    *,
    extracted_dir: Path,
    pdf_dir: Path,
    refs_dir: Path,
    bundle_path: Path,
    include_references: bool,
) -> int:
    """Concatenate the current corpus into one deterministic AI-readable Markdown file."""
    pdf_by_stem = {path.stem: path for path in pdf_dir.glob("*.pdf")}
    md_files = sorted(
        (
            path
            for path in extracted_dir.glob("*.md")
            if path.stem in pdf_by_stem
        ),
        key=lambda path: path.name.casefold(),
    )

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    lines = [
        "---",
        'format: "docling-math-corpus-bundle"',
        f"generated_at: {yaml_quote(generated_at)}",
        f"paper_count: {len(md_files)}",
        f"references_included: {'true' if include_references else 'false'}",
        'source_directory: "extracted/"',
        "---",
        "",
        "# Literature bundle",
        "",
        (
            "Machine-oriented corpus generated by docling-math. Each paper is delimited "
            "by explicit BEGIN/END markers so an AI can recover document boundaries reliably."
        ),
        "",
        (
            "Separated bibliographies are "
            + (
                "included after each paper."
                if include_references
                else "omitted by default to reduce retrieval noise."
            )
        ),
        "",
        "## Corpus map",
        "",
    ]

    blocks: list[str] = []
    for index, md_path in enumerate(md_files, 1):
        paper_id = f"P{index:03d}"
        title = derive_title(md_path, md_path.stem)
        pdf_path = pdf_by_stem[md_path.stem]
        refs_path = refs_dir / f"{md_path.stem}.references.md"
        headings = extract_index_headings(md_path, limit=6)

        lines.append(
            f"{index}. **{paper_id} — {title}**  "
            f"(Markdown: extracted/{md_path.name}; PDF: pdf/{pdf_path.name})"
        )
        useful = [h for h in headings if h.casefold() != title.casefold()][:5]
        if useful:
            lines.append("   - Sections: " + " · ".join(useful))

        raw = md_path.read_text(encoding="utf-8", errors="replace")
        body = strip_front_matter(raw).strip()

        block = [
            "",
            f"<!-- ===== BEGIN PAPER {paper_id} ===== -->",
            "",
            f"# {paper_id} — {title}",
            "",
            f"- Source Markdown: extracted/{md_path.name}",
            f"- Source PDF: pdf/{pdf_path.name}",
        ]
        if refs_path.exists():
            block.append(f"- References: references/{refs_path.name}")
        block.extend(
            [
                "",
                "<!-- BEGIN EXTRACTED CONTENT -->",
                "",
                body,
                "",
                "<!-- END EXTRACTED CONTENT -->",
            ]
        )

        if include_references and refs_path.exists():
            refs_raw = refs_path.read_text(encoding="utf-8", errors="replace")
            refs_body = strip_front_matter(refs_raw).strip()
            block.extend(
                [
                    "",
                    f"## {paper_id} — References",
                    "",
                    refs_body,
                ]
            )

        block.extend(
            [
                "",
                f"<!-- ===== END PAPER {paper_id} ===== -->",
                "",
            ]
        )
        blocks.append("\n".join(block))

    content = "\n".join(lines).rstrip() + "\n"
    if blocks:
        content += "\n## Papers\n" + "".join(blocks)
    write_atomic(bundle_path, content.rstrip() + "\n")
    print(f"[BUNDLE] {bundle_path} ({len(md_files)} papers)")
    return len(md_files)


# =============================================================================
# AGENTS.md retrieval policy
# =============================================================================


AGENTS_CONTENT = """# Literature retrieval policy for bib/

This directory is optimized for high-fidelity, low-context academic retrieval.

1. Start with `bib/INDEX.md`; identify only the relevant papers.
2. Use `bib/bundle.md` for whole-corpus review or when one file is easier to pass to an AI.
3. Read/search `bib/extracted/*.md` first for targeted retrieval. Markdown is the primary retrieval layer.
4. Formulae and tables in Markdown should be treated as structured extracted content, but
   critical exact values should still be verified against the original PDF when needed.
5. `bib/references/` is split out to reduce retrieval noise; search it for citation chaining.
6. `bib/assets/` exists only when extraction was run with `--assets`. Use a targeted crop
   when a visually encoded table/figure cannot be resolved reliably from Markdown.
7. `bib/pdf/*.pdf` is the source of truth.
8. Never infer a coefficient, p-value, confidence interval, sample size, or effect size from
   visibly corrupted extraction; verify it against the PDF.
"""


def ensure_agents_file(path: Path) -> None:
    if path.exists():
        return
    write_atomic(path, AGENTS_CONTENT)
    print(f"[AGENTS] created {path}")


# =============================================================================
# Reporting
# =============================================================================


def print_candidate(candidate: Candidate) -> None:
    diag = candidate.diagnostics
    print(
        f"    {candidate.mode:<16} "
        f"score={candidate.combined_score:6.1f} "
        f"text={diag.grade:<9} "
        f"chars/page={diag.chars_per_page:7.0f} "
        f"time={candidate.seconds:6.1f}s"
    )
    if candidate.confidence_mean or candidate.confidence_low:
        print(
            f"      Docling confidence: mean={candidate.confidence_mean or '-'} "
            f"low={candidate.confidence_low or '-'}"
        )
    if diag.reasons:
        print("      signals: " + "; ".join(diag.reasons[:6]))


def process_one_pdf(
    *,
    pdf_path: Path,
    md_path: Path,
    refs_dir: Path,
    assets_root: Path,
    index_path: Path,
    args: argparse.Namespace,
    device: AcceleratorDevice,
    artifacts_path: Path,
) -> tuple[bool, bool]:
    candidates: list[Candidate] = []
    renamed = False
    print(f"\n[PDF] {pdf_path.name}")

    common = dict(
        pdf_path=pdf_path,
        device=device,
        threads=args.threads,
        ocr_backend=args.ocr_backend,
        ocr_lang=args.ocr_lang,
        layout_preset=args.layout_preset,
        image_scale=args.image_scale,
        math_enrichment=args.math,
        table_enrichment=args.tables,
        assets_enabled=args.assets,
        artifacts_path=artifacts_path,
    )

    try:
        if args.strategy in {"compare", "smart", "hybrid"}:
            print("  [1] hybrid/native + OCR")
            hybrid = convert_candidate(mode="hybrid", **common)
            candidates.append(hybrid)
            print_candidate(hybrid)

        run_ocr = args.strategy in {"compare", "ocr"}
        if args.strategy == "smart" and candidates:
            run_ocr = smart_needs_ocr(candidates[0])

        if run_ocr:
            print("  [2] forced full-page OCR")
            ocr_candidate = convert_candidate(mode="full-page-ocr", **common)
            candidates.append(ocr_candidate)
            print_candidate(ocr_candidate)

        if not candidates:
            raise RuntimeError("No se produjo ningún candidato de extracción.")

        winner = choose_candidate(candidates)
        print(
            f"  [WINNER] {winner.mode} — "
            f"{winner.combined_score:.1f} ({winner.diagnostics.grade})"
        )

        paper_metadata = infer_paper_metadata(winner.markdown)
        if paper_metadata.title:
            print(f"  [METADATA] title={paper_metadata.title}")
        if paper_metadata.keywords:
            print(f"  [METADATA] keywords={len(paper_metadata.keywords)} tags={len(paper_metadata.tags)}")

        if args.rename_pdfs:
            pdf_path, md_path, renamed = rename_corpus_entry(
                pdf_path=pdf_path,
                md_path=md_path,
                refs_dir=refs_dir,
                assets_root=assets_root,
                index_path=index_path,
                markdown_for_identity=winner.markdown,
            )

        if args.write_pdf_metadata:
            if write_pdf_metadata(pdf_path, paper_metadata):
                print("  [PDF-METADATA] Info + XMP updated")

        assets_dir = assets_root / pdf_path.stem
        if args.assets:
            print("  [ASSETS] exporting table crops + filtered figures")
            stats = export_assets(
                document=winner.result.document,
                assets_dir=assets_dir,
                min_figure_area=args.min_figure_area,
                keep_all_figures=args.keep_all_figures,
            )
        else:
            stats = AssetStats()

        refs_path = finalize_markdown(
            pdf_path=pdf_path,
            winner=winner,
            md_path=md_path,
            refs_dir=refs_dir,
            assets_dir=assets_dir,
            asset_stats=stats,
            split_references=not args.no_reference_split,
            assets_enabled=args.assets,
            paper_metadata=paper_metadata,
            metadata_enabled=args.metadata,
            obsidian=args.obsidian,
        )

        if not args.no_index:
            update_index_block(
                index_path=index_path,
                pdf_path=pdf_path,
                md_path=md_path,
                refs_path=refs_path,
                winner=winner,
                stats=stats,
                assets_enabled=args.assets,
            )

        print(
            f"  [OK] md={md_path.name} | "
            f"refs={'yes' if refs_path else 'no'} | "
            f"assets={'yes' if args.assets else 'no'}"
        )

        candidates.clear()
        cleanup_memory()
        return True, renamed

    except Exception as exc:
        print(f"  [FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        candidates.clear()
        cleanup_memory()
        return False, renamed

# =============================================================================
# Main
# =============================================================================


def main() -> int:
    args = parse_args()
    if args.obsidian_vault is not None:
        args.obsidian = True

    if args.threads < 1:
        print("[ERROR] --threads debe ser >= 1", file=sys.stderr)
        return 1
    if args.image_scale <= 0:
        print("[ERROR] --image-scale debe ser > 0", file=sys.stderr)
        return 1
    if not 0 <= args.min_figure_area <= 1:
        print("[ERROR] --min-figure-area debe estar entre 0 y 1", file=sys.stderr)
        return 1

    try:
        repo = args.repo.expanduser().resolve() if args.repo else discover_repo_root()
        bib = resolve_bib_dir(repo)
        pdf_dir = bib / "pdf"
        extracted_dir = bib / "extracted"
        refs_dir = bib / "references"
        assets_root = bib / "assets"
        index_path = bib / "INDEX.md"
        agents_path = bib / "AGENTS.md"
        bundle_path = bib / "bundle.md"
        artifacts_path = resolve_artifacts_path(args.artifacts_path)

        extracted_dir.mkdir(parents=True, exist_ok=True)
        refs_dir.mkdir(parents=True, exist_ok=True)
        if args.assets:
            assets_root.mkdir(parents=True, exist_ok=True)

        pdfs = discover_pdfs(pdf_dir, args.paper)
        if not pdfs:
            print(f"[ERROR] No se encontraron PDFs en {pdf_dir}", file=sys.stderr)
            return 1

        extraction_needed = any(
            needs_processing(
                pdf_path,
                extracted_dir / f"{pdf_path.stem}.md",
                args.force,
            )
            for pdf_path in pdfs
        )

        device: AcceleratorDevice | None = None
        if extraction_needed:
            ensure_model_cache(
                artifacts_path=artifacts_path,
                layout_preset=args.layout_preset,
                refresh=args.refresh_models,
            )
            # Resolve once so CPU confirmation can never repeat once per paper.
            device = resolve_device(args.device)
        else:
            print("[DEVICE] no extraction needed; skipping model/GPU initialization")

        if not args.no_agents:
            ensure_agents_file(agents_path)

        if not args.no_index and index_path.exists():
            backup_dir = bib / ".backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = backup_dir / f"INDEX.md.{timestamp}.bak"
            shutil.copy2(index_path, backup)
            print(f"[BACKUP] {backup}")

        print("=" * 80)
        print(" DOCLING-MATH — HIGH-FIDELITY ACADEMIC EXTRACTION")
        print("=" * 80)
        print(f"Repo            : {repo}")
        print(f"PDFs            : {len(pdfs)}")
        print(f"Strategy        : {args.strategy}")
        print(f"Device          : {device if device is not None else 'not needed'}")
        print(f"OCR             : RapidOCR/{args.ocr_backend} lang={args.ocr_lang}")
        print(f"Layout          : {args.layout_preset}")
        print(f"Math            : {'CodeFormulaV2' if args.math else 'off'}")
        print(f"Tables          : {'TableFormer ACCURATE' if args.tables else 'off'}")
        print(f"Persist assets  : {'yes' if args.assets else 'no'}")
        print(f"Model cache     : {artifacts_path}")
        print(f"Bundle          : {'no' if args.no_bundle else 'bib/bundle.md'}")
        print(f"Rename PDFs     : {'yes' if args.rename_pdfs else 'no'}")
        print("Page markers    : yes")
        print("Reference split : " + ("no" if args.no_reference_split else "yes"))
        print("=" * 80)

        converted = skipped = failed = renamed = 0
        start_total = time.perf_counter()

        for idx, pdf_path in enumerate(pdfs, 1):
            md_path = extracted_dir / f"{pdf_path.stem}.md"
            print(f"\n[{idx:02d}/{len(pdfs):02d}]", end="")

            if not needs_processing(pdf_path, md_path, args.force):
                existing_markdown = (
                    md_path.read_text(encoding="utf-8", errors="replace")
                    if md_path.exists()
                    else ""
                )

                if args.rename_pdfs and existing_markdown:
                    pdf_path, md_path, did_rename = rename_corpus_entry(
                        pdf_path=pdf_path,
                        md_path=md_path,
                        refs_dir=refs_dir,
                        assets_root=assets_root,
                        index_path=index_path,
                        markdown_for_identity=existing_markdown,
                    )
                    if did_rename:
                        renamed += 1
                        existing_markdown = md_path.read_text(
                            encoding="utf-8",
                            errors="replace",
                        )

                if existing_markdown and (
                    args.refresh_metadata
                    or args.obsidian
                    or args.write_pdf_metadata
                ):
                    paper_metadata = infer_paper_metadata(existing_markdown)

                    if args.write_pdf_metadata:
                        if write_pdf_metadata(pdf_path, paper_metadata):
                            print(" [PDF-METADATA] Info + XMP updated")

                    if args.refresh_metadata or args.obsidian or (
                        args.write_pdf_metadata and args.metadata
                    ):
                        enrich_markdown_file(
                            md_path,
                            pdf_name=pdf_path.name,
                            obsidian=args.obsidian,
                        )
                        print(" [METADATA] Markdown properties refreshed")
                    elif args.write_pdf_metadata:
                        # Keep extraction freshness after an intentional PDF metadata rewrite.
                        write_atomic(md_path, existing_markdown)

                print(f" [SKIP] extraction: {pdf_path.name}")
                skipped += 1
                continue

            assert device is not None
            success, did_rename = process_one_pdf(
                pdf_path=pdf_path,
                md_path=md_path,
                refs_dir=refs_dir,
                assets_root=assets_root,
                index_path=index_path,
                args=args,
                device=device,
                artifacts_path=artifacts_path,
            )
            if did_rename:
                renamed += 1
            if success:
                converted += 1
            else:
                failed += 1

        if args.obsidian and args.related_papers:
            related_changed = update_related_papers(extracted_dir)
            print(f"[OBSIDIAN] related links updated in {related_changed} note(s)")

        if not args.no_bundle:
            build_bundle(
                extracted_dir=extracted_dir,
                pdf_dir=pdf_dir,
                refs_dir=refs_dir,
                bundle_path=bundle_path,
                include_references=args.bundle_references,
            )

        if args.obsidian_vault is not None:
            notes, pdf_copies = sync_obsidian_vault(
                bib_dir=bib,
                vault_dir=args.obsidian_vault,
            )
            print(
                f"[OBSIDIAN] vault synced: {notes} note(s), "
                f"{pdf_copies} PDF(s) -> {args.obsidian_vault}"
            )

        elapsed = time.perf_counter() - start_total
        print("\n" + "=" * 80)
        print(f"Converted : {converted}")
        print(f"Skipped   : {skipped}")
        print(f"Failed    : {failed}")
        print(f"Renamed   : {renamed}")
        print(f"Elapsed   : {elapsed / 60:.1f} min")
        print("=" * 80)
        return 2 if failed else 0

    except KeyboardInterrupt:
        print("\n[INTERRUPTED]", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"[ERROR] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
