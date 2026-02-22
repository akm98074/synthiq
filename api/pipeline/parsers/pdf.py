"""
PDF parser using PyMuPDF (fitz).

Extracts text page-by-page, preserving page numbers so the chunker and
citation system can reference exact source locations.
"""
from __future__ import annotations

import fitz  # PyMuPDF

from .base import PageText


def parse_pdf(content: bytes) -> list[PageText]:
    """
    Parse a PDF from raw bytes.

    Returns one PageText per PDF page (skipping blank pages).
    """
    pages: list[PageText] = []

    with fitz.open(stream=content, filetype="pdf") as doc:
        for page_num, page in enumerate(doc, start=1):
            text = page.get_text("text").strip()  # type: ignore[attr-defined]
            if text:
                pages.append(PageText(page_number=page_num, text=text))

    return pages
