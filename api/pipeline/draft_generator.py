"""
Stage 5: Generate section content using Claude Sonnet 4.6.

For each outline section:
1. Retrieves assigned chunks as evidence
2. Injects voice system prompt if voice calibration is enabled
3. Writes section prose with inline citations [Source N, p.X]
4. Parses citations into a structured list

Public API:
  generate_section(client, section, chunk_map, deliverable_type, voice_system_prompt)
  instruct_section(client, section, instruction, chunk_map, deliverable_type, voice_system_prompt)
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

_SECTION_PROMPT = """\
{voice_block}You are writing one section of a {deliverable_type} research document.

## Section to Write
Title: {section_title}
Description: {section_description}
Target length: approximately {suggested_length} words

## Evidence to Synthesise
{evidence_text}

## Source Index
{source_index}

## Instructions
Write the section content in well-structured prose.
- Cite sources using inline markers like [Source 1, p.3] or [Source 2] when drawing on evidence.
- Use the exact source numbers from the Source Index above.
- Do not include the section title in your output (it will be rendered separately).
- Use markdown headers (## Subsection) only for subsections listed in the description.
- Target the suggested length but prioritise quality over word count.

Write the section now:"""

_INSTRUCT_PROMPT = """\
{voice_block}You are editing a section of a {deliverable_type} document.

## Current Section: {section_title}
{current_content}

## Edit Instruction
{instruction}

Rewrite the section following the instruction. Maintain inline citations where appropriate.
Output only the revised section content (no title):\
"""

# Matches [Source N] or [Source N, p.X] (case-insensitive)
_CITATION_RE = re.compile(
    r"\[Source\s+(\d+)(?:,\s*p\.?\s*(\d+))?\]", re.IGNORECASE
)


# ─── Public functions ─────────────────────────────────────────────────────────


async def generate_section(
    client: Any,
    section: dict[str, Any],
    chunk_map: dict[str, dict[str, Any]],
    deliverable_type: str,
    voice_system_prompt: str | None = None,
) -> dict[str, Any]:
    """
    Generate content for one outline section.

    Returns a dict with keys: id, title, content, status, citations.
    """
    section_id = section.get("id", "s0")
    title = section.get("title", "Section")
    chunk_ids: list[str] = section.get("chunk_ids") or []
    assigned_chunks = [chunk_map[cid] for cid in chunk_ids if cid in chunk_map]

    if not client:
        return _placeholder_section(section)

    evidence_text = _build_evidence_text(assigned_chunks)
    source_index_text, source_num_map, source_labels = _build_source_index(
        assigned_chunks
    )

    voice_block = f"## Writing Style\n{voice_system_prompt}\n\n" if voice_system_prompt else ""

    prompt = _SECTION_PROMPT.format(
        voice_block=voice_block,
        deliverable_type=deliverable_type,
        section_title=title,
        section_description=section.get("description", ""),
        suggested_length=section.get("suggested_length", 300),
        evidence_text=evidence_text,
        source_index=source_index_text or "No sources assigned",
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        content_raw = response.content[0].text.strip()
        content_html = _markdown_to_html(content_raw)
        citations = _parse_citations(
            content_raw, source_num_map, source_labels, assigned_chunks
        )
        return {
            "id": section_id,
            "title": title,
            "content": content_html,
            "status": "done",
            "citations": citations,
        }

    except Exception as exc:
        log.warning("Section generation failed for %s (%s)", section_id, exc)
        return {
            "id": section_id,
            "title": title,
            "content": f"<p><em>Generation failed: {exc}</em></p>",
            "status": "error",
            "citations": [],
        }


async def instruct_section(
    client: Any,
    section: dict[str, Any],
    instruction: str,
    chunk_map: dict[str, dict[str, Any]],
    deliverable_type: str,
    voice_system_prompt: str | None = None,
) -> dict[str, Any]:
    """
    Apply an instruction to rewrite/edit an existing section.

    Returns updated section dict.
    """
    current_html = section.get("content", "")
    # Strip HTML tags for the instruction prompt
    current_plain = re.sub(r"<[^>]+>", "", current_html).strip()

    voice_block = f"## Writing Style\n{voice_system_prompt}\n\n" if voice_system_prompt else ""

    if not client:
        return {
            **section,
            "content": f"<p><em>[Instruction applied: {instruction}]</em></p>{current_html}",
        }

    chunk_ids: list[str] = section.get("chunk_ids") or []
    assigned_chunks = [chunk_map[cid] for cid in chunk_ids if cid in chunk_map]
    _, source_num_map, source_labels = _build_source_index(assigned_chunks)

    prompt = _INSTRUCT_PROMPT.format(
        voice_block=voice_block,
        deliverable_type=deliverable_type,
        section_title=section.get("title", ""),
        current_content=current_plain,
        instruction=instruction,
    )

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        content_raw = response.content[0].text.strip()
        content_html = _markdown_to_html(content_raw)
        citations = _parse_citations(
            content_raw, source_num_map, source_labels, assigned_chunks
        )
        return {
            **section,
            "content": content_html,
            "status": "done",
            "citations": citations,
        }

    except Exception as exc:
        log.warning("Section instruct failed (%s)", exc)
        return {**section, "status": "error"}


# ─── Internal helpers ─────────────────────────────────────────────────────────


def _placeholder_section(section: dict[str, Any]) -> dict[str, Any]:
    title = section.get("title", "Section")
    return {
        "id": section.get("id", "s0"),
        "title": title,
        "content": f"<p><em>No AI client available — placeholder for '{title}'.</em></p>",
        "status": "done",
        "citations": [],
    }


def _build_evidence_text(chunks: list[dict[str, Any]]) -> str:
    if not chunks:
        return "No specific evidence assigned — draw from general knowledge."
    lines = []
    for i, row in enumerate(chunks[:20], start=1):
        snippet = (row.get("content") or "").strip()
        page = row.get("page_number")
        page_str = f" (p.{page})" if page else ""
        lines.append(f"[Evidence {i}]{page_str}\n{snippet}")
    return "\n\n".join(lines)


def _build_source_index(
    chunks: list[dict[str, Any]],
) -> tuple[str, dict[str, int], dict[str, str]]:
    """
    Build a numbered source index from a list of chunks.

    Returns (index_text, source_num_map, source_labels) where:
      source_num_map: source_id → source number (1-based)
      source_labels: source_id → display name
    """
    seen: dict[str, int] = {}
    source_labels: dict[str, str] = {}
    num = 1
    for row in chunks:
        sid = row["source_id"]
        if sid not in seen:
            seen[sid] = num
            label = row.get("filename") or row.get("url") or f"Source {num}"
            source_labels[sid] = str(label)
            num += 1

    lines = [f"Source {seen[sid]}: {source_labels[sid]}" for sid in seen]
    index_text = "\n".join(lines)
    return index_text, dict(seen), source_labels


def _parse_citations(
    content: str,
    source_num_map: dict[str, int],
    source_labels: dict[str, str],
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Extract unique citation objects from raw content text."""
    num_to_source_id: dict[int, str] = {v: k for k, v in source_num_map.items()}
    seen: set[tuple[int, int | None]] = set()
    citations: list[dict[str, Any]] = []

    for m in _CITATION_RE.finditer(content):
        num = int(m.group(1))
        page: int | None = int(m.group(2)) if m.group(2) else None
        key = (num, page)
        if key in seen:
            continue
        seen.add(key)

        source_id = num_to_source_id.get(num, "")
        source_title = source_labels.get(source_id, f"Source {num}")

        # Find a representative quote from the assigned chunks
        quote = ""
        if source_id:
            for chunk in chunks:
                if chunk["source_id"] == source_id:
                    if page is None or chunk.get("page_number") == page:
                        quote = (chunk.get("content") or "")[:200]
                        break

        citations.append(
            {
                "source_id": source_id,
                "source_title": source_title,
                "page": page,
                "marker": f"Source {num}" + (f", p.{page}" if page else ""),
                "quote": quote,
            }
        )

    return citations


def _markdown_to_html(text: str) -> str:
    """Convert basic markdown to HTML paragraphs and headings."""
    lines = text.split("\n")
    html_parts: list[str] = []
    in_para = False
    in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            if in_para:
                html_parts.append("</p>")
                in_para = False
            continue

        if stripped.startswith("### "):
            _close_blocks(html_parts, in_para, in_list)
            in_para = in_list = False
            heading = _inline_format(stripped[4:].strip())
            html_parts.append(
                f'<h5 class="font-semibold text-slate-700 mt-3 mb-1">{heading}</h5>'
            )

        elif stripped.startswith("## "):
            _close_blocks(html_parts, in_para, in_list)
            in_para = in_list = False
            heading = _inline_format(stripped[3:].strip())
            html_parts.append(
                f'<h4 class="font-semibold text-slate-800 mt-4 mb-2">{heading}</h4>'
            )

        elif stripped.startswith("# "):
            _close_blocks(html_parts, in_para, in_list)
            in_para = in_list = False
            heading = _inline_format(stripped[2:].strip())
            html_parts.append(
                f'<h3 class="font-semibold text-slate-900 mt-4 mb-2">{heading}</h3>'
            )

        elif stripped.startswith(("- ", "* ", "+ ")):
            if in_para:
                html_parts.append("</p>")
                in_para = False
            if not in_list:
                html_parts.append('<ul class="list-disc ml-5 space-y-0.5">')
                in_list = True
            item = _inline_format(stripped[2:].strip())
            html_parts.append(f"<li>{item}</li>")

        else:
            if in_list:
                html_parts.append("</ul>")
                in_list = False
            content = _inline_format(stripped)
            if not in_para:
                html_parts.append('<p class="mb-3">')
                in_para = True
            html_parts.append(content + " ")

    _close_blocks(html_parts, in_para, in_list)
    return "\n".join(html_parts)


def _close_blocks(
    parts: list[str], in_para: bool, in_list: bool
) -> None:
    if in_list:
        parts.append("</ul>")
    if in_para:
        parts.append("</p>")


def _inline_format(text: str) -> str:
    """Apply bold, italic, and citation marker HTML."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic (single asterisk, not already processed)
    text = re.sub(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)", r"<em>\1</em>", text)
    # Inline citation markers → styled <cite> elements
    text = _CITATION_RE.sub(
        lambda m: (
            f'<cite class="citation-marker text-indigo-600 font-medium cursor-pointer"'
            f' data-source-num="{m.group(1)}"'
            f' data-page="{m.group(2) or ""}">'
            f"[Source {m.group(1)}"
            f"{', p.' + m.group(2) if m.group(2) else ''}]</cite>"
        ),
        text,
    )
    return text
