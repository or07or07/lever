"""Simplified job flow: arrival window + client completion confirmation

Adds jobs.arrival_deadline (set when the professional accepts — they have a
fixed window to reach the site) and jobs.client_confirmed_at (the client must
confirm the work is done before the job can be rated; ratings drive dispatch
priority). IDEMPOTENT: skips columns that already exist (create_all on a fresh
DB builds them from the model).

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-18 06:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("jobs")}
    if "arrival_deadline" not in cols:
        op.add_column("jobs", sa.Column("arrival_deadline", sa.DateTime(), nullable=True))
    if "client_confirmed_at" not in cols:
        op.add_column("jobs", sa.Column("client_confirmed_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "client_confirmed_at")
    op.drop_column("jobs", "arrival_deadline")
