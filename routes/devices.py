"""Lever — Device registration for push notifications.

The app registers its FCM token here after login (and unregisters on logout).
Registration is idempotent: a token that already exists is re-pointed at the
current user and its platform refreshed, so a shared/reflashed device never
leaks pushes to a previous owner.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import DeviceToken, User
from schemas import MessageResponse

router = APIRouter(prefix="/api/devices", tags=["devices"])


class DeviceRegisterIn(BaseModel):
    token: str = Field(min_length=8, max_length=512)
    platform: str = Field(default="android", pattern="^(android|ios|web)$")


class DeviceUnregisterIn(BaseModel):
    token: str = Field(min_length=8, max_length=512)


@router.post("/register", response_model=MessageResponse)
def register_device(
    payload: DeviceRegisterIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    row = db.query(DeviceToken).filter(DeviceToken.token == payload.token).first()
    if row:
        row.user_id = current_user.id
        row.platform = payload.platform
        row.updated_at = datetime.now(timezone.utc)
    else:
        db.add(DeviceToken(
            user_id=current_user.id, token=payload.token, platform=payload.platform
        ))
    db.commit()
    return MessageResponse(message="Device registered")


@router.post("/unregister", response_model=MessageResponse)
def unregister_device(
    payload: DeviceUnregisterIn,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Only the owner may remove their own token.
    db.query(DeviceToken).filter(
        DeviceToken.token == payload.token,
        DeviceToken.user_id == current_user.id,
    ).delete(synchronize_session=False)
    db.commit()
    return MessageResponse(message="Device unregistered")
