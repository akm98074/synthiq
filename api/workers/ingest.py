"""
ARQ background task: ingest_source

Full ingestion pipeline for a single Source record:

  1. Load Source from DB; mark status → "processing"
  2. Retrieve raw bytes (S3 or local storage)
  3. Parse document into pages (PDF / DOCX / URL / text)
  4. Chunk pages into overlapping TextChunk objects
  5. Extract entities from each chunk via Claude Haiku
  6. Embed chunks via Voyage AI
  7. Upsert vectors to Pinecone
  8. Persist Chunk rows to PostgreSQL
  9. Mark Source status → "ready" (or "error")
 10. Update Project status when all its sources are processed
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import anthropic
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal
from models.database import Chunk, Project, Source
from pipeline.chunker import TextChunk, chunk_pages
from pipeline.embedder import embed_texts
from pipeline.entities import extract_entities_batch
from pipeline.parsers import PageText, parse_docx, parse_pdf, parse_text, parse_url
from pipeline.vector_store import delete_source_vectors, upsert_chunks
from storage.s3 import get_storage

log = logging.getLogger(__name__)


# ─── ARQ task ─────────────────────────────────────────────────────────────────


async def ingest_source(ctx: dict[str, Any], source_id: str) -> dict[str, Any]:
    """
    ARQ entry point.  `ctx` is populated by WorkerSettings.on_startup.
    """
    anthropic_client: anthropic.AsyncAnthropic = ctx["anthropic_client"]

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()

        if source is None:
            log.error("ingest_source: source %s not found", source_id)
            return {"status": "error", "reason": "not_found"}

        log.info("ingest_source: starting source=%s type=%s", source_id, source.type)
        source.status = "processing"
        await db.commit()

    try:
        # ── Step 2: get raw bytes ────────────────────────────────────────────
        raw_bytes, source_url = await _fetch_content(source)

        # ── Step 3: parse ────────────────────────────────────────────────────
        pages = await _parse(source.type, raw_bytes, source_url)
        if not pages:
            raise ValueError("Parser returned no pages — document may be empty")

        # ── Step 4: chunk ────────────────────────────────────────────────────
        chunks: list[TextChunk] = chunk_pages(pages)
        log.info("ingest_source: %d chunks from %d pages", len(chunks), len(pages))

        texts = [c.content for c in chunks]

        # ── Step 5: entities (parallel-ish via async) ────────────────────────
        entities_list = await extract_entities_batch(anthropic_client, texts)

        # ── Step 6: embeddings ───────────────────────────────────────────────
        embeddings = await embed_texts(texts)

        # ── Step 7: Pinecone upsert ──────────────────────────────────────────
        await upsert_chunks(
            source_id=source.id,
            project_id=source.project_id,
            chunks=chunks,
            embeddings=embeddings,
            entities_list=entities_list,
        )

        # ── Step 8: persist chunks to DB ─────────────────────────────────────
        async with AsyncSessionLocal() as db:
            # Remove any old chunks (idempotent re-run support)
            old = await db.execute(
                select(Chunk).where(Chunk.source_id == source_id)
            )
            for old_chunk in old.scalars():
                await db.delete(old_chunk)

            for chunk, entities in zip(chunks, entities_list):
                db.add(
                    Chunk(
                        source_id=source_id,
                        content=chunk.content,
                        page_number=chunk.page_number,
                        chunk_index=chunk.chunk_index,
                        entities=entities,
                        pinecone_id=f"{source_id}_{chunk.chunk_index}",
                        is_duplicate=False,
                    )
                )

            # ── Step 9: mark source ready ────────────────────────────────────
            result = await db.execute(select(Source).where(Source.id == source_id))
            source = result.scalar_one()
            source.status = "ready"
            source.confidence_score = 1.0
            page_count = max(
                (c.page_number or 0 for c in chunks), default=0
            )
            source.page_count = page_count

            await db.commit()

        # ── Step 10: update project status ───────────────────────────────────
        await _maybe_advance_project_status(source.project_id)

        log.info(
            "ingest_source: done source=%s chunks=%d pages=%d",
            source_id,
            len(chunks),
            len(pages),
        )
        return {"status": "ready", "chunks": len(chunks), "pages": len(pages)}

    except Exception as exc:
        log.exception("ingest_source: failed source=%s: %s", source_id, exc)
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(Source).where(Source.id == source_id))
            src = result.scalar_one_or_none()
            if src:
                src.status = "error"
                await db.commit()
        raise


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _fetch_content(source: Source) -> tuple[bytes | None, str | None]:
    """
    Return (raw_bytes, url).
    For file-based sources: download from storage and return (bytes, None).
    For URL sources: return (None, url_string).
    """
    if source.type == "url":
        return None, source.url

    storage = get_storage()
    if not source.s3_key:
        raise ValueError(f"Source {source.id} has no s3_key")
    raw = await storage.download(source.s3_key)
    return raw, None


async def _parse(
    source_type: str,
    raw_bytes: bytes | None,
    url: str | None,
) -> list[PageText]:
    """Dispatch to the correct parser based on source_type."""
    if source_type == "url":
        if not url:
            raise ValueError("URL source has no URL")
        return await parse_url(url)
    if raw_bytes is None:
        raise ValueError(f"No content for source type {source_type!r}")
    if source_type == "pdf":
        return parse_pdf(raw_bytes)
    if source_type == "docx":
        return parse_docx(raw_bytes)
    if source_type in ("text", "txt"):
        return parse_text(raw_bytes)
    raise ValueError(f"Unknown source type: {source_type!r}")


async def _maybe_advance_project_status(project_id: str) -> None:
    """
    If all sources in the project are now ready (or errored), update
    the project's status to either "indexing" or "error".
    """
    async with AsyncSessionLocal() as db:
        counts = await db.execute(
            select(
                Source.status,
                func.count(Source.id).label("cnt"),
            )
            .where(Source.project_id == project_id)
            .group_by(Source.status)
        )
        status_map: dict[str, int] = {row.status: row.cnt for row in counts}

        total = sum(status_map.values())
        ready = status_map.get("ready", 0)
        error = status_map.get("error", 0)
        pending_or_processing = total - ready - error

        if pending_or_processing > 0:
            return  # Still work to do

        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            return

        if error > 0 and ready == 0:
            project.status = "error"
        else:
            # All done — move to indexing (cross-reference stage in Phase 3)
            project.status = "indexing"

        await db.commit()
