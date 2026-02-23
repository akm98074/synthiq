"""Add source_map and entity_graph to projects; is_excluded and is_flagged to sources.

Revision ID: 002_source_map
Revises: 001_initial_schema
Create Date: 2026-02-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "002_source_map"
down_revision = "001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add JSONB columns to projects
    op.add_column("projects", sa.Column("source_map", JSONB, nullable=True))
    op.add_column("projects", sa.Column("entity_graph", JSONB, nullable=True))

    # Add boolean columns to sources
    op.add_column(
        "sources",
        sa.Column(
            "is_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "sources",
        sa.Column(
            "is_flagged",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Index for quick filtering of excluded/flagged sources
    op.create_index(
        "ix_sources_is_excluded",
        "sources",
        ["is_excluded"],
        postgresql_where=sa.text("is_excluded = true"),
    )
    op.create_index(
        "ix_sources_is_flagged",
        "sources",
        ["is_flagged"],
        postgresql_where=sa.text("is_flagged = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_sources_is_flagged", table_name="sources")
    op.drop_index("ix_sources_is_excluded", table_name="sources")
    op.drop_column("sources", "is_flagged")
    op.drop_column("sources", "is_excluded")
    op.drop_column("projects", "entity_graph")
    op.drop_column("projects", "source_map")
