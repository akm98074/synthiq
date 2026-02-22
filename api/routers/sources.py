"""
Source ingestion endpoints — file upload and URL ingestion.

After creating a Source record, the file is stored in S3/local storage
and an ARQ background job (ingest_source) is enqueued to process it.
"""
from __future__ import annotations

import os
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.database import Project, Source, User
from models.schemas import SourceOut, SourceUrlCreate
from storage.s3 import get_storage

router = APIRouter(prefix="/projects/{project_id}/sources", tags=["sources"])

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
PLAN_SOURCE_LIMITS = {"free": 10, "professional": 50, "team": 100, "enterprise": None}
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024  # 50 MB

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
}


@router.get("", response_model=list[SourceOut])
async def list_sources(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)
    result = await db.execute(
        select(Source)
        .where(Source.project_id == project_id)
        .order_by(Source.created_at)
    )
    return [SourceOut.model_validate(s) for s in result.scalars().all()]


@router.post(
    "/upload",
    response_model=SourceOut,
    status_code=status.HTTP_201_CREATED,
)
async def upload_file(
    project_id: str,
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)
    await _assert_source_limit(db, project_id, current_user.plan)

    # ── Validate extension ────────────────────────────────────────────────────
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # ── Read & validate size ──────────────────────────────────────────────────
    content = await file.read()
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 50 MB)")

    source_type = "text" if ext == ".txt" else ext.lstrip(".")

    # ── Upload to storage ─────────────────────────────────────────────────────
    source_id = str(uuid.uuid4())
    s3_key = f"sources/{project_id}/{source_id}{ext}"
    storage = get_storage()
    await storage.upload(
        s3_key, content, content_type=CONTENT_TYPES.get(ext, "application/octet-stream")
    )

    # ── Persist source record ─────────────────────────────────────────────────
    source = Source(
        id=source_id,
        project_id=project_id,
        type=source_type,
        filename=file.filename,
        s3_key=s3_key,
        status="pending",
    )
    db.add(source)
    await db.flush()
    await _increment_source_count(db, project_id)
    await db.refresh(source)

    # ── Enqueue ingestion job ─────────────────────────────────────────────────
    await _enqueue_ingest(request, source.id)

    return SourceOut.model_validate(source)


@router.post(
    "/url",
    response_model=SourceOut,
    status_code=status.HTTP_201_CREATED,
)
async def add_url(
    project_id: str,
    request: Request,
    payload: SourceUrlCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)
    await _assert_source_limit(db, project_id, current_user.plan)

    source = Source(
        project_id=project_id,
        type="url",
        url=str(payload.url),
        status="pending",
    )
    db.add(source)
    await db.flush()
    await _increment_source_count(db, project_id)
    await db.refresh(source)

    await _enqueue_ingest(request, source.id)

    return SourceOut.model_validate(source)


@router.get("/{source_id}", response_model=SourceOut)
async def get_source(
    project_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Poll a single source's status during ingestion."""
    await _assert_project_owned(db, project_id, current_user.id)
    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.project_id == project_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return SourceOut.model_validate(source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(
    project_id: str,
    source_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)

    result = await db.execute(
        select(Source).where(Source.id == source_id, Source.project_id == project_id)
    )
    source = result.scalar_one_or_none()
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")

    # Remove from vector store (best-effort)
    from pipeline.vector_store import delete_source_vectors
    await delete_source_vectors(source_id, project_id)

    # Remove from storage (best-effort)
    if source.s3_key:
        try:
            storage = get_storage()
            await storage.delete(source.s3_key)
        except Exception:
            pass

    await db.delete(source)

    project_result = await db.execute(
        select(Project).where(Project.id == project_id)
    )
    project = project_result.scalar_one()
    project.source_count = max(0, project.source_count - 1)


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _enqueue_ingest(request: Request, source_id: str) -> None:
    """Enqueue the ingest_source ARQ job. Silently skip if pool unavailable."""
    arq_pool = getattr(request.app.state, "arq_pool", None)
    if arq_pool is None:
        return
    await arq_pool.enqueue_job("ingest_source", source_id)


async def _assert_project_owned(
    db: AsyncSession, project_id: str, user_id: str
) -> None:
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == user_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Project not found")


async def _assert_source_limit(
    db: AsyncSession, project_id: str, plan: str
) -> None:
    limit = PLAN_SOURCE_LIMITS.get(plan)
    if limit is None:
        return
    count_result = await db.execute(
        select(func.count(Source.id)).where(Source.project_id == project_id)
    )
    count = count_result.scalar_one()
    if count >= limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Source limit reached ({limit} for {plan} plan). Upgrade to add more.",
        )


async def _increment_source_count(db: AsyncSession, project_id: str) -> None:
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one()
    project.source_count += 1
