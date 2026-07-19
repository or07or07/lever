"""Worker-set pricing Phase 1: quote snapshot on jobs

The professional's hourly rate × the service's catalog duration produces a
quote range; it is snapshotted onto the Job at accept time (rates can change
later — the client hires against THIS quote) and the final price is enforced
inside it at completion. IDEMPOTENT: skips columns that already exist
(create_all on a fresh DB builds them from the model).

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-19 01:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("jobs")}
    if "quoted_min" not in cols:
        op.add_column("jobs", sa.Column("quoted_min", sa.Float(), nullable=True))
    if "quoted_max" not in cols:
        op.add_column("jobs", sa.Column("quoted_max", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "quoted_max")
    op.drop_column("jobs", "quoted_min")
