"""Add terms/privacy acceptance tracking and account-deletion marker to users

Adds three columns to the existing `users` table only — deliberately does
NOT touch any other table, since most of the schema past revision 0001 was
brought up via Base.metadata.create_all() at app startup rather than
incremental migrations (create_all only creates missing tables; it never
alters an existing one, which is why this needs a real migration).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-13 00:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic
revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("terms_accepted_version", sa.String(length=20), nullable=True))
    op.add_column("users", sa.Column("terms_accepted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "terms_accepted_at")
    op.drop_column("users", "terms_accepted_version")
