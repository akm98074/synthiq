"""
Plain-text parser.

Reads UTF-8 text and groups lines into synthetic "pages" so the pipeline
treats large text files consistently.
"""
from __future__ import annotations

from .base import PageText

_LINES_PER_PAGE = 500


def parse_text(content: bytes) -> list[PageText]:
    """
    Parse raw text bytes into pages.

    Returns one PageText per 500 lines; always returns at least one page
    even for very short documents.
    """
    text = content.decode("utf-8", errors="replace").strip()

    if not text:
        return []

    lines = text.splitlines()

    if len(lines) <= _LINES_PER_PAGE:
        return [PageText(page_number=1, text=text)]

    pages: list[PageText] = []
    for i in range(0, len(lines), _LINES_PER_PAGE):
        group = "\n".join(lines[i : i + _LINES_PER_PAGE]).strip()
        if group:
            pages.append(
                PageText(page_number=i // _LINES_PER_PAGE + 1, text=group)
            )

    return pages
