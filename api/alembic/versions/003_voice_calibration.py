"""Add use_voice_calibration to projects.

Revision ID: 003_voice_calibration
Revises: 002_source_map
Create Date: 2026-02-24
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "003_voice_calibration"
down_revision = "002_source_map"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "use_voice_calibration",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "use_voice_calibration")
