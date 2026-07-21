"""Lever — Community suggestions.

The inbound half of the product trust loop (Novedades is the outbound half).
Anyone may submit; signed-in submitters get their idea attributed so they can
watch its status. Admin triage lives in routes/admin.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from auth import get_current_user, get_optional_user
from database import get_db
from models import Suggestion, User
from schemas import MessageResponse

router = APIRouter(prefix="/api/suggestions", tags=["suggestions"])

# Kept in lockstep with the frontend's category chips. Aligned with the app's
# pillars: fair pricing, professional quality, the experience, breadth of
# services, and trust/safety.
ALLOWED_CATEGORIES = {
    "pricing", "professionals", "app_experience", "new_service", "safety", "other",
}
ALLOWED_STATUSES = {"new", "reviewing", "planned", "completed", "declined"}


class SuggestionIn(BaseModel):
    category: str = Field(default="other", max_length=40)
    message: str = Field(min_length=5, max_length=2000)
    email: Optional[str] = Field(default=None, max_length=255)


class SuggestionOut(BaseModel):
    """Submitter-facing shape — deliberately WITHOUT admin_notes."""
    id: int
    category: str
    message: str
    status: str
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


@router.post("", response_model=MessageResponse, status_code=201)
def create_suggestion(
    payload: SuggestionIn,
    current_user: Optional[User] = Depends(get_optional_user),
    db: Session = Depends(get_db),
):
    category = payload.category if payload.category in ALLOWED_CATEGORIES else "other"
    message = payload.message.strip()
    if len(message) < 5:
        raise HTTPException(status_code=422, detail="Message is too short")
    # Signed-in submitters are attributed; guests may leave an email so we can
    # follow up. We never require personal data to be heard.
    email = ""
    if current_user is None and payload.email:
        email = payload.email.strip()[:255]
    row = Suggestion(
        user_id=current_user.id if current_user else None,
        email=email,
        category=category,
        message=message,
    )
    db.add(row)
    db.commit()
    return MessageResponse(message="Suggestion received")


@router.get("/mine", response_model=List[SuggestionOut])
def my_suggestions(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """A signed-in user's own suggestions with live status — so contributors
    can watch their idea move from 'received' to 'shipped'."""
    return (
        db.query(Suggestion)
        .filter(Suggestion.user_id == current_user.id)
        .order_by(Suggestion.created_at.desc())
        .all()
    )
