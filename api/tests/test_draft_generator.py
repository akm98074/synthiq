"""Tests for pipeline/draft_generator.py"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pipeline.draft_generator import (
    _build_evidence_text,
    _build_source_index,
    _inline_format,
    _markdown_to_html,
    _parse_citations,
    generate_section,
    instruct_section,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

CHUNKS = [
    {
        "id": "chunk-1",
        "source_id": "src-a",
        "content": "The market grew by 30% in 2023 according to industry reports.",
        "page_number": 5,
        "filename": "market_report.pdf",
        "url": None,
    },
    {
        "id": "chunk-2",
        "source_id": "src-a",
        "content": "Competition intensified with three new entrants in Q4.",
        "page_number": 12,
        "filename": "market_report.pdf",
        "url": None,
    },
    {
        "id": "chunk-3",
        "source_id": "src-b",
        "content": "Regulatory changes will impact pricing strategies.",
        "page_number": 3,
        "filename": "regulatory_brief.pdf",
        "url": None,
    },
]

CHUNK_MAP = {c["id"]: c for c in CHUNKS}

SECTION = {
    "id": "s1",
    "title": "Market Overview",
    "description": "Analysis of market size and growth.",
    "suggested_length": 300,
    "chunk_ids": ["chunk-1", "chunk-2", "chunk-3"],
    "source_ids": ["src-a", "src-b"],
    "subsections": [],
}


# ─── _build_source_index ──────────────────────────────────────────────────────


def test_build_source_index_assigns_numbers():
    index_text, source_num_map, source_labels = _build_source_index(CHUNKS)
    assert "src-a" in source_num_map
    assert "src-b" in source_num_map
    # Both sources should be numbered 1-based
    assert source_num_map["src-a"] == 1
    assert source_num_map["src-b"] == 2


def test_build_source_index_uses_filename():
    _, _, labels = _build_source_index(CHUNKS)
    assert labels["src-a"] == "market_report.pdf"
    assert labels["src-b"] == "regulatory_brief.pdf"


def test_build_source_index_deduplicates():
    _, source_num_map, _ = _build_source_index(CHUNKS)
    # src-a appears twice in CHUNKS but should be numbered once
    assert source_num_map["src-a"] == 1


def test_build_source_index_empty():
    index_text, source_num_map, source_labels = _build_source_index([])
    assert index_text == ""
    assert source_num_map == {}
    assert source_labels == {}


# ─── _build_evidence_text ─────────────────────────────────────────────────────


def test_build_evidence_text_includes_content():
    text = _build_evidence_text(CHUNKS)
    assert "30% in 2023" in text
    assert "Competition intensified" in text


def test_build_evidence_text_includes_page_numbers():
    text = _build_evidence_text(CHUNKS)
    assert "p.5" in text


def test_build_evidence_text_empty():
    text = _build_evidence_text([])
    assert "No specific evidence" in text


# ─── _parse_citations ─────────────────────────────────────────────────────────


def test_parse_citations_finds_basic():
    _, source_num_map, source_labels = _build_source_index(CHUNKS)
    content = "Market grew significantly [Source 1] in recent years."
    citations = _parse_citations(content, source_num_map, source_labels, CHUNKS)
    assert len(citations) == 1
    assert citations[0]["source_id"] == "src-a"
    assert citations[0]["page"] is None


def test_parse_citations_finds_with_page():
    _, source_num_map, source_labels = _build_source_index(CHUNKS)
    content = "Strong growth [Source 1, p.5] was reported."
    citations = _parse_citations(content, source_num_map, source_labels, CHUNKS)
    assert len(citations) == 1
    assert citations[0]["page"] == 5
    assert citations[0]["marker"] == "Source 1, p.5"


def test_parse_citations_deduplicates():
    _, source_num_map, source_labels = _build_source_index(CHUNKS)
    content = "[Source 1] and also [Source 1] and [Source 1, p.5]"
    citations = _parse_citations(content, source_num_map, source_labels, CHUNKS)
    # (1, None) and (1, 5) are distinct
    assert len(citations) == 2


def test_parse_citations_multiple_sources():
    _, source_num_map, source_labels = _build_source_index(CHUNKS)
    content = "Data from [Source 1] and regulations from [Source 2, p.3]."
    citations = _parse_citations(content, source_num_map, source_labels, CHUNKS)
    assert len(citations) == 2
    source_ids = {c["source_id"] for c in citations}
    assert "src-a" in source_ids
    assert "src-b" in source_ids


# ─── _markdown_to_html ────────────────────────────────────────────────────────


def test_markdown_to_html_paragraph():
    html = _markdown_to_html("Simple paragraph text.")
    assert "<p" in html
    assert "Simple paragraph text." in html


def test_markdown_to_html_h2():
    html = _markdown_to_html("## Section Title\nBody text.")
    assert "<h4" in html
    assert "Section Title" in html


def test_markdown_to_html_bullet_list():
    html = _markdown_to_html("- Item one\n- Item two")
    assert "<ul" in html
    assert "<li>" in html
    assert "Item one" in html


def test_markdown_to_html_empty_lines_close_paragraph():
    html = _markdown_to_html("Para one.\n\nPara two.")
    assert html.count("<p") == 2


# ─── _inline_format ───────────────────────────────────────────────────────────


def test_inline_format_bold():
    result = _inline_format("**important**")
    assert "<strong>important</strong>" in result


def test_inline_format_citation_marker():
    result = _inline_format("[Source 3, p.7]")
    assert "citation-marker" in result
    assert 'data-source-num="3"' in result
    assert 'data-page="7"' in result


def test_inline_format_citation_no_page():
    result = _inline_format("[Source 1]")
    assert "citation-marker" in result
    assert 'data-page=""' in result


# ─── generate_section — no client ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_section_no_client():
    result = await generate_section(
        client=None,
        section=SECTION,
        chunk_map=CHUNK_MAP,
        deliverable_type="executive_memo",
    )
    assert result["id"] == "s1"
    assert result["title"] == "Market Overview"
    assert "<em>" in result["content"]  # placeholder has em tag


# ─── generate_section — happy path ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_section_happy_path():
    content = "The market showed strong growth [Source 1, p.5] in recent years."

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=content)]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await generate_section(
        client=mock_client,
        section=SECTION,
        chunk_map=CHUNK_MAP,
        deliverable_type="executive_memo",
    )

    assert result["status"] == "done"
    assert "citation-marker" in result["content"]
    assert len(result["citations"]) >= 1
    assert result["citations"][0]["source_id"] == "src-a"


@pytest.mark.asyncio
async def test_generate_section_with_voice_prompt():
    content = "Concise market analysis [Source 1]."

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=content)]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await generate_section(
        client=mock_client,
        section=SECTION,
        chunk_map=CHUNK_MAP,
        deliverable_type="executive_memo",
        voice_system_prompt="Use formal, concise language.",
    )

    assert result["status"] == "done"
    # Verify that voice prompt was included in the API call
    call_args = mock_client.messages.create.call_args
    prompt_text = call_args.kwargs["messages"][0]["content"]
    assert "formal, concise" in prompt_text


@pytest.mark.asyncio
async def test_generate_section_handles_api_error():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("Rate limit"))

    result = await generate_section(
        client=mock_client,
        section=SECTION,
        chunk_map=CHUNK_MAP,
        deliverable_type="executive_memo",
    )

    assert result["status"] == "error"
    assert "Rate limit" in result["content"]


# ─── instruct_section ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_instruct_section_no_client():
    section_with_content = {**SECTION, "content": "<p>Original content.</p>"}
    result = await instruct_section(
        client=None,
        section=section_with_content,
        instruction="Make it more formal",
        chunk_map=CHUNK_MAP,
        deliverable_type="executive_memo",
    )
    assert "Make it more formal" in result["content"]
    assert "Original content" in result["content"]


@pytest.mark.asyncio
async def test_instruct_section_happy_path():
    revised = "More formal market analysis [Source 1]."

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=revised)]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    section_with_content = {**SECTION, "content": "<p>Original content.</p>"}
    result = await instruct_section(
        client=mock_client,
        section=section_with_content,
        instruction="Make it more formal",
        chunk_map=CHUNK_MAP,
        deliverable_type="executive_memo",
    )

    assert result["status"] == "done"
    assert len(result["citations"]) >= 1

    # Instruction should appear in the API call
    call_args = mock_client.messages.create.call_args
    prompt_text = call_args.kwargs["messages"][0]["content"]
    assert "Make it more formal" in prompt_text
