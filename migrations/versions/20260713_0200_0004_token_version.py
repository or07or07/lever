"""Add token_version to users for JWT revocation (GP-13)

Adds one column to the existing `users` table — same operational note as
0002: Base.metadata.create_all() only creates missing tables, it won't
add this column to a users table that already exists in production, so
this migration must actually run.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-13 02:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "token_version")
