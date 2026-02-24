"""Tests for pipeline/outline_generator.py"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.outline_generator import (
    _build_fallback,
    _summarise_clusters,
    _summarise_contradictions,
    _summarise_gaps,
    _summarise_evidence,
    generate_outline,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────────

SAMPLE_CHUNKS = [
    {
        "id": f"chunk-{i}",
        "source_id": f"src-{i % 3}",
        "content": f"Content of chunk {i} with relevant information.",
        "page_number": i + 1,
        "entities": {"entities": [f"Entity{i}"]},
        "filename": f"doc_{i % 3}.pdf",
        "url": None,
    }
    for i in range(9)
]

SAMPLE_SOURCE_MAP = {
    "clusters": [
        {"id": "c1", "label": "Market Analysis", "chunk_count": 5, "source_ids": ["src-0"]},
        {"id": "c2", "label": "Competitive Intel", "chunk_count": 3, "source_ids": ["src-1"]},
    ],
    "contradictions": [
        {
            "id": "con1",
            "entity": "MarketSize",
            "claim": "differs",
            "source_a": "doc_0.pdf",
            "source_b": "doc_1.pdf",
        }
    ],
    "gaps": [
        {"topic": "Pricing Strategy", "mentioned_in_count": 2, "missing_in_count": 1}
    ],
}


# ─── _summarise_clusters ──────────────────────────────────────────────────────


def test_summarise_clusters_normal():
    summary = _summarise_clusters(SAMPLE_SOURCE_MAP)
    assert "Market Analysis" in summary
    assert "5 chunks" in summary
    assert "Competitive Intel" in summary


def test_summarise_clusters_empty():
    summary = _summarise_clusters({})
    assert summary == "No clusters available"


def test_summarise_clusters_capped_at_six():
    sm = {
        "clusters": [
            {"id": f"c{i}", "label": f"Cluster {i}", "chunk_count": i, "source_ids": []}
            for i in range(10)
        ]
    }
    summary = _summarise_clusters(sm)
    # Should only include first 6
    assert "Cluster 6" not in summary


# ─── _summarise_contradictions ────────────────────────────────────────────────


def test_summarise_contradictions_normal():
    summary = _summarise_contradictions(SAMPLE_SOURCE_MAP)
    assert "MarketSize" in summary
    assert "doc_0.pdf" in summary


def test_summarise_contradictions_empty():
    summary = _summarise_contradictions({"contradictions": []})
    assert summary == "None detected"


# ─── _summarise_gaps ──────────────────────────────────────────────────────────


def test_summarise_gaps_normal():
    summary = _summarise_gaps(SAMPLE_SOURCE_MAP)
    assert "Pricing Strategy" in summary


def test_summarise_gaps_empty():
    summary = _summarise_gaps({})
    assert summary == "None detected"


# ─── _build_fallback ──────────────────────────────────────────────────────────


def test_build_fallback_no_chunks():
    outline = _build_fallback([])
    assert "sections" in outline
    assert len(outline["sections"]) == 4
    # With no chunks, first section has none
    assert outline["sections"][0]["chunk_ids"] == []


def test_build_fallback_distributes_chunks():
    outline = _build_fallback(SAMPLE_CHUNKS)
    # All sections except executive summary should get some chunks
    distributable = outline["sections"][1:]
    total_assigned = sum(len(s["chunk_ids"]) for s in distributable)
    assert total_assigned > 0


def test_build_fallback_source_ids_consistent():
    outline = _build_fallback(SAMPLE_CHUNKS)
    chunk_id_set = {c["id"] for c in SAMPLE_CHUNKS}
    for section in outline["sections"]:
        for cid in section["chunk_ids"]:
            assert cid in chunk_id_set


# ─── generate_outline — no client ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_outline_no_client():
    outline = await generate_outline(
        client=None,
        deliverable_type="executive_memo",
        source_map=SAMPLE_SOURCE_MAP,
        entity_graph={},
        chunk_rows=SAMPLE_CHUNKS,
    )
    assert "sections" in outline
    assert len(outline["sections"]) >= 1


# ─── generate_outline — happy path ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_generate_outline_happy_path():
    mock_outline = {
        "title": "Investment Analysis",
        "sections": [
            {
                "id": "s1",
                "title": "Executive Summary",
                "description": "Overview",
                "suggested_length": 200,
                "chunk_ids": ["chunk-0"],
                "source_ids": ["src-0"],
                "subsections": [],
            },
            {
                "id": "s2",
                "title": "Market Analysis",
                "description": "Deep dive",
                "suggested_length": 500,
                "chunk_ids": ["chunk-1", "chunk-2"],
                "source_ids": ["src-1"],
                "subsections": [],
            },
        ],
    }

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=json.dumps(mock_outline))]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    outline = await generate_outline(
        client=mock_client,
        deliverable_type="investment_thesis",
        source_map=SAMPLE_SOURCE_MAP,
        entity_graph={},
        chunk_rows=SAMPLE_CHUNKS,
    )

    assert outline["title"] == "Investment Analysis"
    assert len(outline["sections"]) == 2
    assert outline["sections"][0]["id"] == "s1"


@pytest.mark.asyncio
async def test_generate_outline_strips_markdown_fences():
    mock_outline = {"title": "Test", "sections": []}
    raw = f"```json\n{json.dumps(mock_outline)}\n```"

    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=raw)]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    outline = await generate_outline(
        client=mock_client,
        deliverable_type="executive_memo",
        source_map={},
        entity_graph={},
        chunk_rows=[],
    )
    assert outline["title"] == "Test"


@pytest.mark.asyncio
async def test_generate_outline_falls_back_on_invalid_json():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="not valid json at all")]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    outline = await generate_outline(
        client=mock_client,
        deliverable_type="executive_memo",
        source_map={},
        entity_graph={},
        chunk_rows=SAMPLE_CHUNKS,
    )
    # Should return fallback
    assert "sections" in outline
    assert len(outline["sections"]) == 4


@pytest.mark.asyncio
async def test_generate_outline_falls_back_on_missing_sections():
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text='{"title": "T", "wrong_key": []}')]
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    outline = await generate_outline(
        client=mock_client,
        deliverable_type="executive_memo",
        source_map={},
        entity_graph={},
        chunk_rows=[],
    )
    assert "sections" in outline


@pytest.mark.asyncio
async def test_generate_outline_falls_back_on_api_error():
    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))

    outline = await generate_outline(
        client=mock_client,
        deliverable_type="executive_memo",
        source_map=SAMPLE_SOURCE_MAP,
        entity_graph={},
        chunk_rows=SAMPLE_CHUNKS,
    )
    assert "sections" in outline
