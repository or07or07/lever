"""Add service_key + structured answers to service_requests (catalog Phase 2)

Adds two nullable columns to the existing `service_requests` table:
  service_key — which catalog service (services_catalog.py) the request is
                for; NULL means a legacy/free-text request, so every
                existing row keeps working unchanged.
  answers     — JSON responses to the service's dynamic-form questions.

Same operational note as 0002/0004/0005: create_all() won't retrofit
columns onto an existing table, this must actually run in production.

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-13 05:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("service_requests", sa.Column("service_key", sa.String(length=80), nullable=True))
    op.add_column("service_requests", sa.Column("answers", sa.JSON(), nullable=True))
    op.create_index("ix_service_requests_service_key", "service_requests", ["service_key"])


def downgrade() -> None:
    op.drop_index("ix_service_requests_service_key", table_name="service_requests")
    op.drop_column("service_requests", "answers")
    op.drop_column("service_requests", "service_key")
