"""Add city_interest table (future-market interest capture)

New table for visitors outside Guayaquil who ask for Lever in their city.
Only written with explicit consent (see routes). Brand-new table, but run
this to keep Alembic's version state accurate on the existing prod DB.

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-14 02:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "city_interest",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("city", sa.String(length=120), nullable=False),
        sa.Column("province", sa.String(length=120), server_default="", nullable=True),
        sa.Column("service_category", sa.String(length=80), server_default="", nullable=True),
        sa.Column("contact", sa.String(length=255), server_default="", nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("city_interest")
