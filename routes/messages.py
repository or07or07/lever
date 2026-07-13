"""Lever — Message routes: job-scoped chat between client and provider."""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Job, Message, ServiceRequest, User
from routes.moderation import is_blocked_pair
from schemas import MessageCreate, MessageOut

router = APIRouter(prefix="/api/messages", tags=["messages"])


@router.get("/job/{job_id}", response_model=List[MessageOut])
def get_messages(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    req = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
    if not (
        current_user.id == job.mechanic_id
        or (req and current_user.id == req.client_id)
        or current_user.role == "admin"
    ):
        raise HTTPException(status_code=403, detail="Not authorised for this job")

    msgs = db.query(Message).filter(Message.job_id == job_id).order_by(Message.created_at).all()

    # Mark unread messages as read for current user
    db.query(Message).filter(
        Message.job_id == job_id,
        Message.sender_id != current_user.id,
        Message.is_read == False,
    ).update({"is_read": True})
    db.commit()

    return msgs


@router.post("/job/{job_id}", response_model=MessageOut, status_code=status.HTTP_201_CREATED)
def send_message(
    job_id: int,
    payload: MessageCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail="Cannot message on a closed job")

    req = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
    if not (
        current_user.id == job.mechanic_id
        or (req and current_user.id == req.client_id)
        or current_user.role == "admin"
    ):
        raise HTTPException(status_code=403, detail="Not authorised for this job")

    other_id = job.mechanic_id if current_user.id != job.mechanic_id else (req.client_id if req else None)
    if other_id and is_blocked_pair(db, current_user.id, other_id):
        raise HTTPException(status_code=403, detail="You cannot message this user")

    msg = Message(job_id=job_id, sender_id=current_user.id, content=payload.content)
    db.add(msg)
    db.commit()
    db.refresh(msg)
    return msg


@router.get("/unread-count")
def unread_count(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    count = (
        db.query(func.count(Message.id))
        .filter(Message.sender_id != current_user.id, Message.is_read == False)
        .join(Job, Job.id == Message.job_id)
        .filter(
            (Job.mechanic_id == current_user.id)
            | (Job.request.has(ServiceRequest.client_id == current_user.id))
        )
        .scalar()
    )
    return {"unread": count or 0}
