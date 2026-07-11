"""Lever — Dispute routes: raise disputes on jobs."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import require_client_or_mechanic
from database import get_db
from models import Dispute, Job, ServiceRequest, User
from schemas import DisputeCreate, DisputeOut

router = APIRouter(prefix="/api/disputes", tags=["disputes"])


@router.post("/job/{job_id}", response_model=DisputeOut, status_code=status.HTTP_201_CREATED)
def raise_dispute(
    job_id: int,
    payload: DisputeCreate,
    current_user: User = Depends(require_client_or_mechanic),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    req = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
    if not (current_user.id == job.mechanic_id or (req and current_user.id == req.client_id)):
        raise HTTPException(status_code=403, detail="Only job participants can raise disputes")

    existing = db.query(Dispute).filter(Dispute.job_id == job_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Dispute already exists for this job")

    dispute = Dispute(
        job_id=job_id,
        raised_by_id=current_user.id,
        description=payload.description,
    )
    db.add(dispute)
    db.commit()
    db.refresh(dispute)
    return dispute
