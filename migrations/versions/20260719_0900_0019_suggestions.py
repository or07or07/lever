"""Community suggestions table

The inbound half of the trust loop: anyone can submit a product suggestion,
the admin triages it through a lifecycle. IDEMPOTENT: skips creation if the
table already exists (create_all builds it on a fresh DB).

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-19 09:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "suggestions" in insp.get_table_names():
        return
    op.create_table(
        "suggestions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(),
                  sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True, server_default=""),
        sa.Column("category", sa.String(length=40), nullable=False, server_default="other"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="new"),
        sa.Column("admin_notes", sa.Text(), nullable=True, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False,
                  server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_suggestions_user_id", "suggestions", ["user_id"])
    op.create_index("ix_suggestions_status", "suggestions", ["status"])


def downgrade() -> None:
    op.drop_table("suggestions")
