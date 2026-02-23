"""
Stage 2 — Clustering, entity graph construction, and cluster labelling.

K-means auto-k selection via silhouette score over k = 2 … min(10, n//3).
Falls back to k=1 when fewer than 4 chunks exist.

Entity graph: entities from all chunks grouped by normalised name.
Only entities that appear in ≥2 distinct sources are included.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

_MIN_CHUNKS_FOR_CLUSTERING = 4
_MAX_K = 10


# ─── Entity graph ─────────────────────────────────────────────────────────────


def build_entity_graph(
    chunk_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Parameters
    ----------
    chunk_rows:
        Each dict must have keys: source_id, content, entities (dict).
        entities keys: people, organizations, locations, dates, key_concepts.

    Returns
    -------
    entity_graph: dict mapping normalised entity name →
        {
          "source_ids": [...],
          "mention_count": int,
          "snippets": [{"source_id": ..., "text": ...}, ...],
        }
    Only entities appearing in ≥2 distinct sources are included.
    """
    # entity_name → {source_ids: set, mentions: int, snippets: list}
    raw: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"source_ids": set(), "mention_count": 0, "snippets": []}
    )

    for row in chunk_rows:
        source_id = row["source_id"]
        entities: dict[str, list[str]] = row.get("entities") or {}
        content = row.get("content", "")

        all_entity_names: list[str] = []
        for category in ("people", "organizations", "locations", "dates", "key_concepts"):
            all_entity_names.extend(entities.get(category, []))

        for name in all_entity_names:
            key = name.strip().lower()
            if not key:
                continue
            raw[key]["source_ids"].add(source_id)
            raw[key]["mention_count"] += 1
            # Keep up to 5 snippets with the chunk text (truncated)
            if len(raw[key]["snippets"]) < 5:
                snippet_text = content[:200] if content else ""
                raw[key]["snippets"].append(
                    {"source_id": source_id, "text": snippet_text}
                )

    # Filter to ≥2 distinct sources and serialise sets → lists
    graph: dict[str, Any] = {}
    for name, data in raw.items():
        if len(data["source_ids"]) >= 2:
            graph[name] = {
                "source_ids": sorted(data["source_ids"]),
                "mention_count": data["mention_count"],
                "snippets": data["snippets"],
            }

    return graph


# ─── K-means clustering ───────────────────────────────────────────────────────


def _auto_k(embeddings: np.ndarray) -> int:
    """Select k via silhouette score for k = 2 … min(MAX_K, n//3)."""
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    n = len(embeddings)
    k_max = min(_MAX_K, n // 3)
    if k_max < 2:
        return 1

    best_k, best_score = 1, -1.0
    for k in range(2, k_max + 1):
        km = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = km.fit_predict(embeddings)
        try:
            score = silhouette_score(embeddings, labels)
        except ValueError:
            continue
        if score > best_score:
            best_score, best_k = score, k
    return best_k


def cluster_chunks(
    chunk_rows: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> tuple[np.ndarray, int]:
    """
    Run KMeans on embeddings.  Returns (label_array, k).
    chunk_rows and embeddings must be same length and order.
    """
    from sklearn.cluster import KMeans

    n = len(embeddings)
    if n < _MIN_CHUNKS_FOR_CLUSTERING:
        return np.zeros(n, dtype=int), 1

    emb_array = np.array(embeddings, dtype=np.float32)
    k = _auto_k(emb_array)
    if k == 1:
        return np.zeros(n, dtype=int), 1

    km = KMeans(n_clusters=k, random_state=42, n_init="auto")
    labels: np.ndarray = km.fit_predict(emb_array)
    return labels, k


# ─── Cluster labelling via Claude Haiku ──────────────────────────────────────


_LABEL_PROMPT = """\
You are a research analyst. Here are the top entities found in a cluster of \
text chunks from various documents:

Entities: {entities}

Give this cluster a concise, descriptive label of 3–5 words that captures \
the main theme. Respond with ONLY the label text — no explanation, no quotes."""


async def label_clusters(
    client: Any,
    cluster_entities: list[list[str]],  # per-cluster top entities
) -> list[str]:
    """
    Ask Claude Haiku to label each cluster.  Falls back to generic labels
    if the API key is absent or a call fails.
    """
    from config import settings

    labels: list[str] = []
    for i, entities in enumerate(cluster_entities):
        fallback = f"Cluster {i + 1}"
        if not settings.anthropic_api_key or not entities:
            labels.append(fallback)
            continue
        try:
            response = await client.messages.create(
                model=settings.anthropic_model,
                max_tokens=32,
                messages=[
                    {
                        "role": "user",
                        "content": _LABEL_PROMPT.format(
                            entities=", ".join(entities[:10])
                        ),
                    }
                ],
            )
            label = response.content[0].text.strip()
            labels.append(label or fallback)
        except Exception as exc:
            logger.warning("Cluster labelling failed for cluster %d: %s", i, exc)
            labels.append(fallback)
    return labels


# ─── Orchestrator ─────────────────────────────────────────────────────────────


async def build_clusters(
    client: Any,
    chunk_rows: list[dict[str, Any]],
    embeddings: list[list[float]],
) -> list[dict[str, Any]]:
    """
    Full cluster pipeline:
      1. Run KMeans to assign labels
      2. Compute per-cluster stats (source_ids, chunk_count, top entities)
      3. Call Claude Haiku to label each cluster

    Returns list of cluster dicts matching ClusterOut schema.
    """
    if not chunk_rows:
        return []

    labels_array, k = cluster_chunks(chunk_rows, embeddings)

    # Collect per-cluster data
    clusters_raw: dict[int, dict[str, Any]] = {
        i: {
            "id": str(uuid.uuid4()),
            "source_ids": set(),
            "chunk_count": 0,
            "entity_counts": defaultdict(int),
        }
        for i in range(k)
    }

    for chunk, label in zip(chunk_rows, labels_array):
        c = clusters_raw[int(label)]
        c["source_ids"].add(chunk["source_id"])
        c["chunk_count"] += 1
        entities: dict[str, list[str]] = chunk.get("entities") or {}
        for category in ("people", "organizations", "key_concepts"):
            for name in entities.get(category, []):
                c["entity_counts"][name.strip().lower()] += 1

    # Top entities per cluster (for labelling)
    cluster_top_entities: list[list[str]] = []
    for i in range(k):
        top = sorted(
            clusters_raw[i]["entity_counts"].items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        cluster_top_entities.append([name for name, _ in top])

    cluster_labels = await label_clusters(client, cluster_top_entities)

    result: list[dict[str, Any]] = []
    for i in range(k):
        c = clusters_raw[i]
        result.append(
            {
                "id": c["id"],
                "label": cluster_labels[i],
                "source_count": len(c["source_ids"]),
                "chunk_count": c["chunk_count"],
                "source_ids": sorted(c["source_ids"]),
                "key_entities": cluster_top_entities[i],
            }
        )
    return result
