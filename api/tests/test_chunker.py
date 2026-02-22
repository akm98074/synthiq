"""
Unit tests for pipeline/chunker.py

Tests do not require any external services (no DB, no API calls).
"""
import pytest

from pipeline.chunker import TextChunk, chunk_pages, _maybe_split_paragraph
from pipeline.parsers.base import PageText


# ─── chunk_pages ──────────────────────────────────────────────────────────────


def test_chunk_pages_empty():
    """Empty input returns empty output."""
    assert chunk_pages([]) == []


def test_chunk_pages_single_short_page(short_text):
    """A short single page becomes exactly one chunk."""
    pages = [PageText(page_number=1, text=short_text)]
    chunks = chunk_pages(pages)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0
    assert chunks[0].page_number == 1
    assert short_text in chunks[0].content


def test_chunk_pages_preserves_page_numbers():
    """Each chunk must carry the page number of the page it came from."""
    pages = [
        PageText(page_number=1, text="Page one content " * 50),
        PageText(page_number=2, text="Page two content " * 50),
        PageText(page_number=3, text="Page three content " * 50),
    ]
    chunks = chunk_pages(pages)
    # Every chunk must have a valid page_number
    page_nums = {c.page_number for c in chunks}
    assert page_nums.issubset({1, 2, 3})


def test_chunk_pages_sequential_indices():
    """chunk_index must be 0-based and sequential across pages."""
    pages = [
        PageText(page_number=i, text="Some content sentence. " * 30)
        for i in range(1, 4)
    ]
    chunks = chunk_pages(pages)
    indices = [c.chunk_index for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_pages_long_text_splits(long_text):
    """A text exceeding TARGET_CHARS must produce multiple chunks."""
    pages = [PageText(page_number=1, text=long_text)]
    chunks = chunk_pages(pages)
    assert len(chunks) > 1, "Long text should produce more than one chunk"


def test_chunk_pages_no_empty_chunks(multi_paragraph_text):
    """No chunk should have empty or whitespace-only content."""
    pages = [PageText(page_number=1, text=multi_paragraph_text)]
    chunks = chunk_pages(pages)
    for chunk in chunks:
        assert chunk.content.strip(), f"Empty chunk at index {chunk.chunk_index}"


def test_chunk_pages_overlap_present(long_text):
    """
    Consecutive chunks should share content from the tail/head boundary,
    confirming overlap is applied.
    """
    from config import settings
    pages = [PageText(page_number=1, text=long_text)]
    chunks = chunk_pages(pages)

    if len(chunks) < 2:
        pytest.skip("Need at least 2 chunks to test overlap")

    tail_of_first = chunks[0].content[-settings.chunk_overlap_chars:]
    head_of_second = chunks[1].content[: settings.chunk_overlap_chars * 2]
    # Some portion of the first chunk's tail must appear at the start of the second
    assert any(
        word in head_of_second
        for word in tail_of_first.split()[-10:]
        if len(word) > 4
    ), "No overlap detected between consecutive chunks"


def test_chunk_pages_content_coverage(multi_paragraph_text):
    """
    The union of all chunk contents should contain every distinct word
    from the original text (information preservation).
    """
    pages = [PageText(page_number=1, text=multi_paragraph_text)]
    chunks = chunk_pages(pages)

    all_chunk_text = " ".join(c.content for c in chunks).lower()
    original_words = set(multi_paragraph_text.lower().split())
    missing = [w for w in original_words if w not in all_chunk_text]
    assert not missing, f"Words missing from chunks: {missing[:10]}"


# ─── _maybe_split_paragraph ───────────────────────────────────────────────────


def test_split_paragraph_short_unchanged():
    """Short paragraphs are returned unchanged."""
    para = "Short sentence."
    result = _maybe_split_paragraph(para, target=2000)
    assert result == [para]


def test_split_paragraph_long_produces_multiple():
    """A paragraph longer than target produces multiple parts."""
    para = ("Word " * 500).strip()
    result = _maybe_split_paragraph(para, target=200)
    assert len(result) > 1


def test_split_paragraph_parts_non_empty():
    """No part should be empty."""
    para = ("This is a sentence. " * 200).strip()
    result = _maybe_split_paragraph(para, target=300)
    for part in result:
        assert part.strip()


def test_split_paragraph_content_preserved():
    """All words from the original paragraph appear in the splits."""
    para = "The quick brown fox jumps over the lazy dog. " * 200
    result = _maybe_split_paragraph(para, target=400)
    combined = " ".join(result)
    assert "quick brown fox" in combined
    assert "lazy dog" in combined
