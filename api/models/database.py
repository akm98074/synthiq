"""
SQLAlchemy 2.0 async models — the six core tables for Synthiq MVP.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.utcnow()


class Base(DeclarativeBase):
    pass


# ─── Users ────────────────────────────────────────────────────────────────────


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    clerk_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="free"
    )
    # Phase 7: Stripe billing
    stripe_customer_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    stripe_subscription_id: Mapped[str | None] = mapped_column(String(255), unique=True)
    subscription_status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="inactive"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    projects: Mapped[list[Project]] = relationship(
        "Project", back_populates="user", cascade="all, delete-orphan"
    )
    voice_profile: Mapped[VoiceProfile | None] = relationship(
        "VoiceProfile", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


# ─── Projects ─────────────────────────────────────────────────────────────────


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    deliverable_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default="created"
    )
    source_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Phase 3: populated by index_project worker
    source_map: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    entity_graph: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Phase 4: voice calibration toggle
    use_voice_calibration: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="projects")
    sources: Mapped[list[Source]] = relationship(
        "Source", back_populates="project", cascade="all, delete-orphan"
    )
    deliverable: Mapped[Deliverable | None] = relationship(
        "Deliverable", back_populates="project", uselist=False, cascade="all, delete-orphan"
    )


# ─── Sources ──────────────────────────────────────────────────────────────────


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[str] = mapped_column(
        String(16), nullable=False  # pdf | url | docx | text
    )
    filename: Mapped[str | None] = mapped_column(String(512))
    url: Mapped[str | None] = mapped_column(Text)
    s3_key: Mapped[str | None] = mapped_column(String(1024))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending"
    )
    confidence_score: Mapped[float | None] = mapped_column()
    page_count: Mapped[int | None] = mapped_column(Integer)
    # Phase 3: user controls
    is_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_flagged: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped[Project] = relationship("Project", back_populates="sources")
    chunks: Mapped[list[Chunk]] = relationship(
        "Chunk", back_populates="source", cascade="all, delete-orphan"
    )


# ─── Chunks ───────────────────────────────────────────────────────────────────


class Chunk(Base):
    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    source_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    # Store embedding vector as JSONB for simplicity in MVP (Pinecone is primary vector store)
    entities: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    pinecone_id: Mapped[str | None] = mapped_column(String(255))
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    source: Mapped[Source] = relationship("Source", back_populates="chunks")


# ─── Voice Profiles ───────────────────────────────────────────────────────────


class VoiceProfile(Base):
    __tablename__ = "voice_profiles"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    user_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    style_signature: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    voice_system_prompt: Mapped[str | None] = mapped_column(Text)
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped[User] = relationship("User", back_populates="voice_profile")


# ─── Deliverables ─────────────────────────────────────────────────────────────


class Deliverable(Base):
    __tablename__ = "deliverables"

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False), primary_key=True, default=_uuid
    )
    project_id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        ForeignKey("projects.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="generating"
    )
    # Structured outline as JSON
    outline: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # Sections stored as JSON array
    sections: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    # Flat citation index
    citations: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    project: Mapped[Project] = relationship("Project", back_populates="deliverable")
