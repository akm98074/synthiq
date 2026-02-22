"""
Smart text chunker with overlap.

Strategy
--------
1. For each page, split text on paragraph boundaries (double newline).
2. Greedily merge paragraphs into a chunk until TARGET_CHARS is reached.
3. When a single paragraph exceeds TARGET_CHARS, split it at sentence
   boundaries (". ", "! ", "? ") and then at whitespace.
4. Prepend OVERLAP_CHARS of the previous chunk to each new chunk so
   embeddings capture cross-boundary context.
5. Assign sequential chunk_index across all pages of a document.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from config import settings
from pipeline.parsers.base import PageText

# ─── Types ────────────────────────────────────────────────────────────────────


@dataclass
class TextChunk:
    content: str
    page_number: int | None
    chunk_index: int   # sequential across the whole document


# ─── Public API ───────────────────────────────────────────────────────────────


def chunk_pages(pages: list[PageText]) -> list[TextChunk]:
    """
    Convert a list of PageText objects into overlapping TextChunks.

    Parameters come from settings so they can be overridden via env vars.
    """
    target = settings.chunk_target_chars
    overlap = settings.chunk_overlap_chars

    chunks: list[TextChunk] = []
    chunk_idx = 0
    prev_tail = ""  # last `overlap` chars of previous chunk for context

    for page in pages:
        page_chunks = _split_text(
            page.text, page.page_number, target, overlap, prev_tail
        )
        for raw_content, page_num in page_chunks:
            chunks.append(
                TextChunk(
                    content=raw_content,
                    page_number=page_num,
                    chunk_index=chunk_idx,
                )
            )
            chunk_idx += 1
            prev_tail = raw_content[-overlap:] if len(raw_content) > overlap else raw_content

    return chunks


# ─── Internals ────────────────────────────────────────────────────────────────

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def _split_text(
    text: str,
    page_number: int | None,
    target: int,
    overlap: int,
    prev_tail: str,
) -> list[tuple[str, int | None]]:
    """
    Split a page's text into (content, page_number) tuples.
    Prepends prev_tail to the first chunk for overlap.
    """
    # Split into paragraphs
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    results: list[tuple[str, int | None]] = []
    current_parts: list[str] = []
    current_len = 0

    def flush(parts: list[str], first: bool) -> None:
        body = "\n\n".join(parts)
        if first and prev_tail:
            content = prev_tail.rstrip() + "\n\n" + body
        else:
            content = body
        results.append((content.strip(), page_number))

    first = True
    for para in paragraphs:
        sub_chunks = _maybe_split_paragraph(para, target)
        for sub in sub_chunks:
            if current_len + len(sub) > target and current_parts:
                flush(current_parts, first)
                first = False
                # Keep last sub_chunk as overlap seed for next flush
                tail = current_parts[-1][-overlap:] if current_parts else ""
                current_parts = [tail, sub] if tail else [sub]
                current_len = len(current_parts[0]) + len(sub)
            else:
                current_parts.append(sub)
                current_len += len(sub)

    if current_parts:
        flush(current_parts, first)

    return results


def _maybe_split_paragraph(para: str, target: int) -> list[str]:
    """
    If a paragraph exceeds target size, split it at sentence boundaries.
    Falls back to whitespace splitting for very long sentences.
    """
    if len(para) <= target:
        return [para]

    sentences = _SENTENCE_END.split(para)
    parts: list[str] = []
    current: list[str] = []
    current_len = 0

    for sent in sentences:
        if current_len + len(sent) > target and current:
            parts.append(" ".join(current))
            current = [sent]
            current_len = len(sent)
        else:
            current.append(sent)
            current_len += len(sent) + 1

    if current:
        parts.append(" ".join(current))

    # Final fallback: hard-split any remaining oversized piece
    final: list[str] = []
    for part in parts:
        if len(part) > target * 2:
            for i in range(0, len(part), target):
                final.append(part[i : i + target])
        else:
            final.append(part)

    return final
