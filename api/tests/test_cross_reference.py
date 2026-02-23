"""
Unit tests for pipeline/cross_reference.py.

All Claude API calls are mocked so no real key is needed.
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock


# ─── Gap detection ────────────────────────────────────────────────────────────


def test_gap_detection_empty():
    from pipeline.cross_reference import detect_gaps

    result = detect_gaps({}, [])
    assert result == []


def test_gap_detection_single_source():
    """Need ≥2 sources for gaps."""
    from pipeline.cross_reference import detect_gaps

    graph = {
        "inflation": {"source_ids": ["s1"], "mention_count": 1, "snippets": []}
    }
    result = detect_gaps(graph, ["s1"])
    assert result == []


def test_gap_detection_entity_in_all_sources_not_a_gap():
    """Entity present in 100% of sources is not a gap."""
    from pipeline.cross_reference import detect_gaps

    graph = {
        "federal reserve": {
            "source_ids": ["s1", "s2", "s3"],
            "mention_count": 3,
            "snippets": [],
        }
    }
    result = detect_gaps(graph, ["s1", "s2", "s3"])
    assert result == []


def test_gap_detection_threshold():
    """Entity in 2/3 sources (66%) with 1 missing → gap."""
    from pipeline.cross_reference import detect_gaps

    graph = {
        "interest rates": {
            "source_ids": ["s1", "s2"],
            "mention_count": 2,
            "snippets": [],
        }
    }
    result = detect_gaps(graph, ["s1", "s2", "s3"])
    assert len(result) == 1
    gap = result[0]
    assert gap["topic"] == "interest rates"
    assert gap["mentioned_in_count"] == 2
    assert gap["missing_in_count"] == 1
    assert "s3" in gap["missing_source_ids"]


def test_gap_detection_below_threshold():
    """Entity in 1/3 sources (33%) — below 60% threshold → not a gap."""
    from pipeline.cross_reference import detect_gaps

    graph = {
        "cryptocurrency": {
            "source_ids": ["s1"],
            "mention_count": 1,
            "snippets": [],
        }
    }
    result = detect_gaps(graph, ["s1", "s2", "s3"])
    assert result == []


def test_gap_detection_sorted_by_count():
    """Gaps are returned sorted by mentioned_in_count descending."""
    from pipeline.cross_reference import detect_gaps

    # 5 sources total
    sources = [f"s{i}" for i in range(5)]
    graph = {
        "inflation": {
            "source_ids": ["s0", "s1", "s2", "s3"],   # 4/5 = 80% → gap
            "mention_count": 4,
            "snippets": [],
        },
        "gdp": {
            "source_ids": ["s0", "s1", "s2"],           # 3/5 = 60% → gap
            "mention_count": 3,
            "snippets": [],
        },
    }
    result = detect_gaps(graph, sources)
    assert len(result) == 2
    assert result[0]["mentioned_in_count"] >= result[1]["mentioned_in_count"]


# ─── Contradiction detection ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_contradictions_no_api_key(monkeypatch):
    """Without API key returns empty list."""
    import config
    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = ""
    try:
        from pipeline.cross_reference import detect_contradictions

        graph = {
            "federal reserve": {
                "source_ids": ["s1", "s2"],
                "snippets": [
                    {"source_id": "s1", "text": "Fed raised rates."},
                    {"source_id": "s2", "text": "Fed cut rates."},
                ],
            }
        }
        result = await detect_contradictions(MagicMock(), graph, {"s1": "Source A", "s2": "Source B"})
        assert result == []
    finally:
        config.settings.anthropic_api_key = original


@pytest.mark.asyncio
async def test_contradictions_valid_response():
    """A valid Claude response is parsed into contradiction dicts."""
    import config

    json_payload = json.dumps([
        {
            "claim": "Fed raised vs cut rates",
            "source_a_idx": 0,
            "source_b_idx": 1,
            "quote_a": "The Fed raised rates by 50bps.",
            "quote_b": "The Fed cut rates by 25bps.",
            "significance": 0.9,
        }
    ])

    mock_content = MagicMock()
    mock_content.text = json_payload
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = "fake-key"
    try:
        from pipeline.cross_reference import detect_contradictions

        graph = {
            "federal reserve": {
                "source_ids": ["s1", "s2"],
                "snippets": [
                    {"source_id": "s1", "text": "Fed raised rates."},
                    {"source_id": "s2", "text": "Fed cut rates."},
                ],
            }
        }
        result = await detect_contradictions(mock_client, graph, {"s1": "Source A", "s2": "Source B"})
        assert len(result) == 1
        c = result[0]
        assert c["entity"] == "federal reserve"
        assert "id" in c
        assert c["source_a_id"] == "s1"
        assert c["source_b_id"] == "s2"
        assert c["significance"] == pytest.approx(0.9)
    finally:
        config.settings.anthropic_api_key = original


@pytest.mark.asyncio
async def test_contradictions_invalid_json_skipped():
    """If Claude returns invalid JSON, no crash — returns empty."""
    import config

    mock_content = MagicMock()
    mock_content.text = "This is not JSON at all!"
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = "fake-key"
    try:
        from pipeline.cross_reference import detect_contradictions

        graph = {
            "inflation": {
                "source_ids": ["s1", "s2"],
                "snippets": [
                    {"source_id": "s1", "text": "High inflation."},
                    {"source_id": "s2", "text": "Low inflation."},
                ],
            }
        }
        result = await detect_contradictions(mock_client, graph, {"s1": "A", "s2": "B"})
        assert result == []
    finally:
        config.settings.anthropic_api_key = original


@pytest.mark.asyncio
async def test_contradictions_single_source_skipped():
    """Entity with only one source cannot have contradictions."""
    import config

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock()

    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = "fake-key"
    try:
        from pipeline.cross_reference import detect_contradictions

        graph = {
            "unicorn": {
                "source_ids": ["s1"],
                "snippets": [{"source_id": "s1", "text": "Unicorns are real."}],
            }
        }
        result = await detect_contradictions(mock_client, graph, {"s1": "Source A"})
        assert result == []
        # No API call should have been made
        mock_client.messages.create.assert_not_called()
    finally:
        config.settings.anthropic_api_key = original


@pytest.mark.asyncio
async def test_contradictions_empty_response():
    """Claude returning [] (no contradictions) is handled correctly."""
    import config

    mock_content = MagicMock()
    mock_content.text = "[]"
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = "fake-key"
    try:
        from pipeline.cross_reference import detect_contradictions

        graph = {
            "gdp": {
                "source_ids": ["s1", "s2"],
                "snippets": [
                    {"source_id": "s1", "text": "GDP grew 3%."},
                    {"source_id": "s2", "text": "GDP grew 3%."},
                ],
            }
        }
        result = await detect_contradictions(mock_client, graph, {"s1": "A", "s2": "B"})
        assert result == []
    finally:
        config.settings.anthropic_api_key = original


@pytest.mark.asyncio
async def test_contradictions_sorted_by_significance():
    """Multiple contradictions are sorted by significance descending."""
    import config

    json_payload = json.dumps([
        {
            "claim": "Minor conflict",
            "source_a_idx": 0,
            "source_b_idx": 1,
            "quote_a": "quote a1",
            "quote_b": "quote b1",
            "significance": 0.3,
        },
        {
            "claim": "Major conflict",
            "source_a_idx": 0,
            "source_b_idx": 1,
            "quote_a": "quote a2",
            "quote_b": "quote b2",
            "significance": 0.9,
        },
    ])

    mock_content = MagicMock()
    mock_content.text = json_payload
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    original = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = "fake-key"
    try:
        from pipeline.cross_reference import detect_contradictions

        graph = {
            "rates": {
                "source_ids": ["s1", "s2"],
                "snippets": [
                    {"source_id": "s1", "text": "Rates rose."},
                    {"source_id": "s2", "text": "Rates fell."},
                ],
            }
        }
        result = await detect_contradictions(mock_client, graph, {"s1": "A", "s2": "B"})
        assert len(result) == 2
        assert result[0]["significance"] >= result[1]["significance"]
    finally:
        config.settings.anthropic_api_key = original
