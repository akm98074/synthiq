"""
Text embedding using Voyage AI (voyage-3, 1024 dimensions).

Falls back to deterministic zero-vectors when VOYAGE_API_KEY is not set,
so the full pipeline still runs in development without an API key.
"""
from __future__ import annotations

import logging
import math

import voyageai  # type: ignore[import-untyped]

from config import settings

log = logging.getLogger(__name__)

EMBEDDING_DIM = settings.voyage_dimensions  # 1024 for voyage-3


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for a list of texts.

    Returns a list of float vectors of length EMBEDDING_DIM.
    """
    if not texts:
        return []

    if not settings.voyage_api_key:
        log.debug("No VOYAGE_API_KEY — returning zero vectors (dev mode)")
        return [_zero_vector() for _ in texts]

    client = voyageai.AsyncClient(api_key=settings.voyage_api_key)
    batch_size = settings.embed_batch_size
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        try:
            result = await client.embed(
                batch,
                model=settings.voyage_model,
                input_type="document",
            )
            all_embeddings.extend(result.embeddings)
        except Exception as exc:
            log.warning(
                "Embedding failed for batch %d–%d: %s — using zero vectors",
                i,
                i + len(batch),
                exc,
            )
            all_embeddings.extend(_zero_vector() for _ in batch)

    return all_embeddings


def _zero_vector() -> list[float]:
    return [0.0] * EMBEDDING_DIM
