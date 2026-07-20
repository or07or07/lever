"""Push notifications: device_tokens table

One row per device a user registered for FCM push, so offers/updates can
reach a closed app. IDEMPOTENT: skips creation if the table already exists
(create_all builds it on a fresh DB).

Revision ID: 0018
Revises: 0017
Create Date: 2026-07-19 07:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "device_tokens" in insp.get_table_names():
        return
    op.create_table(
        "device_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token", sa.String(length=512), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False, server_default="android"),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_device_tokens_user_id", "device_tokens", ["user_id"])
    op.create_unique_constraint("uq_device_tokens_token", "device_tokens", ["token"])


def downgrade() -> None:
    op.drop_table("device_tokens")
