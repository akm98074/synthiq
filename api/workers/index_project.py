"""
ARQ background task: index_project

Stage 2 + 3 pipeline — run after all sources for a project are ready.

  Stage 2 (Indexing):
    1. Load all non-excluded chunks with embeddings from DB
    2. Cluster chunks via K-means with silhouette-score auto-k
    3. Label clusters via Claude Haiku
    4. Build entity graph (cross-source entities appearing in ≥2 sources)
    5. Compute per-source confidence scores
    6. Persist source_map + entity_graph to Project

  Stage 3 (Cross-reference):
    7. Detect contradictions via Claude Haiku (per entity, cross-source)
    8. Detect gaps (entity in ≥60 % of sources but absent in ≥1)
    9. Persist updated source_map to Project
   10. Mark project status → "ready" (or "error")
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from database import AsyncSessionLocal
from models.database import Chunk, Project, Source

log = logging.getLogger(__name__)


async def index_project(ctx: dict[str, Any], project_id: str) -> dict[str, Any]:
    """ARQ entry point.  ctx populated by WorkerSettings.on_startup."""
    import anthropic

    anthropic_client: anthropic.AsyncAnthropic = ctx["anthropic_client"]

    log.info("index_project: starting project=%s", project_id)

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Project)
            .options(selectinload(Project.sources).selectinload(Source.chunks))
            .where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            log.error("index_project: project %s not found", project_id)
            return {"status": "error", "reason": "not_found"}

        project.status = "indexing"
        await db.commit()

    try:
        # ── Load data from DB ────────────────────────────────────────────────
        async with AsyncSessionLocal() as db:
            sources_result = await db.execute(
                select(Source).where(
                    Source.project_id == project_id,
                    Source.is_excluded.is_(False),
                    Source.status == "ready",
                )
            )
            sources = list(sources_result.scalars())

            if not sources:
                log.warning("index_project: no ready sources for project=%s", project_id)
                await _set_project_status(project_id, "ready")
                return {"status": "ready", "clusters": 0}

            source_ids = [s.id for s in sources]

            # Load all chunks for these sources
            chunks_result = await db.execute(
                select(Chunk).where(Chunk.source_id.in_(source_ids))
            )
            all_chunks = list(chunks_result.scalars())

        # ── Build source display name map ────────────────────────────────────
        source_name_map: dict[str, str] = {}
        source_type_map: dict[str, str] = {}
        for s in sources:
            name = s.filename or s.url or s.id
            source_name_map[s.id] = str(name)
            source_type_map[s.id] = s.type

        # ── Stage 2a: Confidence scores ──────────────────────────────────────
        from pipeline.confidence import compute_confidence

        async with AsyncSessionLocal() as db:
            for source in sources:
                src_chunks = [c for c in all_chunks if c.source_id == source.id]
                entities_list = [c.entities or {} for c in src_chunks]
                score = compute_confidence(source.type, entities_list)
                result = await db.execute(
                    select(Source).where(Source.id == source.id)
                )
                src_row = result.scalar_one()
                src_row.confidence_score = score
            await db.commit()

        # ── Stage 2b: Entity graph ────────────────────────────────────────────
        from pipeline.clustering import build_entity_graph

        chunk_rows = [
            {
                "source_id": c.source_id,
                "content": c.content,
                "entities": c.entities or {},
            }
            for c in all_chunks
        ]

        entity_graph = build_entity_graph(chunk_rows)
        log.info(
            "index_project: entity_graph built, %d cross-source entities",
            len(entity_graph),
        )

        # ── Stage 2c: Clustering ──────────────────────────────────────────────
        from pipeline.clustering import build_clusters

        # We need embeddings — fetch from Pinecone or use zero vectors as fallback
        # For MVP: use zero-vectors if Pinecone not configured (clustering still runs
        # but may be less meaningful)
        embeddings = await _load_embeddings(all_chunks, source_ids)

        clusters = await build_clusters(anthropic_client, chunk_rows, embeddings)
        log.info("index_project: %d clusters built", len(clusters))

        # ── Stage 2d: Map source → cluster_ids ───────────────────────────────
        source_cluster_map: dict[str, list[str]] = {sid: [] for sid in source_ids}
        for cluster in clusters:
            for sid in cluster["source_ids"]:
                source_cluster_map.setdefault(sid, []).append(cluster["id"])

        # ── Stage 2e: Build sidebar sources data ─────────────────────────────
        async with AsyncSessionLocal() as db:
            sources_result = await db.execute(
                select(Source).where(Source.project_id == project_id)
            )
            all_sources = list(sources_result.scalars())

        sidebar_sources = [
            {
                "id": s.id,
                "filename": s.filename,
                "url": s.url,
                "type": s.type,
                "status": s.status,
                "confidence_score": s.confidence_score,
                "page_count": s.page_count,
                "is_excluded": s.is_excluded,
                "is_flagged": s.is_flagged,
                "cluster_ids": source_cluster_map.get(s.id, []),
            }
            for s in all_sources
        ]

        # ── Stage 3a: Contradiction detection ────────────────────────────────
        async with AsyncSessionLocal() as db:
            project_row = await db.execute(
                select(Project).where(Project.id == project_id)
            )
            project = project_row.scalar_one()
            project.status = "cross_referencing"
            await db.commit()

        from pipeline.cross_reference import detect_contradictions, detect_gaps

        contradictions = await detect_contradictions(
            anthropic_client, entity_graph, source_name_map
        )
        log.info("index_project: %d contradictions found", len(contradictions))

        # ── Stage 3b: Gap detection ───────────────────────────────────────────
        gaps = detect_gaps(entity_graph, source_ids)
        log.info("index_project: %d gaps found", len(gaps))

        # ── Persist source_map and entity_graph ───────────────────────────────
        source_map_payload: dict[str, Any] = {
            "clusters": clusters,
            "contradictions": contradictions,
            "gaps": gaps,
            "sources": sidebar_sources,
            "entity_count": len(entity_graph),
        }

        # Serialize entity_graph: convert any sets to lists
        entity_graph_serializable = {
            k: {
                "source_ids": v["source_ids"],
                "mention_count": v["mention_count"],
                "snippets": v["snippets"],
            }
            for k, v in entity_graph.items()
        }

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Project).where(Project.id == project_id)
            )
            project = result.scalar_one()
            project.source_map = source_map_payload
            project.entity_graph = entity_graph_serializable
            project.status = "ready"
            await db.commit()

        log.info(
            "index_project: done project=%s clusters=%d contradictions=%d gaps=%d",
            project_id,
            len(clusters),
            len(contradictions),
            len(gaps),
        )
        return {
            "status": "ready",
            "clusters": len(clusters),
            "contradictions": len(contradictions),
            "gaps": len(gaps),
            "entity_count": len(entity_graph),
        }

    except Exception as exc:
        log.exception("index_project: failed project=%s: %s", project_id, exc)
        await _set_project_status(project_id, "error")
        raise


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _set_project_status(project_id: str, status: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()
        if project:
            project.status = status
            await db.commit()


async def _load_embeddings(
    chunks: list[Chunk],
    source_ids: list[str],
) -> list[list[float]]:
    """
    Return embeddings for chunks in the same order as `chunks`.
    In MVP we re-embed using the stored chunk content (Voyage AI).
    Falls back to zero-vectors when Voyage key is absent.
    """
    from pipeline.embedder import EMBEDDING_DIM, embed_texts

    texts = [c.content for c in chunks]
    if not texts:
        return []
    embeddings = await embed_texts(texts)
    return embeddings
