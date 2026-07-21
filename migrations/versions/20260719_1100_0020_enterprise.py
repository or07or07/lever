"""Enterprise foundation: companies, company_members, subscriptions

Companies send their own employees; the company is the reputation umbrella and
the subscriber. Subscriptions are billing-ready but inert until a processor is
wired. IDEMPOTENT: skips any table that already exists (create_all builds them
on a fresh DB).

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-19 11:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if "companies" not in tables:
        op.create_table(
            "companies",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("name", sa.String(length=200), nullable=False),
            sa.Column("ruc", sa.String(length=20), nullable=True, server_default=""),
            sa.Column("contact_email", sa.String(length=255), nullable=True, server_default=""),
            sa.Column("contact_phone", sa.String(length=30), nullable=True, server_default=""),
            sa.Column("description", sa.Text(), nullable=True, server_default=""),
            sa.Column("logo_url", sa.String(length=500), nullable=True, server_default=""),
            sa.Column("avg_rating", sa.Float(), nullable=True, server_default="0"),
            sa.Column("total_jobs", sa.Integer(), nullable=True, server_default="0"),
            sa.Column("verification_status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    if "company_members" not in tables:
        op.create_table(
            "company_members",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False, server_default="employee"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        op.create_index("ix_company_members_unique", "company_members", ["company_id", "user_id"], unique=True)
        op.create_index("ix_company_members_company_id", "company_members", ["company_id"])
        op.create_index("ix_company_members_user_id", "company_members", ["user_id"])

    if "subscriptions" not in tables:
        op.create_table(
            "subscriptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("subject_type", sa.String(length=20), nullable=False),
            sa.Column("subject_id", sa.Integer(), nullable=False),
            sa.Column("tier", sa.String(length=30), nullable=False, server_default="free"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="inactive"),
            sa.Column("trial_ends_at", sa.DateTime(), nullable=True),
            sa.Column("current_period_end", sa.DateTime(), nullable=True),
            sa.Column("processor", sa.String(length=30), nullable=True, server_default=""),
            sa.Column("processor_ref", sa.String(length=255), nullable=True, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_subscriptions_subject", "subscriptions", ["subject_type", "subject_id"])


def downgrade() -> None:
    op.drop_table("subscriptions")
    op.drop_table("company_members")
    op.drop_table("companies")
