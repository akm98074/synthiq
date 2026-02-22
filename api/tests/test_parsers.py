"""
Unit tests for document parsers.

PDF and DOCX tests generate minimal valid binary fixtures in-memory
rather than committing binary files to the repo.
URL tests use a small inline HTTP server (pytest-asyncio + httpx).
"""
from __future__ import annotations

import io

import pytest
import pytest_asyncio

from pipeline.parsers.base import PageText
from pipeline.parsers.text import parse_text


# ─── Text parser ──────────────────────────────────────────────────────────────


def test_parse_text_simple():
    content = b"Hello world.\nThis is a test."
    pages = parse_text(content)
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "Hello world" in pages[0].text


def test_parse_text_empty():
    pages = parse_text(b"")
    assert pages == []


def test_parse_text_whitespace_only():
    pages = parse_text(b"   \n\n\t  ")
    assert pages == []


def test_parse_text_large_splits_into_pages():
    """500+ lines should be split into multiple pages."""
    many_lines = "\n".join(f"Line {i}" for i in range(1200))
    pages = parse_text(many_lines.encode())
    assert len(pages) >= 2
    # Each page should have a sequential page number starting at 1
    assert pages[0].page_number == 1
    assert pages[1].page_number == 2


def test_parse_text_utf8_decoding():
    content = "Über café résumé naïve".encode("utf-8")
    pages = parse_text(content)
    assert len(pages) == 1
    assert "café" in pages[0].text


def test_parse_text_latin1_fallback():
    """Latin-1 bytes should decode with replacement rather than raising."""
    content = bytes(range(128, 256))  # non-UTF-8 bytes
    pages = parse_text(content)
    # Should not raise; may have replacement chars
    assert isinstance(pages, list)


# ─── DOCX parser ──────────────────────────────────────────────────────────────


def _make_docx(paragraphs: list[str]) -> bytes:
    """Create a minimal valid DOCX in memory."""
    from docx import Document  # type: ignore[import-untyped]

    doc = Document()
    for para in paragraphs:
        doc.add_paragraph(para)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_parse_docx_single_page():
    from pipeline.parsers.docx import parse_docx

    content = _make_docx(["First paragraph.", "Second paragraph.", "Third paragraph."])
    pages = parse_docx(content)
    assert len(pages) >= 1
    full_text = " ".join(p.text for p in pages)
    assert "First paragraph" in full_text
    assert "Second paragraph" in full_text


def test_parse_docx_empty_document():
    from pipeline.parsers.docx import parse_docx

    content = _make_docx([])
    pages = parse_docx(content)
    assert pages == []


def test_parse_docx_many_paragraphs_splits():
    from pipeline.parsers.docx import parse_docx

    # 120 paragraphs should split into at least 2 "pages" (50 per page)
    content = _make_docx([f"Paragraph {i}." for i in range(120)])
    pages = parse_docx(content)
    assert len(pages) >= 2
    page_nums = [p.page_number for p in pages]
    assert page_nums == list(range(1, len(pages) + 1))


def test_parse_docx_page_numbers_sequential():
    from pipeline.parsers.docx import parse_docx

    content = _make_docx([f"Para {i}" for i in range(200)])
    pages = parse_docx(content)
    for i, page in enumerate(pages, start=1):
        assert page.page_number == i


# ─── PDF parser ───────────────────────────────────────────────────────────────


def _make_pdf(texts: list[str]) -> bytes:
    """Create a minimal multi-page PDF in memory using PyMuPDF."""
    import fitz  # PyMuPDF

    doc = fitz.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text, fontsize=12)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def test_parse_pdf_single_page():
    from pipeline.parsers.pdf import parse_pdf

    content = _make_pdf(["Hello from page 1."])
    pages = parse_pdf(content)
    assert len(pages) == 1
    assert pages[0].page_number == 1
    assert "Hello from page 1" in pages[0].text


def test_parse_pdf_multiple_pages():
    from pipeline.parsers.pdf import parse_pdf

    texts = [f"Content on page {i}." for i in range(1, 6)]
    content = _make_pdf(texts)
    pages = parse_pdf(content)
    assert len(pages) == 5
    for i, page in enumerate(pages, start=1):
        assert page.page_number == i
        assert f"page {i}" in page.text.lower()


def test_parse_pdf_blank_pages_skipped():
    from pipeline.parsers.pdf import parse_pdf

    # Mix of blank and text pages — blank pages should not appear in output
    import fitz

    doc = fitz.open()
    doc.new_page()  # blank
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Real content here.", fontsize=12)
    doc.new_page()  # blank
    buf = io.BytesIO()
    doc.save(buf)
    content = buf.getvalue()

    pages = parse_pdf(content)
    assert len(pages) == 1
    assert "Real content" in pages[0].text


# ─── URL parser (async) ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_url_extracts_text():
    """URL parser strips boilerplate and returns article text — uses mock."""
    import httpx
    from unittest.mock import AsyncMock, MagicMock, patch

    from pipeline.parsers.url import parse_url

    html = """
    <html><body>
      <nav>Skip me</nav>
      <article>
        <h1>Market Analysis 2024</h1>
        <p>Global equity markets rose 12% in Q1.</p>
        <p>Technology sector outperformed by 400 basis points.</p>
      </article>
      <footer>Footer text</footer>
    </body></html>
    """
    # httpx Response methods (raise_for_status, .text) are synchronous
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.return_value = None
    mock_response.text = html

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        pages = await parse_url("https://example.com/article")

    assert len(pages) == 1
    full_text = pages[0].text
    assert "Market Analysis" in full_text
    assert "equity markets" in full_text


@pytest.mark.asyncio
async def test_parse_url_404_raises():
    """Non-200 responses should raise httpx.HTTPStatusError."""
    import httpx
    from unittest.mock import AsyncMock, MagicMock, patch

    from pipeline.parsers.url import parse_url

    # raise_for_status is a synchronous method in httpx — use MagicMock
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "Not Found",
        request=MagicMock(),
        response=MagicMock(),
    )

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch("httpx.AsyncClient", return_value=mock_client):
        with pytest.raises(httpx.HTTPStatusError):
            await parse_url("https://example.com/not-found")
