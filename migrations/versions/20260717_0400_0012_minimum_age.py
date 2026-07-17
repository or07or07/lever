"""Add minimum-age (18+) fields to users

Adds date_of_birth (DATE), age_verified_at and minimum_age_policy_version.
All three are NULLABLE on purpose: existing accounts predate the policy and
must NOT be deleted or suspended by this migration — they are handled by a
separate, phased age-verification flow (see docs/minimum-age.md).

create_all() never adds columns to an existing table, so this migration must
run against the live database.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-17 04:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # IDEMPOTENT: on a fresh database create_all() creates users WITH these
    # columns already, so add them only when missing.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("users")}
    if "date_of_birth" not in cols:
        op.add_column("users", sa.Column("date_of_birth", sa.Date(), nullable=True))
    if "age_verified_at" not in cols:
        op.add_column("users", sa.Column("age_verified_at", sa.DateTime(), nullable=True))
    if "minimum_age_policy_version" not in cols:
        op.add_column("users", sa.Column("minimum_age_policy_version", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "minimum_age_policy_version")
    op.drop_column("users", "age_verified_at")
    op.drop_column("users", "date_of_birth")
