"""
Project CRUD endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models.database import Project, User
from models.schemas import (
    PaginatedProjects,
    ProjectCreate,
    ProjectOut,
    ProjectVoiceUpdate,
)
from services.plan_limits import check_project_limit, check_voice_access

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=PaginatedProjects)
async def list_projects(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    offset = (page - 1) * size
    total_result = await db.execute(
        select(func.count(Project.id)).where(Project.user_id == current_user.id)
    )
    total = total_result.scalar_one()

    projects_result = await db.execute(
        select(Project)
        .where(Project.user_id == current_user.id)
        .order_by(Project.created_at.desc())
        .offset(offset)
        .limit(size)
    )
    projects = projects_result.scalars().all()

    return PaginatedProjects(
        items=[ProjectOut.model_validate(p) for p in projects],
        total=total,
        page=page,
        size=size,
    )


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
async def create_project(
    payload: ProjectCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Enforce plan project limit
    count_result = await db.execute(
        select(func.count(Project.id)).where(Project.user_id == current_user.id)
    )
    count = count_result.scalar_one()
    check_project_limit(current_user.plan, count)

    project = Project(
        user_id=current_user.id,
        name=payload.name,
        deliverable_type=payload.deliverable_type,
        status="created",
        source_count=0,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    return ProjectOut.model_validate(project)


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(db, project_id, current_user.id)
    return ProjectOut.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = await _get_owned_project(db, project_id, current_user.id)
    await db.delete(project)


@router.patch("/{project_id}/voice", response_model=ProjectOut)
async def update_project_voice(
    project_id: str,
    payload: ProjectVoiceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle voice calibration on/off for a specific project."""
    if payload.use_voice_calibration:
        check_voice_access(current_user.plan)
    project = await _get_owned_project(db, project_id, current_user.id)
    project.use_voice_calibration = payload.use_voice_calibration
    await db.flush()
    await db.refresh(project)
    return ProjectOut.model_validate(project)


# ─── Helpers ──────────────────────────────────────────────────────────────────


async def _get_owned_project(
    db: AsyncSession, project_id: str, user_id: str
) -> Project:
    result = await db.execute(
        select(Project).where(
            Project.id == project_id, Project.user_id == user_id
        )
    )
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    return project
