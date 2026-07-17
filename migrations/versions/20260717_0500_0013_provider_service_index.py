"""Index provider_services by (service_key, is_active) for exact-service matching

Multi-profession matching looks up providers by exact service — "who offers
service_key X and has it active?" — so add a supporting index.

Revision ID: 0013
Revises: 0012
Create Date: 2026-07-17 05:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IDEMPOTENT: on a fresh database create_all() creates this index from the
    # model's __table_args__, so create it only when missing.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    existing = {ix["name"] for ix in insp.get_indexes("provider_services")}
    if "ix_provider_services_service_active" not in existing:
        op.create_index(
            "ix_provider_services_service_active",
            "provider_services",
            ["service_key", "is_active"],
        )


def downgrade() -> None:
    op.drop_index("ix_provider_services_service_active", table_name="provider_services")
