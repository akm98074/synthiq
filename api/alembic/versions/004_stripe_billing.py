"""004: Add Stripe billing columns to users table.

Revision ID: 004_stripe_billing
Revises: 003_voice_calibration
Create Date: 2025-01-01 00:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = "004_stripe_billing"
down_revision = "003_voice_calibration"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("stripe_customer_id", sa.String(255), nullable=True, unique=True),
    )
    op.add_column(
        "users",
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True, unique=True),
    )
    op.add_column(
        "users",
        sa.Column(
            "subscription_status",
            sa.String(32),
            nullable=False,
            server_default="inactive",
        ),
    )
    op.create_index(
        "ix_users_stripe_customer_id",
        "users",
        ["stripe_customer_id"],
        unique=True,
        postgresql_where=sa.text("stripe_customer_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_users_stripe_customer_id", table_name="users")
    op.drop_column("users", "subscription_status")
    op.drop_column("users", "stripe_subscription_id")
    op.drop_column("users", "stripe_customer_id")
