"""Lever — Notification routes.

Provides in-app notifications for job updates, messages, reviews, and system alerts.

CIA Triad:
  Confidentiality: Notifications scoped to authenticated user only
  Integrity:       Read status tracked per user; bulk mark-read validated
  Availability:    Paginated queries; unread count endpoint for polling
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Notification, User
from schemas import NotificationMarkRead, NotificationOut, MessageResponse

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("", response_model=List[NotificationOut])
def list_notifications(
    unread_only: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List notifications for the current user."""
    q = db.query(Notification).filter(Notification.user_id == current_user.id)
    if unread_only:
        q = q.filter(Notification.is_read == False)
    return q.order_by(Notification.created_at.desc()).offset(offset).limit(limit).all()


@router.get("/count")
def unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get unread notification count (for badge display)."""
    count = (
        db.query(func.count(Notification.id))
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .scalar()
    )
    return {"unread_count": count}


@router.post("/mark-read", response_model=MessageResponse)
def mark_read(
    payload: NotificationMarkRead,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark specific notifications as read."""
    updated = (
        db.query(Notification)
        .filter(
            Notification.id.in_(payload.notification_ids),
            Notification.user_id == current_user.id,
        )
        .update({"is_read": True}, synchronize_session="fetch")
    )
    db.commit()
    return MessageResponse(message=f"{updated} notifications marked as read")


@router.post("/mark-all-read", response_model=MessageResponse)
def mark_all_read(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Mark all notifications as read."""
    updated = (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id, Notification.is_read == False)
        .update({"is_read": True}, synchronize_session="fetch")
    )
    db.commit()
    return MessageResponse(message=f"{updated} notifications marked as read")
