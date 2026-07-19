"""Worker-set pricing Phase 2: client chooses a professional

Adds service_requests.preferred_provider_id — when set, dispatch offers the
request ONLY to that professional (the client hired them directly from the
browse screen). Cleared by the "send to everyone" fallback. IDEMPOTENT:
skips the column if it already exists (create_all on a fresh DB builds it
from the model).

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-19 03:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("service_requests")}
    if "preferred_provider_id" not in cols:
        op.add_column(
            "service_requests",
            sa.Column("preferred_provider_id", sa.Integer(), nullable=True),
        )


def downgrade() -> None:
    op.drop_column("service_requests", "preferred_provider_id")
