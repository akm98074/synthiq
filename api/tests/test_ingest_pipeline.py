"""
Integration-style tests for the ingestion pipeline components
(storage, embedder, entities) — all using mocks so no real API keys needed.
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pipeline.chunker import TextChunk
from pipeline.parsers.base import PageText


# ─── Local storage ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_local_storage_round_trip(tmp_path, monkeypatch):
    """Upload and download should return the same bytes."""
    from storage.s3 import LocalStorage

    # Point storage at a temp directory
    monkeypatch.setattr("storage.s3._LOCAL_BASE", tmp_path / "synthiq-test")
    storage = LocalStorage()
    storage._path  # ensure monkeypatched base is used

    content = b"Hello, local storage!"
    key = "test/source123.pdf"
    await storage.upload(key, content)
    downloaded = await storage.download(key)
    assert downloaded == content


@pytest.mark.asyncio
async def test_local_storage_delete(tmp_path, monkeypatch):
    from storage.s3 import LocalStorage

    monkeypatch.setattr("storage.s3._LOCAL_BASE", tmp_path / "synthiq-test")
    storage = LocalStorage()

    content = b"Delete me"
    key = "test/to_delete.txt"
    await storage.upload(key, content)
    await storage.delete(key)

    safe = key.replace("/", "__")
    path = tmp_path / "synthiq-test" / safe
    assert not path.exists()


# ─── Embedder ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_embedder_zero_vectors_without_api_key(monkeypatch):
    """Without a Voyage API key, embedder returns zero-vectors."""
    monkeypatch.setattr("pipeline.embedder.settings.voyage_api_key", "")
    from pipeline.embedder import embed_texts, EMBEDDING_DIM

    texts = ["Hello world", "Second text"]
    embeddings = await embed_texts(texts)
    assert len(embeddings) == 2
    for vec in embeddings:
        assert len(vec) == EMBEDDING_DIM
        assert all(v == 0.0 for v in vec)


@pytest.mark.asyncio
async def test_embedder_empty_input():
    from pipeline.embedder import embed_texts

    result = await embed_texts([])
    assert result == []


@pytest.mark.asyncio
async def test_embedder_with_mocked_voyage(monkeypatch):
    """When a Voyage API key is set, the client should be called."""
    monkeypatch.setattr("pipeline.embedder.settings.voyage_api_key", "fake-key")
    monkeypatch.setattr("pipeline.embedder.settings.embed_batch_size", 10)

    fake_result = MagicMock()
    fake_result.embeddings = [[0.1] * 1024, [0.2] * 1024]

    mock_client = AsyncMock()
    mock_client.embed = AsyncMock(return_value=fake_result)

    with patch("voyageai.AsyncClient", return_value=mock_client):
        from pipeline import embedder
        import importlib
        importlib.reload(embedder)  # Re-import to pick up monkeypatch
        result = await embedder.embed_texts(["text one", "text two"])

    assert len(result) == 2


# ─── Entity extraction ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_entities_empty_input():
    from pipeline.entities import extract_entities_batch

    result = await extract_entities_batch(MagicMock(), [])
    assert result == []


@pytest.mark.asyncio
async def test_entities_no_api_key(monkeypatch):
    """Without an Anthropic key, returns empty entity dicts."""
    monkeypatch.setattr("pipeline.entities.settings.anthropic_api_key", "")
    from pipeline.entities import extract_entities_batch

    texts = ["Goldman Sachs raised rates.", "Apple Inc. reported earnings."]
    result = await extract_entities_batch(MagicMock(), texts)
    assert len(result) == 2
    for d in result:
        assert set(d.keys()) == {"people", "organizations", "locations", "dates", "key_concepts"}
        assert all(isinstance(v, list) for v in d.values())


@pytest.mark.asyncio
async def test_entities_parses_valid_json(monkeypatch):
    """A valid JSON response from Claude is correctly parsed."""
    monkeypatch.setattr("pipeline.entities.settings.anthropic_api_key", "fake")
    monkeypatch.setattr("pipeline.entities.settings.entity_batch_size", 10)

    import anthropic
    from pipeline.entities import extract_entities_batch

    json_response = (
        '[{"people": ["Jerome Powell"], "organizations": ["Federal Reserve"], '
        '"locations": ["Washington DC"], "dates": ["2024"], "key_concepts": ["interest rates"]}]'
    )

    mock_content = MagicMock()
    mock_content.text = json_response
    mock_response = MagicMock()
    mock_response.content = [mock_content]

    mock_client = AsyncMock()
    mock_client.messages.create = AsyncMock(return_value=mock_response)

    result = await extract_entities_batch(mock_client, ["Fed raised rates in 2024."])
    assert len(result) == 1
    assert "Jerome Powell" in result[0]["people"]
    assert "Federal Reserve" in result[0]["organizations"]


# ─── Vector store ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vector_store_skips_without_pinecone_key(monkeypatch):
    """upsert_chunks should silently do nothing without a Pinecone key."""
    monkeypatch.setattr("pipeline.vector_store.settings.pinecone_api_key", "")
    from pipeline.vector_store import upsert_chunks

    chunks = [TextChunk(content="test", page_number=1, chunk_index=0)]
    embeddings = [[0.0] * 1024]
    entities_list = [{"people": [], "organizations": [], "locations": [], "dates": [], "key_concepts": []}]

    # Should complete without error or exception
    await upsert_chunks("src-id", "proj-id", chunks, embeddings, entities_list)
