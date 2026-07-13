"""Add reports and blocks tables (content moderation, GP-08)

Both are brand-new tables, so Base.metadata.create_all() would actually
create them too on a fresh boot — unlike 0002, this migration isn't
strictly load-bearing for an empty database. It still needs to run for
the same reason 0002 does: on a database that already exists in
production, create_all() only fills in tables that are missing, and
running this explicitly keeps Alembic's version table an accurate record
of what's actually been applied.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-13 01:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    report_entity_enum = sa.Enum(
        "user", "message", "review", "service_request", name="report_entity_enum"
    )
    report_category_enum = sa.Enum(
        "spam", "harassment", "fraud", "inappropriate", "safety", "other",
        name="report_category_enum",
    )
    report_status_enum = sa.Enum(
        "open", "reviewing", "resolved", "dismissed", name="report_status_enum"
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reported_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_type", report_entity_enum, nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("category", report_category_enum, nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=True),
        sa.Column("status", report_status_enum, server_default="open", nullable=False),
        sa.Column("admin_notes", sa.Text(), server_default="", nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_reports_status", "reports", ["status"])
    op.create_index("ix_reports_reported_user", "reports", ["reported_user_id"])

    op.create_table(
        "blocks",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("blocker_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("blocked_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_blocks_blocker_blocked", "blocks", ["blocker_id", "blocked_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_blocks_blocker_blocked", table_name="blocks")
    op.drop_table("blocks")

    op.drop_index("ix_reports_reported_user", table_name="reports")
    op.drop_index("ix_reports_status", table_name="reports")
    op.drop_table("reports")

    # Drop the enum types explicitly (PostgreSQL only — SQLite ignores this)
    sa.Enum(name="report_status_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="report_category_enum").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="report_entity_enum").drop(op.get_bind(), checkfirst=True)
