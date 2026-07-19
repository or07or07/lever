"""Worker-set pricing Phase 3: metered hourly billing + overtime approvals

The clock is the app, not the worker's word: billing runs from "Iniciar
trabajo" to "Completar trabajo" at the professional's snapshotted hourly
rate, clamped between the quoted minimum and the quoted maximum plus any
client-approved extra time. IDEMPOTENT: skips columns that already exist.

Revision ID: 0017
Revises: 0016
Create Date: 2026-07-19 05:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS = (
    ("hourly_rate_snapshot", sa.Float(), None),
    ("billed_minutes", sa.Integer(), None),
    ("client_confirmed_start_at", sa.DateTime(), None),
    ("extra_minutes_requested", sa.Integer(), None),
    ("extra_minutes_approved", sa.Integer(), None),
)


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("jobs")}
    for name, coltype, _ in _COLS:
        if name not in cols:
            op.add_column("jobs", sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    for name, _, _ in reversed(_COLS):
        op.drop_column("jobs", name)
