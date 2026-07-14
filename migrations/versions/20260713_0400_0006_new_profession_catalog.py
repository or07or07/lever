"""Remap legacy profession keys to the new 12-category catalog

Data-only migration — no schema changes. The professions registry
(professions.py) was replaced: mechanic/hvac/electrician/construction/
carwash became a 12-category catalog (home_cleaning, handyman, plumbing,
electrical, painting, construction, gardening, appliance_repair,
tech_support, beauty, automotive, moving).

Existing rows are remapped so no provider profile or service request is
left holding a key the application no longer recognizes:
  mechanic    -> automotive
  carwash     -> automotive
  hvac        -> appliance_repair
  electrician -> electrical
  construction  (unchanged — key exists in both catalogs)

The downgrade is intentionally lossy for carwash: both mechanic and
carwash map forward to automotive, so reversing maps all automotive rows
back to mechanic. That's acceptable for a downgrade path that exists only
for emergencies.

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-13 04:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_FORWARD = {
    "mechanic": "automotive",
    "carwash": "automotive",
    "hvac": "appliance_repair",
    "electrician": "electrical",
}

_REVERSE = {
    "automotive": "mechanic",  # lossy: carwash rows also come back as mechanic
    "appliance_repair": "hvac",
    "electrical": "electrician",
}


def _remap(mapping: dict[str, str]) -> None:
    conn = op.get_bind()
    for old, new in mapping.items():
        conn.execute(
            sa.text("UPDATE mechanic_profiles SET profession = :new WHERE profession = :old"),
            {"new": new, "old": old},
        )
        conn.execute(
            sa.text("UPDATE service_requests SET profession_type = :new WHERE profession_type = :old"),
            {"new": new, "old": old},
        )


def upgrade() -> None:
    _remap(_FORWARD)


def downgrade() -> None:
    _remap(_REVERSE)
