"""Add provider service selection (Phase 3 — service catalog)

Adds users.verification_level (existing table — must actually run, same
note as every prior column-adding migration). Creates the new
provider_services table (new table, so create_all() would also make it
on a from-scratch database, but this keeps Alembic's version state
accurate on the already-existing production database).

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-14 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("verification_level", sa.String(length=20), server_default="none", nullable=False),
    )

    op.create_table(
        "provider_services",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("provider_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("service_key", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_provider_services_provider_user_id", "provider_services", ["provider_user_id"])
    op.create_index(
        "ix_provider_services_unique", "provider_services", ["provider_user_id", "service_key"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_provider_services_unique", table_name="provider_services")
    op.drop_index("ix_provider_services_provider_user_id", table_name="provider_services")
    op.drop_table("provider_services")
    op.drop_column("users", "verification_level")
