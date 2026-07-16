"""Add customer_ratings table + client_profiles aggregate columns

Professional→customer ratings (reverse of reviews) plus a cached aggregate on
client_profiles. The customer_ratings table is new (create_all would create it
on a fresh boot), but the two client_profiles columns must be added here —
create_all() never adds columns to an existing table, so this migration must
run against the live DB.

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-16 03:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "customer_ratings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("mechanic_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("client_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), server_default="", nullable=True),
        sa.Column("communication", sa.Integer(), nullable=True),
        sa.Column("punctuality", sa.Integer(), nullable=True),
        sa.Column("respect", sa.Integer(), nullable=True),
        sa.Column("request_accuracy", sa.Integer(), nullable=True),
        sa.Column("moderation_status", sa.String(length=16), server_default="visible", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_customer_ratings_client_id", "customer_ratings", ["client_id"])

    op.add_column("client_profiles", sa.Column("avg_rating", sa.Float(), server_default="0", nullable=False))
    op.add_column("client_profiles", sa.Column("total_ratings", sa.Integer(), server_default="0", nullable=False))


def downgrade() -> None:
    op.drop_column("client_profiles", "total_ratings")
    op.drop_column("client_profiles", "avg_rating")
    op.drop_index("ix_customer_ratings_client_id", table_name="customer_ratings")
    op.drop_table("customer_ratings")
