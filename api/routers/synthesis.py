"""
Source Map and Deliverable generation endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.database import Deliverable, Project, Source, User
from models.schemas import (
    ClusterOut,
    ContradictionOut,
    DeliverableOut,
    ExportRequest,
    ExportResponse,
    GapOut,
    SectionInstructRequest,
    SourceFlagUpdate,
    SourceMapOut,
    SourceSidebarOut,
)

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
        # Pipeline not yet complete — return empty structure
        return SourceMapOut(clusters=[], contradictions=[], gaps=[], sources=[], entity_count=0)

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
    return {"id": source_id, "is_flagged": source.is_flagged, "is_excluded": source.is_excluded}


# ─── Deliverable ──────────────────────────────────────────────────────────────


@router.get("/deliverable", response_model=DeliverableOut)
async def get_deliverable(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)
    result = await db.execute(
        select(Deliverable).where(Deliverable.project_id == project_id)
    )
    deliverable = result.scalar_one_or_none()
    if deliverable is None:
        raise HTTPException(status_code=404, detail="No deliverable generated yet")
    return _deliverable_to_out(deliverable)


@router.post("/deliverable/generate", response_model=DeliverableOut)
async def generate_deliverable(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)

    # Check if one already exists; bump version if so
    result = await db.execute(
        select(Deliverable).where(Deliverable.project_id == project_id)
    )
    deliverable = result.scalar_one_or_none()

    if deliverable is None:
        deliverable = Deliverable(
            project_id=project_id,
            version=1,
            status="generating",
            sections=[],
        )
        db.add(deliverable)
    else:
        deliverable.version += 1
        deliverable.status = "generating"
        deliverable.sections = []

    await db.flush()
    await db.refresh(deliverable)
    # Full pipeline (Stages 4-5) enqueued as background job in Phase 5
    return _deliverable_to_out(deliverable)


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
    await _assert_project_owned(db, project_id, current_user.id)
    deliverable = await _get_deliverable_or_404(db, project_id)
    # Section regeneration implemented in Phase 5
    return _deliverable_to_out(deliverable)


@router.post(
    "/deliverable/sections/{section_id}/instruct",
    response_model=DeliverableOut,
)
async def instruct_section(
    project_id: str,
    section_id: str,
    payload: SectionInstructRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)
    deliverable = await _get_deliverable_or_404(db, project_id)
    # Instruction-based editing implemented in Phase 5
    return _deliverable_to_out(deliverable)


# ─── Export ───────────────────────────────────────────────────────────────────


@router.post("/export", response_model=ExportResponse)
async def export_deliverable(
    project_id: str,
    payload: ExportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await _assert_project_owned(db, project_id, current_user.id)
    await _get_deliverable_or_404(db, project_id)
    # Full export (python-docx / weasyprint + S3 presigned URL) in Phase 6
    return ExportResponse(
        download_url=f"/projects/{project_id}/export/placeholder.{payload.format}"
    )


# ─── Helpers ──────────────────────────────────────────────────────────────────


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


def _deliverable_to_out(d: Deliverable) -> DeliverableOut:
    sections = d.sections or []
    return DeliverableOut(
        id=d.id,
        version=d.version,
        status=d.status,
        sections=[
            {
                "id": s.get("id", ""),
                "title": s.get("title", ""),
                "content": s.get("content", ""),
                "citations": s.get("citations", []),
            }
            for s in sections
        ],
    )
