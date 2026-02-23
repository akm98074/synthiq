"""
Pydantic v2 schemas for request/response validation.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl


# ─── Shared ───────────────────────────────────────────────────────────────────


class OrmModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


DeliverableType = Literal[
    "executive_memo",
    "competitive_landscape",
    "investment_thesis",
    "project_brief",
    "literature_summary",
]

ProjectStatus = Literal[
    "created",
    "ingesting",
    "indexing",
    "cross_referencing",
    "generating",
    "ready",
    "error",
]

SourceStatus = Literal["pending", "processing", "ready", "error"]
SourceType = Literal["pdf", "url", "docx", "text"]


# ─── User ─────────────────────────────────────────────────────────────────────


class UserOut(OrmModel):
    id: str
    clerk_id: str
    email: str
    plan: str
    created_at: datetime


# ─── Project ──────────────────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    deliverable_type: DeliverableType


class ProjectOut(OrmModel):
    id: str
    name: str
    deliverable_type: str
    status: str
    source_count: int
    created_at: datetime
    updated_at: datetime


class PaginatedProjects(BaseModel):
    items: list[ProjectOut]
    total: int
    page: int
    size: int


# ─── Source ───────────────────────────────────────────────────────────────────


class SourceUrlCreate(BaseModel):
    url: str = Field(..., min_length=1)


class SourceOut(OrmModel):
    id: str
    project_id: str
    type: str
    filename: str | None = None
    url: str | None = None
    status: str
    confidence_score: float | None = None
    page_count: int | None = None
    is_excluded: bool = False
    is_flagged: bool = False
    created_at: datetime


# ─── Source Map ───────────────────────────────────────────────────────────────


class ClusterOut(BaseModel):
    id: str
    label: str
    source_count: int
    chunk_count: int
    source_ids: list[str]
    key_entities: list[str]


class ContradictionOut(BaseModel):
    id: str
    entity: str
    claim: str
    source_a: str
    source_a_id: str
    source_b: str
    source_b_id: str
    quote_a: str
    quote_b: str
    significance: float = 0.5


class GapOut(BaseModel):
    topic: str
    mentioned_in_count: int
    missing_in_count: int
    missing_source_ids: list[str]


class SourceSidebarOut(BaseModel):
    id: str
    filename: str | None = None
    url: str | None = None
    type: str
    status: str
    confidence_score: float | None = None
    page_count: int | None = None
    is_excluded: bool = False
    is_flagged: bool = False
    cluster_ids: list[str] = []


class SourceFlagUpdate(BaseModel):
    is_flagged: bool | None = None
    is_excluded: bool | None = None


class SourceMapOut(BaseModel):
    clusters: list[ClusterOut]
    contradictions: list[ContradictionOut]
    gaps: list[GapOut]
    sources: list[SourceSidebarOut]
    entity_count: int = 0


# ─── Deliverable ──────────────────────────────────────────────────────────────


class CitationOut(BaseModel):
    source_id: str
    source_title: str
    page: int | None = None


class SectionOut(BaseModel):
    id: str
    title: str
    content: str
    citations: list[CitationOut]


class DeliverableOut(BaseModel):
    id: str
    version: int
    status: str
    sections: list[SectionOut]


class SectionInstructRequest(BaseModel):
    instruction: str = Field(..., min_length=1)


# ─── Export ───────────────────────────────────────────────────────────────────


class ExportRequest(BaseModel):
    format: Literal["docx", "pdf"] = "docx"
    include_citations: bool = True
    include_source_map: bool = False


class ExportResponse(BaseModel):
    download_url: str


# ─── Voice ────────────────────────────────────────────────────────────────────


class VoiceProfileOut(BaseModel):
    id: str
    sample_count: int
    style_signature: dict[str, Any] | None = None
    updated_at: datetime
