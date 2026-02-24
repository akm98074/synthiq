"""
ARQ background task: Stage 4 (Outline) + Stage 5 (Draft).

Updates the Deliverable row incrementally after each section so the SSE
endpoint can stream progress to the frontend.
"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings
from models.database import Chunk, Deliverable, Project, Source, VoiceProfile
from pipeline.draft_generator import generate_section
from pipeline.outline_generator import generate_outline

log = logging.getLogger(__name__)


async def generate_deliverable(ctx: dict, project_id: str) -> dict[str, Any]:
    """
    Orchestrate Stage 4 (outline) + Stage 5 (draft) for a project.

    Persists each completed section to the DB so the SSE poll endpoint
    can deliver incremental progress to the browser.
    """
    client = ctx.get("anthropic_client")

    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as db:
            project = await _load_project(db, project_id)
            if project is None:
                log.error("Project %s not found", project_id)
                return {"error": "project_not_found"}

            deliverable = await _load_deliverable(db, project_id)
            if deliverable is None:
                log.error("No deliverable record for project %s", project_id)
                return {"error": "deliverable_not_found"}

            chunk_rows, chunk_map = await _load_chunks(db, project_id)
            voice_prompt = await _load_voice_prompt(db, project) if project.use_voice_calibration else None

            # ── Stage 4: Outline ───────────────────────────────────────────────
            log.info("Stage 4 — generating outline for project %s", project_id)
            project.status = "generating"
            await db.commit()

            outline = await generate_outline(
                client=client,
                deliverable_type=project.deliverable_type,
                source_map=project.source_map or {},
                entity_graph=project.entity_graph or {},
                chunk_rows=chunk_rows,
            )
            deliverable.outline = outline
            await db.commit()

            # ── Stage 5: Sections ──────────────────────────────────────────────
            all_sections = _flatten_sections(outline)
            log.info("Stage 5 — generating %d sections", len(all_sections))

            completed: list[dict[str, Any]] = []
            for section in all_sections:
                log.info("  Writing section: %s", section.get("title"))
                result = await generate_section(
                    client=client,
                    section=section,
                    chunk_map=chunk_map,
                    deliverable_type=project.deliverable_type,
                    voice_system_prompt=voice_prompt,
                )
                completed.append(result)
                # Persist partial state so SSE endpoint sees progress
                deliverable.sections = list(completed)
                await db.commit()

            deliverable.status = "ready"
            project.status = "ready"
            await db.commit()

            log.info(
                "generate_deliverable complete — project %s, %d sections",
                project_id,
                len(completed),
            )
            return {"status": "done", "sections": len(completed)}

    except Exception as exc:
        log.exception(
            "generate_deliverable failed for project %s: %s", project_id, exc
        )
        await _mark_error(project_id)
        return {"error": str(exc)}

    finally:
        await engine.dispose()


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _load_project(db: AsyncSession, project_id: str) -> Project | None:
    result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    return result.scalar_one_or_none()


async def _load_deliverable(db: AsyncSession, project_id: str) -> Deliverable | None:
    result = await db.execute(
        select(Deliverable).where(Deliverable.project_id == project_id)
    )
    return result.scalar_one_or_none()


async def _load_chunks(
    db: AsyncSession, project_id: str
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    result = await db.execute(
        select(Chunk, Source.filename, Source.url)
        .join(Source, Chunk.source_id == Source.id)
        .where(
            Source.project_id == project_id,
            Source.is_excluded.is_(False),
        )
        .order_by(Source.id, Chunk.chunk_index)
    )
    rows = result.all()
    chunk_rows = [
        {
            "id": c.id,
            "source_id": c.source_id,
            "content": c.content,
            "page_number": c.page_number,
            "entities": c.entities,
            "filename": filename,
            "url": url,
        }
        for c, filename, url in rows
    ]
    chunk_map = {r["id"]: r for r in chunk_rows}
    return chunk_rows, chunk_map


async def _load_voice_prompt(db: AsyncSession, project: Project) -> str | None:
    result = await db.execute(
        select(VoiceProfile).where(VoiceProfile.user_id == project.user_id)
    )
    vp = result.scalar_one_or_none()
    return vp.voice_system_prompt if vp else None


def _flatten_sections(outline: dict[str, Any]) -> list[dict[str, Any]]:
    """Return top-level sections and their subsections in order."""
    flat: list[dict[str, Any]] = []
    for section in outline.get("sections") or []:
        flat.append(section)
        for sub in section.get("subsections") or []:
            flat.append(sub)
    return flat


async def _mark_error(project_id: str) -> None:
    """Best-effort: mark the deliverable status as 'error'."""
    engine = create_async_engine(settings.database_url, echo=False)
    Session = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with Session() as db:
            result = await db.execute(
                select(Deliverable).where(Deliverable.project_id == project_id)
            )
            deliverable = result.scalar_one_or_none()
            if deliverable:
                deliverable.status = "error"
                await db.commit()
    except Exception:
        pass
    finally:
        await engine.dispose()
