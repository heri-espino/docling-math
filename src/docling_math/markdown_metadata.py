"""Markdown front matter enrichment and Obsidian relationship helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .metadata import PaperMetadata, infer_paper_metadata, split_front_matter


def _topic_tags(tags: tuple[str, ...] | list[str]) -> set[str]:
    return {
        str(tag)
        for tag in tags
        if tag
        and str(tag) != "literature"
        and not str(tag).startswith("author/")
        and not str(tag).startswith("year/")
    }


def _ordered_front_matter(
    existing: dict[str, Any],
    *,
    paper_id: str,
    pdf_name: str,
    metadata: PaperMetadata,
    obsidian: bool,
) -> dict[str, Any]:
    front: dict[str, Any] = {}

    # Human / Obsidian-facing properties first.
    front["id"] = paper_id
    if metadata.title:
        front["title"] = metadata.title
    if metadata.authors:
        front["authors"] = list(metadata.authors)
    if metadata.year is not None:
        front["year"] = metadata.year
    if metadata.journal:
        front["journal"] = metadata.journal
    if metadata.doi:
        front["doi"] = metadata.doi
    if metadata.keywords:
        front["keywords"] = list(metadata.keywords)
    if metadata.tags:
        front["tags"] = list(metadata.tags)
    if metadata.aliases:
        front["aliases"] = list(metadata.aliases)

    topics = sorted(_topic_tags(metadata.tags))
    if topics:
        front["topics"] = topics

    if obsidian:
        front["pdf"] = f"[[{pdf_name}]]"
        css = existing.get("cssclasses")
        classes = list(css) if isinstance(css, list) else []
        if "literature-note" not in classes:
            classes.append("literature-note")
        front["cssclasses"] = classes

    # Preserve extraction/provenance/custom fields that are not owned above.
    owned = set(front)
    for key, value in existing.items():
        if key in owned:
            continue
        front[key] = value

    return front


def enrich_markdown_text(
    markdown: str,
    *,
    paper_id: str,
    pdf_name: str,
    metadata: PaperMetadata | None = None,
    obsidian: bool = False,
) -> str:
    """Merge bibliographic metadata into YAML without changing the extracted body."""
    existing, body = split_front_matter(markdown)
    resolved = metadata or infer_paper_metadata(markdown)
    front = _ordered_front_matter(
        existing,
        paper_id=paper_id,
        pdf_name=pdf_name,
        metadata=resolved,
        obsidian=obsidian,
    )
    dumped = yaml.safe_dump(
        front,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
        width=1000,
    ).rstrip()
    return f"---\n{dumped}\n---\n\n{body.lstrip()}"


def enrich_markdown_file(
    path: Path,
    *,
    pdf_name: str,
    obsidian: bool = False,
) -> PaperMetadata:
    text = path.read_text(encoding="utf-8", errors="replace")
    metadata = infer_paper_metadata(text)
    enriched = enrich_markdown_text(
        text,
        paper_id=path.stem,
        pdf_name=pdf_name,
        metadata=metadata,
        obsidian=obsidian,
    )
    temp = path.with_name(f".{path.name}.metadata.tmp")
    temp.write_text(enriched, encoding="utf-8")
    temp.replace(path)
    return metadata


def _front_tags(front: dict[str, Any]) -> tuple[str, ...]:
    value = front.get("tags")
    if isinstance(value, list):
        return tuple(str(item) for item in value if str(item))
    if isinstance(value, str) and value:
        return (value,)
    return ()


def update_related_papers(
    extracted_dir: Path,
    *,
    max_related: int = 5,
    min_shared_topics: int = 1,
) -> int:
    """Write Obsidian wikilinks based on shared normalized topic tags."""
    records: list[tuple[Path, dict[str, Any], str, set[str]]] = []
    for path in sorted(extracted_dir.glob("*.md"), key=lambda p: p.name.casefold()):
        text = path.read_text(encoding="utf-8", errors="replace")
        front, _body = split_front_matter(text)
        topics = _topic_tags(_front_tags(front))
        title = str(front.get("title") or path.stem)
        records.append((path, front, title, topics))

    changed = 0
    for path, front, _title, topics in records:
        scored: list[tuple[int, float, str, str]] = []
        if topics:
            for other_path, _other_front, other_title, other_topics in records:
                if other_path == path or not other_topics:
                    continue
                shared = topics & other_topics
                if len(shared) < min_shared_topics:
                    continue
                union = topics | other_topics
                jaccard = len(shared) / max(len(union), 1)
                scored.append(
                    (len(shared), jaccard, other_title.casefold(), other_path.stem)
                )

        scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
        related = [f"[[{stem}]]" for *_prefix, stem in scored[:max_related]]

        text = path.read_text(encoding="utf-8", errors="replace")
        current_front, body = split_front_matter(text)
        old_related = current_front.get("related")
        if related:
            current_front["related"] = related
        else:
            current_front.pop("related", None)

        if old_related == current_front.get("related"):
            continue

        dumped = yaml.safe_dump(
            current_front,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
            width=1000,
        ).rstrip()
        updated = f"---\n{dumped}\n---\n\n{body.lstrip()}"
        temp = path.with_name(f".{path.name}.related.tmp")
        temp.write_text(updated, encoding="utf-8")
        temp.replace(path)
        changed += 1

    return changed
