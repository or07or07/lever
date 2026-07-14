"""Add admin MFA / TOTP columns to users (GP-14)

Adds three columns to the existing `users` table — same operational note
as 0002/0004: Base.metadata.create_all() only creates missing tables, it
won't retrofit these onto a users table that already exists in
production, so this migration must actually run.

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-13 03:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("mfa_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("users", sa.Column("mfa_secret", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("mfa_backup_codes", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "mfa_backup_codes")
    op.drop_column("users", "mfa_secret")
    op.drop_column("users", "mfa_enabled")
