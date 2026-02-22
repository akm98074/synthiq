"""
Pinecone vector store wrapper.

Provides upsert and delete operations. When PINECONE_API_KEY is not set,
operations are silently skipped so local development works without a
Pinecone account.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from config import settings
from pipeline.chunker import TextChunk

log = logging.getLogger(__name__)

_METADATA_CONTENT_MAX = 900  # Pinecone metadata string limit is 1 KB


def _get_index():
    """Lazily create and return the Pinecone index client."""
    if not settings.pinecone_api_key:
        return None
    from pinecone import Pinecone  # type: ignore[import-untyped]

    pc = Pinecone(api_key=settings.pinecone_api_key)
    return pc.Index(settings.pinecone_index_name)


async def upsert_chunks(
    source_id: str,
    project_id: str,
    chunks: list[TextChunk],
    embeddings: list[list[float]],
    entities_list: list[dict[str, list[str]]],
) -> None:
    """
    Upsert chunk vectors to Pinecone under namespace `project_{project_id}`.

    Vector IDs are `{source_id}_{chunk_index}` so they can be deleted by source.
    """
    if not chunks:
        return

    index = _get_index()
    if index is None:
        log.debug("No PINECONE_API_KEY — skipping vector upsert (dev mode)")
        return

    namespace = f"project_{project_id}"
    vectors: list[dict[str, Any]] = []

    for chunk, embedding, entities in zip(chunks, embeddings, entities_list):
        vector_id = f"{source_id}_{chunk.chunk_index}"
        metadata: dict[str, Any] = {
            "source_id": source_id,
            "project_id": project_id,
            "chunk_index": chunk.chunk_index,
            "page_number": chunk.page_number,
            "content": chunk.content[:_METADATA_CONTENT_MAX],
        }
        # Flatten entity lists into searchable strings
        for key, values in entities.items():
            if values:
                metadata[f"entities_{key}"] = values[:20]  # Pinecone list limit

        vectors.append({"id": vector_id, "values": embedding, "metadata": metadata})

    batch_size = settings.pinecone_upsert_batch
    loop = asyncio.get_event_loop()

    for i in range(0, len(vectors), batch_size):
        batch = vectors[i : i + batch_size]
        try:
            await loop.run_in_executor(
                None,
                lambda b=batch: index.upsert(vectors=b, namespace=namespace),
            )
        except Exception as exc:
            log.error("Pinecone upsert failed for batch %d–%d: %s", i, i + len(batch), exc)
            raise


async def delete_source_vectors(source_id: str, project_id: str) -> None:
    """Delete all vectors belonging to a source from Pinecone."""
    index = _get_index()
    if index is None:
        return

    namespace = f"project_{project_id}"
    loop = asyncio.get_event_loop()

    try:
        await loop.run_in_executor(
            None,
            lambda: index.delete(
                filter={"source_id": {"$eq": source_id}},
                namespace=namespace,
            ),
        )
    except Exception as exc:
        log.warning("Pinecone delete failed for source %s: %s", source_id, exc)
