"""Add market_code to service_requests (Guayaquil launch)

Adds one nullable column to the existing service_requests table. Set
server-side by market.validate_service_location() when a request is
created; NULL only on legacy pre-launch rows. Same operational note as
every prior column migration — create_all() won't retrofit it, so this
must actually run in production.

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-14 01:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("service_requests", sa.Column("market_code", sa.String(length=10), nullable=True))
    op.create_index("ix_service_requests_market_code", "service_requests", ["market_code"])


def downgrade() -> None:
    op.drop_index("ix_service_requests_market_code", table_name="service_requests")
    op.drop_column("service_requests", "market_code")
