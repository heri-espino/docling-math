"""Filename inference for academic PDFs.

The renaming policy is deliberately conservative: if title, publication year, and at least
one plausible author surname cannot be inferred from the extracted Markdown, the PDF is
left untouched.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

GENERIC_HEADINGS = {
    "abstract",
    "summary",
    "resumen",
    "introduction",
    "introduccion",
    "keywords",
    "key words",
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


@dataclass(frozen=True)
class PaperIdentity:
    """Metadata sufficient for the canonical academic filename."""

    authors: tuple[str, ...]
    year: int
    title: str
    stem: str


def strip_front_matter(markdown: str) -> str:
    if not markdown.startswith("---\n"):
        return markdown
    end = markdown.find("\n---\n", 4)
    if end == -1:
        return markdown
    return markdown[end + len("\n---\n") :].lstrip()


def _ascii_fold(text: str) -> str:
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", "ignore")
        .decode("ascii")
    )


def _clean_inline_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"[*_`~]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _clean_author_line(text: str) -> str:
    text = _clean_inline_markdown(text)
    text = re.sub(r"\b(?:https?://\S+|www\.\S+|\S+@\S+)\b", " ", text, flags=re.I)
    text = re.sub(r"\bORCID\b.*$", " ", text, flags=re.I)
    text = re.sub(r"[*†‡§]+", " ", text)
    text = re.sub(r"(?<=\D)\d+(?:,\d+)*(?=\D|$)", " ", text)
    text = re.sub(r"[\[\](){}]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" ,;")


def _extract_title(markdown: str) -> tuple[str | None, int | None]:
    lines = strip_front_matter(markdown).splitlines()[:100]

    for index, line in enumerate(lines):
        match = re.match(r"^\s*#\s+(.+?)\s*$", line)
        if not match:
            continue
        title = _clean_inline_markdown(match.group(1))
        if (
            title
            and title.casefold() not in GENERIC_HEADINGS
            and len(title) >= 6
        ):
            return title, index

    for index, line in enumerate(lines[:30]):
        title = _clean_inline_markdown(re.sub(r"^\s*#{1,6}\s+", "", line))
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
    if re.search(r"\b(?:abstract|resumen|keywords?|jel|classification)\b", lower):
        return False
    if re.search(r"\b(?:19|20)\d{2}\b", text):
        return False

    words = _NAME_WORD_RE.findall(text)
    if not 2 <= len(words) <= 24:
        return False

    # A sentence is much less likely to be an author block than a short name list.
    if text.count(".") >= 2 and len(words) > 12:
        return False

    return True


def _split_authors(text: str) -> list[str]:
    text = _clean_author_line(text)
    parts = re.split(r"\s*(?:;|\band\b|\by\b|&)\s*", text, flags=re.I)
    parts = [part.strip(" ,") for part in parts if part.strip(" ,")]

    if len(parts) == 1 and "," in text:
        comma_parts = [part.strip() for part in text.split(",") if part.strip()]
        if len(comma_parts) >= 2 and all(
            len(_NAME_WORD_RE.findall(part)) >= 2
            for part in comma_parts
        ):
            parts = comma_parts

    return parts


def _surname_from_name(name: str) -> str | None:
    clean = _clean_author_line(name)
    if not clean:
        return None

    # Support "Surname, Given" in addition to the usual "Given Surname".
    if clean.count(",") == 1:
        left, right = (part.strip() for part in clean.split(",", 1))
        left_words = _NAME_WORD_RE.findall(left)
        right_words = _NAME_WORD_RE.findall(right)
        if left_words and right_words:
            surname = left_words[-1]
        else:
            surname = ""
    else:
        words = _NAME_WORD_RE.findall(clean)
        surname = words[-1] if len(words) >= 2 else ""

    surname = _ascii_fold(surname)
    # Requested convention: Cortes-Toto -> CortesToto.
    surname = re.sub(r"[-'’\s]+", "", surname)
    surname = re.sub(r"[^A-Za-z0-9]", "", surname)
    return surname or None


def _extract_authors(markdown: str, title_index: int | None) -> tuple[str, ...]:
    lines = strip_front_matter(markdown).splitlines()
    start = (title_index or 0) + 1
    candidates: list[tuple[int, int, str]] = []

    for offset, raw in enumerate(lines[start : start + 16]):
        visible = _clean_inline_markdown(raw)
        if not visible:
            continue

        heading = re.match(r"^\s*#{1,6}\s+(.+?)\s*$", raw)
        if heading:
            normalized = _clean_inline_markdown(heading.group(1)).casefold()
            if normalized in GENERIC_HEADINGS or normalized.startswith("abstract"):
                break

        if re.match(r"^(?:abstract|resumen|keywords?)\b", visible, flags=re.I):
            break

        clean = _clean_author_line(raw)
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
        people = _split_authors(candidate)
        surnames = [
            surname
            for surname in (_surname_from_name(person) for person in people)
            if surname
        ]
        if surnames:
            return tuple(surnames[:2])

    return ()


def _extract_year(markdown: str) -> int | None:
    lines = strip_front_matter(markdown).splitlines()[:140]
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

    # Ties prefer the later year; this helps when both a received year and a
    # publication/copyright year occur on the first page.
    choices.sort(reverse=True)
    return choices[0][1]


def title_slug(title: str, max_chars: int = 120) -> str:
    title = _ascii_fold(title).replace("&", " and ")
    title = re.sub(r"['’]", "", title)
    title = re.sub(r"[^A-Za-z0-9]+", "_", title)
    title = re.sub(r"_+", "_", title).strip("_")
    if len(title) > max_chars:
        title = title[:max_chars].rstrip("_")
    return title


def infer_paper_identity(markdown: str) -> PaperIdentity | None:
    """Infer Author1_Author2-Year-Title from extracted academic Markdown."""
    title, title_index = _extract_title(markdown)
    authors = _extract_authors(markdown, title_index)
    year = _extract_year(markdown)

    if not title or not authors or year is None:
        return None

    slug = title_slug(title)
    if not slug:
        return None

    stem = f"{'_'.join(authors)}-{year}-{slug}"
    return PaperIdentity(authors=authors, year=year, title=title, stem=stem)
