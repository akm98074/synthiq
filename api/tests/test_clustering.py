"""
Unit tests for pipeline/clustering.py and pipeline/confidence.py.

No external services required — clustering uses synthetic embeddings,
and Claude Haiku calls are fully mocked.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


# ─── Confidence scoring ───────────────────────────────────────────────────────


def test_confidence_pdf_no_entities():
    from pipeline.confidence import compute_confidence

    score = compute_confidence("pdf", [])
    # domain_score=0.9, specificity=0.0 → 0.6*0.9 + 0.4*0.0 = 0.54
    assert score == pytest.approx(0.54, abs=1e-4)


def test_confidence_url_high_entities():
    from pipeline.confidence import compute_confidence

    # 5 entities per chunk × 4 chunks → density=5.0 → specificity=1.0
    entities = [{"people": ["A"], "organizations": ["B"], "locations": ["C"], "dates": ["D"], "key_concepts": ["E"]}] * 4
    score = compute_confidence("url", entities)
    # 0.6*0.70 + 0.4*1.0 = 0.42 + 0.40 = 0.82
    assert score == pytest.approx(0.82, abs=1e-4)


def test_confidence_text_partial_entities():
    from pipeline.confidence import compute_confidence

    # 2 entities per chunk → density=2.0 → specificity = 2/5 = 0.4
    entities = [{"people": ["A", "B"], "organizations": [], "locations": [], "dates": [], "key_concepts": []}] * 3
    score = compute_confidence("text", entities)
    # 0.6*0.65 + 0.4*0.4 = 0.39 + 0.16 = 0.55
    assert score == pytest.approx(0.55, abs=1e-4)


def test_confidence_unknown_type():
    from pipeline.confidence import compute_confidence

    score = compute_confidence("csv", [])
    # domain_score=0.60 (fallback), specificity=0.0 → 0.36
    assert score == pytest.approx(0.36, abs=1e-4)


def test_confidence_capped_at_one():
    from pipeline.confidence import compute_confidence

    # Very dense entities — must not exceed 1.0
    entities = [
        {
            "people": ["A"] * 5,
            "organizations": ["B"] * 5,
            "locations": ["C"] * 5,
            "dates": ["D"] * 5,
            "key_concepts": ["E"] * 5,
        }
    ] * 10
    score = compute_confidence("pdf", entities)
    assert score <= 1.0


# ─── Entity graph ─────────────────────────────────────────────────────────────


def test_entity_graph_single_source_excluded():
    """Entities that only appear in one source should be excluded."""
    from pipeline.clustering import build_entity_graph

    chunks = [
        {
            "source_id": "src-1",
            "content": "Apple is growing.",
            "entities": {"organizations": ["Apple"], "people": [], "locations": [], "dates": [], "key_concepts": []},
        }
    ]
    graph = build_entity_graph(chunks)
    assert "apple" not in graph


def test_entity_graph_cross_source_included():
    """Entity appearing in ≥2 sources must be in the graph."""
    from pipeline.clustering import build_entity_graph

    chunks = [
        {
            "source_id": "src-1",
            "content": "Fed raises rates.",
            "entities": {"organizations": ["Federal Reserve"], "people": [], "locations": [], "dates": [], "key_concepts": []},
        },
        {
            "source_id": "src-2",
            "content": "Fed keeps rates stable.",
            "entities": {"organizations": ["Federal Reserve"], "people": [], "locations": [], "dates": [], "key_concepts": []},
        },
    ]
    graph = build_entity_graph(chunks)
    assert "federal reserve" in graph
    data = graph["federal reserve"]
    assert set(data["source_ids"]) == {"src-1", "src-2"}
    assert data["mention_count"] == 2


def test_entity_graph_snippets_capped():
    """Snippets per entity must be capped at 5."""
    from pipeline.clustering import build_entity_graph

    chunks = [
        {
            "source_id": f"src-{i}",
            "content": f"Content {i}",
            "entities": {"people": ["Jane Doe"], "organizations": [], "locations": [], "dates": [], "key_concepts": []},
        }
        for i in range(10)
    ]
    graph = build_entity_graph(chunks)
    assert "jane doe" in graph
    assert len(graph["jane doe"]["snippets"]) <= 5


def test_entity_graph_normalises_case():
    """Entity keys are lowercased for grouping."""
    from pipeline.clustering import build_entity_graph

    chunks = [
        {
            "source_id": "s1",
            "content": "Apple Inc.",
            "entities": {"organizations": ["Apple Inc."], "people": [], "locations": [], "dates": [], "key_concepts": []},
        },
        {
            "source_id": "s2",
            "content": "APPLE INC. reported earnings.",
            "entities": {"organizations": ["APPLE INC."], "people": [], "locations": [], "dates": [], "key_concepts": []},
        },
    ]
    graph = build_entity_graph(chunks)
    assert "apple inc." in graph


# ─── cluster_chunks ───────────────────────────────────────────────────────────


def test_cluster_chunks_too_few_returns_zeros():
    """Fewer than 4 chunks → single cluster (all zeros)."""
    from pipeline.clustering import cluster_chunks
    import numpy as np

    chunks = [{"source_id": "s1", "content": "x", "entities": {}}] * 3
    embeddings = [[0.1] * 8] * 3
    labels, k = cluster_chunks(chunks, embeddings)
    assert k == 1
    assert list(labels) == [0, 0, 0]


def test_cluster_chunks_distinct_groups():
    """Well-separated embeddings should cluster into ≥2 groups."""
    from pipeline.clustering import cluster_chunks
    import numpy as np

    # Two tight groups in 4-d space
    group_a = [[1.0, 0.0, 0.0, 0.0]] * 5
    group_b = [[0.0, 1.0, 0.0, 0.0]] * 5
    embeddings = group_a + group_b
    chunks = [{"source_id": f"s{i}", "content": "x", "entities": {}} for i in range(10)]
    labels, k = cluster_chunks(chunks, embeddings)
    assert k >= 2
    # First 5 should share one label; second 5 another
    assert len(set(labels[:5])) == 1
    assert len(set(labels[5:])) == 1
    assert labels[0] != labels[5]


# ─── build_clusters (mocked Claude) ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_clusters_empty_input():
    from pipeline.clustering import build_clusters

    result = await build_clusters(MagicMock(), [], [])
    assert result == []


@pytest.mark.asyncio
async def test_build_clusters_returns_labels(monkeypatch):
    """build_clusters returns correctly shaped cluster dicts."""
    from pipeline.clustering import build_clusters

    # Mock label_clusters to avoid real API call
    async def fake_label(client, entities_list):
        return [f"Label {i}" for i in range(len(entities_list))]

    monkeypatch.setattr("pipeline.clustering.label_clusters", fake_label)

    chunks = [
        {"source_id": f"s{i % 2}", "content": "text", "entities": {"people": ["Alice"], "organizations": [], "locations": [], "dates": [], "key_concepts": []}}
        for i in range(10)
    ]
    # Two-group embeddings
    embeddings = [[1.0, 0.0]] * 5 + [[0.0, 1.0]] * 5

    clusters = await build_clusters(MagicMock(), chunks, embeddings)
    assert len(clusters) >= 1
    for c in clusters:
        assert "id" in c
        assert "label" in c
        assert "source_count" in c
        assert "chunk_count" in c
        assert isinstance(c["source_ids"], list)


@pytest.mark.asyncio
async def test_label_clusters_no_api_key(monkeypatch):
    """Without API key, label_clusters returns generic fallback labels."""
    monkeypatch.setattr("pipeline.clustering.settings" if False else "config.settings", type("S", (), {"anthropic_api_key": "", "anthropic_model": "x"})(), raising=False)

    from pipeline.clustering import label_clusters

    # Monkeypatch settings inside the module
    import config
    original_key = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = ""
    try:
        labels = await label_clusters(MagicMock(), [["entity1", "entity2"], []])
        assert len(labels) == 2
        assert all(isinstance(l, str) for l in labels)
    finally:
        config.settings.anthropic_api_key = original_key


@pytest.mark.asyncio
async def test_label_clusters_with_mock_client():
    """With a mocked client, labels come from the API response."""
    from pipeline.clustering import label_clusters
    import config

    mock_content = MagicMock()
    mock_content.text = "Interest Rates Policy"
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    original_key = config.settings.anthropic_api_key
    config.settings.anthropic_api_key = "fake-key"
    try:
        labels = await label_clusters(mock_client, [["federal reserve", "inflation"]])
        assert labels == ["Interest Rates Policy"]
    finally:
        config.settings.anthropic_api_key = original_key
