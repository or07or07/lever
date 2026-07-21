"""Lever — Subscription helpers (billing-ready, inert until a processor ships).

A subject (a provider user, or a company) has at most one Subscription row.
Entitlements derive purely from status — nothing here charges money. When the
payment integration lands it only needs to flip status/current_period_end and
populate processor/processor_ref; every gate in the app already reads through
subscription_active().

Tiers:
  provider: 'free' (default) | 'pro'
  company:  'enterprise'
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from models import Subscription

ACTIVE_STATUSES = ("trial", "active")


def _as_utc(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_subscription(db: Session, subject_type: str, subject_id: int) -> Optional[Subscription]:
    return (
        db.query(Subscription)
        .filter(Subscription.subject_type == subject_type, Subscription.subject_id == subject_id)
        .order_by(Subscription.id.desc())
        .first()
    )


def ensure_subscription(
    db: Session, subject_type: str, subject_id: int, tier: str, status: str = "inactive"
) -> Subscription:
    """Get-or-create the subject's subscription row. Individual providers get a
    'free' row lazily; companies get an 'enterprise' row at sign-up."""
    sub = get_subscription(db, subject_type, subject_id)
    if sub:
        return sub
    sub = Subscription(subject_type=subject_type, subject_id=subject_id, tier=tier, status=status)
    db.add(sub)
    db.flush()
    return sub


def subscription_active(sub: Optional[Subscription]) -> bool:
    """True when the subscription entitles paid features RIGHT NOW. A 'free'
    provider tier is never 'active' in the paid sense — it's the baseline."""
    if not sub or sub.status not in ACTIVE_STATUSES:
        return False
    end = _as_utc(sub.current_period_end)
    if end is not None and end < datetime.now(timezone.utc):
        return False
    return True


def subscription_public(sub: Optional[Subscription]) -> dict:
    """JSON-safe view for the app — never exposes processor internals."""
    if not sub:
        return {"tier": "free", "status": "inactive", "active": False, "current_period_end": None}
    return {
        "tier": sub.tier,
        "status": sub.status,
        "active": subscription_active(sub),
        "current_period_end": sub.current_period_end.isoformat() if sub.current_period_end else None,
        "trial_ends_at": sub.trial_ends_at.isoformat() if sub.trial_ends_at else None,
    }
