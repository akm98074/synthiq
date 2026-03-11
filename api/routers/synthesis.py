"""
Source Map and Deliverable generation endpoints.
"""
from __future__ import annotations

import asyncio
import json
import logging
import pathlib
import re
import tempfile
import uuid
from typing import AsyncGenerator

from arq.connections import RedisSettings, create_pool
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from config import settings
from database import get_db
from models.database import Chunk, Deliverable, Project, Source, User, VoiceProfile
from models.schemas import (
    CitationOut,
    ClusterOut,
    ContradictionOut,
    DeliverableOut,
    ExportRequest,
    ExportResponse,
    GapOut,
    SectionInstructRequest,
    SectionOut,
    SourceFlagUpdate,
    SourceMapOut,
    SourceSidebarOut,
)
from pipeline.draft_generator import generate_section, instruct_section
from pipeline.exporter import build_docx, build_pdf

log = logging.getLogger(__name__)

router = APIRouter(prefix="/projects/{project_id}", tags=["synthesis"])


# ─── Source Map ───────────────────────────────────────────────────────────────


@router.get("/source-map", response_model=SourceMapOut)
async def get_source_map(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _assert_project_owned(db, project_id, current_user.id)

    sm = project.source_map
    if not sm:
        return SourceMapOut(
            clusters=[], contradictions=[], gaps=[], sources=[], entity_count=0
        )

    clusters = [ClusterOut(**c) for c in (sm.get("clusters") or [])]
    contradictions = [ContradictionOut(**c) for c in (sm.get("contradictions") or [])]
    gaps = [GapOut(**g) for g in (sm.get("gaps") or [])]
    sources = [SourceSidebarOut(**s) for s in (sm.get("sources") or [])]

    return SourceMapOut(
        clusters=clusters,
        contradictions=contradictions,
        gaps=gaps,
        sources=sources,
        entity_count=sm.get("entity_count", 0),
    )


# ─── Source flag / exclude ────────────────────────────────────────────────────


@router.put("/sources/{source_id}/flag", response_model=dict)
async def flag_source(
    project_id: str,
    source_id: str,
    payload: SourceFlagUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)
    result = await db.execute(
        select(Source).where(
            Source.id == source_id, Source.project_id == project_id
        )
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    if payload.is_flagged is not None:
        source.is_flagged = payload.is_flagged
    if payload.is_excluded is not None:
        source.is_excluded = payload.is_excluded

    await db.commit()
    return {
        "id": source_id,
        "is_flagged": source.is_flagged,
        "is_excluded": source.is_excluded,
    }


# ─── Deliverable ──────────────────────────────────────────────────────────────


@router.get("/deliverable", response_model=DeliverableOut)
async def get_deliverable(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)
    deliverable = await _get_deliverable_or_404(db, project_id)
    return _deliverable_to_out(deliverable)


@router.post("/deliverable/generate", response_model=DeliverableOut)
async def generate_deliverable_endpoint(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)

    # Upsert deliverable record
    result = await db.execute(
        select(Deliverable).where(Deliverable.project_id == project_id)
    )
    deliverable = result.scalar_one_or_none()

    if deliverable is None:
        deliverable = Deliverable(
            project_id=project_id,
            version=1,
            status="generating",
            outline=None,
            sections=[],
        )
        db.add(deliverable)
    else:
        deliverable.version += 1
        deliverable.status = "generating"
        deliverable.outline = None
        deliverable.sections = []

    await db.flush()
    await db.refresh(deliverable)
    await db.commit()

    # Enqueue Stage 4+5 background job
    try:
        pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
        await pool.enqueue_job("generate_deliverable", project_id)
        await pool.aclose()
    except Exception as exc:
        log.warning("Could not enqueue generate_deliverable (%s)", exc)

    return _deliverable_to_out(deliverable)


# ─── SSE progress stream ──────────────────────────────────────────────────────


@router.get("/deliverable/events")
async def deliverable_events(
    project_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Server-Sent Events endpoint.

    Polls the DB every 2 s and emits 'progress' events with incremental
    section data until status is 'ready' or 'error', then sends 'done'.
    """
    await _assert_project_owned(db, project_id, current_user.id)

    async def event_generator() -> AsyncGenerator[str, None]:
        last_section_count = -1
        while True:
            if await request.is_disconnected():
                break

            result = await db.execute(
                select(Deliverable).where(Deliverable.project_id == project_id)
            )
            await db.commit()  # ensure fresh read
            deliverable = result.scalar_one_or_none()

            if deliverable is None:
                yield _sse("error", {"detail": "No deliverable found"})
                break

            section_count = len(deliverable.sections or [])
            if section_count != last_section_count:
                last_section_count = section_count
                data = _deliverable_to_out(deliverable).model_dump()
                yield _sse("progress", data)

            if deliverable.status in ("ready", "error"):
                yield _sse("done", {"status": deliverable.status})
                break

            await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


# ─── Section regenerate / instruct ───────────────────────────────────────────


@router.post(
    "/deliverable/sections/{section_id}/regenerate",
    response_model=DeliverableOut,
)
async def regenerate_section(
    project_id: str,
    section_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _assert_project_owned(db, project_id, current_user.id)
    deliverable = await _get_deliverable_or_404(db, project_id)

    sections: list[dict] = list(deliverable.sections or [])
    section = next((s for s in sections if s.get("id") == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    client = _make_anthropic_client()
    _, chunk_map = await _load_chunks(db, project_id)
    voice_prompt = (
        await _load_voice_prompt(db, project) if project.use_voice_calibration else None
    )

    # Merge outline section data so chunk_ids are available
    outline_section = _find_outline_section(deliverable.outline, section_id)
    merged = {**outline_section, **section} if outline_section else section

    updated = await generate_section(
        client=client,
        section=merged,
        chunk_map=chunk_map,
        deliverable_type=project.deliverable_type,
        voice_system_prompt=voice_prompt,
    )

    sections = [updated if s.get("id") == section_id else s for s in sections]
    deliverable.sections = sections
    await db.commit()
    return _deliverable_to_out(deliverable)


@router.post(
    "/deliverable/sections/{section_id}/instruct",
    response_model=DeliverableOut,
)
async def instruct_section_endpoint(
    project_id: str,
    section_id: str,
    payload: SectionInstructRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _assert_project_owned(db, project_id, current_user.id)
    deliverable = await _get_deliverable_or_404(db, project_id)

    sections: list[dict] = list(deliverable.sections or [])
    section = next((s for s in sections if s.get("id") == section_id), None)
    if section is None:
        raise HTTPException(status_code=404, detail="Section not found")

    client = _make_anthropic_client()
    _, chunk_map = await _load_chunks(db, project_id)
    voice_prompt = (
        await _load_voice_prompt(db, project) if project.use_voice_calibration else None
    )

    outline_section = _find_outline_section(deliverable.outline, section_id)
    merged = {**outline_section, **section} if outline_section else section

    updated = await instruct_section(
        client=client,
        section=merged,
        instruction=payload.instruction,
        chunk_map=chunk_map,
        deliverable_type=project.deliverable_type,
        voice_system_prompt=voice_prompt,
    )

    sections = [updated if s.get("id") == section_id else s for s in sections]
    deliverable.sections = sections
    await db.commit()
    return _deliverable_to_out(deliverable)


# ─── Export ───────────────────────────────────────────────────────────────────


@router.post("/export", response_model=ExportResponse)
async def export_deliverable(
    project_id: str,
    payload: ExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _assert_project_owned(db, project_id, current_user.id)
    deliverable = await _get_deliverable_or_404(db, project_id)

    if deliverable.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Deliverable is not ready for export",
        )

    sections = deliverable.sections or []
    source_map = project.source_map or {}

    slug = re.sub(r"[^\w\-]", "_", project.name.lower())[:48]
    filename_base = f"{slug}_v{deliverable.version}"

    if payload.format == "docx":
        file_bytes = build_docx(
            sections=sections,
            project_name=project.name,
            deliverable_type=project.deliverable_type,
            citation_style=payload.citation_style,
            include_source_map=payload.include_source_map,
            source_map=source_map if payload.include_source_map else None,
        )
        filename = f"{filename_base}.docx"
        content_type = (
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
    else:
        file_bytes = build_pdf(
            sections=sections,
            project_name=project.name,
            deliverable_type=project.deliverable_type,
            citation_style=payload.citation_style,
            include_source_map=payload.include_source_map,
            source_map=source_map if payload.include_source_map else None,
        )
        filename = f"{filename_base}.pdf"
        content_type = "application/pdf"

    download_url = await _store_export(file_bytes, filename, content_type)
    return ExportResponse(
        download_url=download_url,
        filename=filename,
        format=payload.format,
    )


# ─── Private helpers ──────────────────────────────────────────────────────────


async def _assert_project_owned(
    db: AsyncSession, project_id: str, user_id: str
) -> Project:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def _get_deliverable_or_404(db: AsyncSession, project_id: str) -> Deliverable:
    result = await db.execute(
        select(Deliverable).where(Deliverable.project_id == project_id)
    )
    d = result.scalar_one_or_none()
    if d is None:
        raise HTTPException(status_code=404, detail="No deliverable found")
    return d


async def _load_chunks(
    db: AsyncSession, project_id: str
) -> tuple[list[dict], dict[str, dict]]:
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


def _make_anthropic_client():
    """Create a fresh AsyncAnthropic client (used by synchronous endpoints)."""
    try:
        import anthropic
        return anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    except Exception:
        return None


def _find_outline_section(
    outline: dict | None, section_id: str
) -> dict | None:
    if not outline:
        return None
    for s in outline.get("sections") or []:
        if s.get("id") == section_id:
            return s
        for sub in s.get("subsections") or []:
            if sub.get("id") == section_id:
                return sub
    return None


async def _store_export(
    file_bytes: bytes, filename: str, content_type: str
) -> str:
    """
    Upload to S3 and return a presigned URL, or save locally and return a
    /export-download/ URL for local development.
    """
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        import boto3

        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
            region_name=settings.aws_region,
        )
        key = f"exports/{uuid.uuid4()}/{filename}"
        s3.put_object(
            Bucket=settings.aws_s3_bucket,
            Key=key,
            Body=file_bytes,
            ContentType=content_type,
        )
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.aws_s3_bucket, "Key": key},
            ExpiresIn=3600,
        )

    # Local dev: write to temp dir, return a FastAPI serve URL
    export_dir = pathlib.Path(tempfile.gettempdir()) / "synthiq-exports"
    export_dir.mkdir(exist_ok=True)
    token = str(uuid.uuid4())
    (export_dir / f"{token}_{filename}").write_bytes(file_bytes)
    return f"{settings.api_url}/export-download/{token}/{filename}"


def _deliverable_to_out(d: Deliverable) -> DeliverableOut:
    sections = d.sections or []
    section_outs = []
    for s in sections:
        citations = [
            CitationOut(
                source_id=c.get("source_id", ""),
                source_title=c.get("source_title", ""),
                page=c.get("page"),
                marker=c.get("marker"),
                quote=c.get("quote"),
            )
            for c in (s.get("citations") or [])
        ]
        section_outs.append(
            SectionOut(
                id=s.get("id", ""),
                title=s.get("title", ""),
                content=s.get("content", ""),
                status=s.get("status", "done"),
                citations=citations,
            )
        )
    return DeliverableOut(
        id=d.id,
        version=d.version,
        status=d.status,
        outline=d.outline,
        sections=section_outs,
    )
