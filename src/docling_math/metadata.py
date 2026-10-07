"""Bibliographic metadata inference and Obsidian-oriented normalization."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

import yaml


GENERIC_HEADINGS = {
    "abstract",
    "summary",
    "resumen",
    "introduction",
    "introduccion",
    "keywords",
    "key words",
    "palabras clave",
    "contents",
    "table of contents",
}

AFFILIATION_SIGNALS = {
    "university",
    "universidad",
    "department",
    "departamento",
    "institute",
    "instituto",
    "faculty",
    "facultad",
    "school",
    "college",
    "laboratory",
    "laboratorio",
    "research center",
    "research centre",
    "hospital",
    "academy",
    "academia",
    "corresponding author",
    "correspondence",
    "email",
    "e-mail",
    "orcid",
    "doi",
    "http",
    "www.",
    "journal",
    "vol.",
    "volume",
}

GOOD_YEAR_CONTEXT = {
    "published",
    "publication",
    "copyright",
    "©",
    "journal",
    "volume",
    "vol.",
    "citation",
    "cite",
}

BAD_YEAR_CONTEXT = {
    "received",
    "accepted",
    "revised",
    "submitted",
}

_NAME_WORD_RE = re.compile(
    r"[A-Za-zÀ-ÖØ-öø-ÿ]+(?:[-'’][A-Za-zÀ-ÖØ-öø-ÿ]+)*"
)

DOI_RE = re.compile(
    r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b",
    flags=re.I,
)


@dataclass(frozen=True)
class PaperMetadata:
    """Normalized metadata shared by filenames, Markdown, PDF metadata, and UI."""

    title: str | None = None
    authors: tuple[str, ...] = ()
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    abstract: str | None = None
    keywords: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()

    @property
    def complete_for_filename(self) -> bool:
        return bool(self.title and self.authors and self.year is not None)


def split_front_matter(markdown: str) -> tuple[dict[str, Any], str]:
    """Return YAML front matter plus body; invalid YAML is treated conservatively."""
    if not markdown.startswith("---\n"):
        return {}, markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return {}, markdown

    raw = markdown[4:end]
    body = markdown[end + len("\n---\n") :].lstrip()
    try:
        parsed = yaml.safe_load(raw) or {}
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception:
        parsed = {}
    return parsed, body


def strip_front_matter(markdown: str) -> str:
    return split_front_matter(markdown)[1]


def ascii_fold(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def clean_inline_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_\x60~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_author_line(text: str) -> str:
    text = clean_inline_markdown(text)
    text = re.sub(r"\b(?:https?://\S+|www\.\S+|\S+@\S+)\b", " ", text, flags=re.I)
    text = re.sub(r"\bORCID\b.*$", " ", text, flags=re.I)
    text = re.sub(r"[*†‡§]+", " ", text)
    text = re.sub(r"(?<=\D)\d+(?:,\d+)*(?=\D|$)", " ", text)
    text = re.sub(r"[\[\](){}]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ,;")


def _extract_title(body: str) -> tuple[str | None, int | None]:
    lines = body.splitlines()[:100]

    for index, line in enumerate(lines):
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if not match:
            continue
        title = clean_inline_markdown(match.group(1))
        if title and title.casefold() not in GENERIC_HEADINGS and len(title) >= 6:
            return title, index

    for index, line in enumerate(lines[:30]):
        title = clean_inline_markdown(re.sub(r"^\s*#{1,6}\s+", "", line))
        if (
            len(title) >= 12
            and title.casefold() not in GENERIC_HEADINGS
            and not re.search(r"\b(?:doi|abstract|resumen)\b", title, flags=re.I)
        ):
            return title, index

    return None, None


def _plausible_author_line(text: str) -> bool:
    if not text or len(text) > 240:
        return False
    lower = text.casefold()
    if any(signal in lower for signal in AFFILIATION_SIGNALS):
        return False
    if re.search(r"\b(?:abstract|resumen|keywords?|palabras clave|jel|classification)\b", lower):
        return False
    if re.search(r"\b(?:19|20)\d{2}\b", text):
        return False

    words = _NAME_WORD_RE.findall(text)
    if not 2 <= len(words) <= 24:
        return False
    if text.count(".") >= 2 and len(words) > 12:
        return False
    return True


def _split_authors(text: str) -> list[str]:
    text = clean_author_line(text)
    parts = re.split(r"\s*(?:;|\band\b|\by\b|&)\s*", text, flags=re.I)
    parts = [part.strip(" ,") for part in parts if part.strip(" ,")]

    if len(parts) == 1 and "," in text:
        comma_parts = [part.strip() for part in text.split(",") if part.strip()]
        if 2 <= len(comma_parts) <= 8 and all(
            len(_NAME_WORD_RE.findall(part)) >= 2
            for part in comma_parts
        ):
            parts = comma_parts
    return parts


def _extract_author_names(body: str, title_index: int | None) -> tuple[str, ...]:
    lines = body.splitlines()
    start = (title_index or 0) + 1
    candidates: list[tuple[int, int, str]] = []

    for offset, raw in enumerate(lines[start : start + 16]):
        visible = clean_inline_markdown(raw)
        if not visible:
            continue

        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", raw)
        if heading:
            normalized = clean_inline_markdown(heading.group(1)).casefold()
            if normalized in GENERIC_HEADINGS or normalized.startswith("abstract"):
                break

        if re.match(r"^(?:abstract|resumen|keywords?|palabras clave)\b", visible, flags=re.I):
            break

        clean = clean_author_line(raw)
        if not _plausible_author_line(clean):
            continue

        words = _NAME_WORD_RE.findall(clean)
        score = max(0, 8 - offset)
        if re.search(r"\b(?:and|y)\b|&|;", clean, flags=re.I):
            score += 6
        if "," in clean:
            score += 2
        if 2 <= len(words) <= 10:
            score += 4
        candidates.append((score, -offset, clean))

    candidates.sort(reverse=True)
    for _score, _offset, candidate in candidates:
        people = tuple(_split_authors(candidate))
        if people:
            return people
    return ()


def surname_from_name(name: str) -> str | None:
    """Return a filesystem/tag-safe surname; Cortes-Toto -> CortesToto."""
    clean = clean_author_line(name)
    if not clean:
        return None

    if clean.count(",") == 1:
        left, right = (part.strip() for part in clean.split(",", 1))
        left_words = _NAME_WORD_RE.findall(left)
        right_words = _NAME_WORD_RE.findall(right)
        surname = left_words[-1] if left_words and right_words else ""
    else:
        words = _NAME_WORD_RE.findall(clean)
        surname = words[-1] if len(words) >= 2 else ""

    surname = ascii_fold(surname)
    surname = re.sub(r"[-'’\s]+", "", surname)
    surname = re.sub(r"[^A-Za-z0-9]", "", surname)
    return surname or None


def _extract_year(body: str) -> int | None:
    lines = body.splitlines()[:140]
    choices: list[tuple[int, int, int]] = []
    for index, line in enumerate(lines):
        lower = line.casefold()
        for match in re.finditer(r"\b(19\d{2}|20\d{2})\b", line):
            year = int(match.group(1))
            score = 0
            if index < 30:
                score += 3
            if any(signal in lower for signal in GOOD_YEAR_CONTEXT):
                score += 7
            if any(signal in lower for signal in BAD_YEAR_CONTEXT):
                score -= 6
            choices.append((score, year, -index))
    if not choices:
        return None
    choices.sort(reverse=True)
    return choices[0][1]


def _extract_doi(body: str) -> str | None:
    match = DOI_RE.search(body[:12000])
    if not match:
        return None
    return match.group(0).rstrip(".,;)")


def _split_keywords(text: str) -> tuple[str, ...]:
    text = clean_inline_markdown(text)
    text = re.sub(r"^(?:keywords?|key words|palabras clave)\s*[:—-]\s*", "", text, flags=re.I)
    parts = re.split(r"\s*[;,•·|]\s*", text)
    cleaned: list[str] = []
    seen: set[str] = set()
    for part in parts:
        value = re.sub(r"\s+", " ", part).strip(" .")
        if not value or len(value) > 100:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value)
    return tuple(cleaned[:20])


def _extract_keywords(body: str) -> tuple[str, ...]:
    lines = body.splitlines()
    for index, raw in enumerate(lines[:220]):
        visible = clean_inline_markdown(raw)
        inline = re.match(
            r"^(?:keywords?|key words|palabras clave)\s*[:—-]\s*(.+)$",
            visible,
            flags=re.I,
        )
        if inline:
            return _split_keywords(inline.group(1))

        heading = re.match(
            r"^\s*#{1,6}\s+(?:keywords?|key words|palabras clave)\s*$",
            raw,
            flags=re.I,
        )
        if heading:
            collected: list[str] = []
            for later in lines[index + 1 : index + 5]:
                if re.match(r"^\s*#{1,6}\s+", later):
                    break
                visible_later = clean_inline_markdown(later)
                if visible_later:
                    collected.append(visible_later)
            if collected:
                return _split_keywords("; ".join(collected))
    return ()


def _extract_abstract(body: str) -> str | None:
    lines = body.splitlines()
    for index, raw in enumerate(lines[:240]):
        visible = clean_inline_markdown(raw)
        inline = re.match(r"^(?:abstract|resumen)\s*[:—-]\s*(.+)$", visible, flags=re.I)
        if inline and len(inline.group(1)) >= 40:
            return inline.group(1).strip()

        heading = re.match(r"^\s*#{1,6}\s+(?:abstract|resumen)\s*$", raw, flags=re.I)
        if not heading:
            continue

        collected: list[str] = []
        for later in lines[index + 1 :]:
            if re.match(r"^\s*#{1,6}\s+", later):
                break
            visible_later = clean_inline_markdown(later)
            if visible_later:
                collected.append(visible_later)
            if sum(len(x) for x in collected) > 2000:
                break
        abstract = " ".join(collected).strip()
        if len(abstract) >= 40:
            return abstract
    return None


def _extract_journal(body: str) -> str | None:
    lines = [clean_inline_markdown(line) for line in body.splitlines()[:80]]
    patterns = (
        re.compile(r"\b((?:Journal|Review|Transactions|Proceedings)\s+of\s+[^|;]{3,100})", re.I),
        re.compile(r"\b((?:[A-Z][A-Za-z&-]+\s+){0,4}(?:Journal|Review|Transactions))\b"),
    )
    for line in lines:
        if not line or len(line) > 220:
            continue
        for pattern in patterns:
            match = pattern.search(line)
            if match:
                value = re.sub(r"\s+", " ", match.group(1)).strip(" .,:;-")
                value = re.split(r"\s+(?:vol\.?|volume|doi|https?://)", value, maxsplit=1, flags=re.I)[0]
                if 5 <= len(value) <= 120:
                    return value
    return None


def _front_list(value: Any) -> tuple[str, ...]:
    if isinstance(value, list):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str) and value.strip():
        return (value.strip(),)
    return ()


def normalize_tag(text: str) -> str | None:
    value = ascii_fold(text).casefold().strip()
    aliases = {
        "time series analysis": "time-series",
        "time series": "time-series",
        "bayesian inference": "bayesian",
        "convolutional neural networks": "cnn",
        "convolutional neural network": "cnn",
        "machine learning": "machine-learning",
        "deep learning": "deep-learning",
        "trend estimation": "trend-estimation",
    }
    if value in aliases:
        return aliases[value]

    value = re.sub(r"['’]", "", value)
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value or len(value) > 60:
        return None
    return value


def build_tags(
    *,
    authors: tuple[str, ...],
    year: int | None,
    keywords: tuple[str, ...],
    max_topic_tags: int = 5,
) -> tuple[str, ...]:
    tags: list[str] = ["literature"]
    if year is not None:
        tags.append(f"year/{year}")

    for author in authors[:2]:
        surname = surname_from_name(author)
        if surname:
            tags.append(f"author/{surname.casefold()}")

    topic_count = 0
    for keyword in keywords:
        tag = normalize_tag(keyword)
        if not tag or tag in tags:
            continue
        tags.append(tag)
        topic_count += 1
        if topic_count >= max_topic_tags:
            break

    return tuple(tags)


def _metadata_from_front(front: dict[str, Any]) -> dict[str, Any]:
    title = front.get("title")
    authors = _front_list(front.get("authors"))
    keywords = _front_list(front.get("keywords"))
    tags = _front_list(front.get("tags"))
    aliases = _front_list(front.get("aliases"))

    year: int | None = None
    try:
        if front.get("year") is not None:
            year = int(front["year"])
    except (TypeError, ValueError):
        pass

    return {
        "title": str(title).strip() if title else None,
        "authors": authors,
        "year": year,
        "journal": str(front.get("journal")).strip() if front.get("journal") else None,
        "doi": str(front.get("doi")).strip() if front.get("doi") else None,
        "abstract": str(front.get("abstract")).strip() if front.get("abstract") else None,
        "keywords": keywords,
        "tags": tags,
        "aliases": aliases,
    }


def infer_paper_metadata(markdown: str) -> PaperMetadata:
    """Infer bibliographic metadata, preferring stable existing YAML values."""
    front, body = split_front_matter(markdown)
    existing = _metadata_from_front(front)

    inferred_title, title_index = _extract_title(body)
    title = existing["title"] or inferred_title

    authors = existing["authors"] or _extract_author_names(body, title_index)
    year = existing["year"] if existing["year"] is not None else _extract_year(body)
    journal = existing["journal"] or _extract_journal(body)
    doi = existing["doi"] or _extract_doi(body)
    abstract = existing["abstract"] or _extract_abstract(body)
    keywords = existing["keywords"] or _extract_keywords(body)

    tags = existing["tags"] or build_tags(
        authors=authors,
        year=year,
        keywords=keywords,
    )
    aliases = existing["aliases"] or ((title,) if title else ())

    return PaperMetadata(
        title=title,
        authors=tuple(authors),
        year=year,
        journal=journal,
        doi=doi,
        abstract=abstract,
        keywords=tuple(keywords),
        tags=tuple(tags),
        aliases=tuple(aliases),
    )


def title_slug(title: str, max_chars: int = 120) -> str:
    title = ascii_fold(title).replace("&", " and ")
    title = re.sub(r"['’]", "", title)
    title = re.sub(r"[^A-Za-z0-9]+", "_", title)
    title = re.sub(r"_+", "_", title).strip("_")
    if len(title) > max_chars:
        title = title[:max_chars].rstrip("_")
    return title


def canonical_stem(metadata: PaperMetadata) -> str | None:
    """Return Author1_Author2-Year-Title or None when metadata is insufficient."""
    if not metadata.complete_for_filename:
        return None

    surnames = [
        surname
        for surname in (surname_from_name(author) for author in metadata.authors[:2])
        if surname
    ]
    if not surnames:
        return None

    slug = title_slug(metadata.title or "")
    if not slug:
        return None
    return f"{'_'.join(surnames)}-{metadata.year}-{slug}"
