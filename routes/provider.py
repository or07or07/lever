"""Lever - Provider routes: profile, job board, job management.

Works for all professions (mechanic, HVAC, electrician, construction, car wash).
The job board is filtered by the provider's profession.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from auth import require_provider
from database import get_db
from models import Job, MechanicProfile, Notification, ServiceRequest, User
from professions import get_job_statuses
from routes.moderation import blocked_user_ids_involving, is_blocked_pair
from schemas import (
    JobDetail,
    JobOut,
    JobStatusUpdate,
    MechanicProfileOut,
    MechanicProfileUpdate,
    MessageResponse,
    ReviewOut,
    ServiceRequestBoardOut,
)

logger = logging.getLogger("lever.provider")

router = APIRouter(prefix="/api/provider", tags=["provider"])


# ---------------------------------------------------------------------------
# Helpers - notification creation
# ---------------------------------------------------------------------------

# Human-readable status messages for client notifications
_STATUS_MESSAGES = {
    "en_route": "is on the way to your location",
    "diagnosing": "has arrived and is diagnosing the issue",
    "repairing": "has started the repair work",
    "inspecting": "has arrived and is inspecting",
    "servicing": "has started servicing",
    "working": "has started working on your project",
    "assessing": "has arrived and is assessing the job",
    "prepping": "is prepping your vehicle",
    "washing": "is washing your vehicle",
    "completed": "has completed the job - please leave a review!",
    "cancelled": "has cancelled the job",
}

# Next-step guidance for the worker after each status transition
_WORKER_NEXT_STEPS = {
    "accepted": "Head to the client's location and update your status to 'En Route' when you leave.",
    "en_route": "Once you arrive, update your status to begin the work phase.",
    "diagnosing": "Diagnose the issue and update your status when you start repairs.",
    "repairing": "Complete the repair and mark the job as 'Completed' when done.",
    "inspecting": "Complete the inspection and update your status when you start work.",
    "servicing": "Complete the service and mark the job as 'Completed' when done.",
    "working": "Complete the work and mark the job as 'Completed' when done.",
    "assessing": "Complete the assessment and update your status when you start work.",
    "prepping": "Finish prepping and update your status to start washing.",
    "washing": "Complete the wash and mark the job as 'Completed' when done.",
    "completed": "Job complete! Wait for the client's review.",
}


def _create_notification(
    db: Session,
    user_id: int,
    notif_type: str,
    title: str,
    message: str,
    link: str | None = None,
) -> Notification:
    """Create and add a notification to the session (caller must commit)."""
    notif = Notification(
        user_id=user_id,
        type=notif_type,
        title=title,
        message=message,
        link=link,
    )
    db.add(notif)
    logger.info(f"Notification created: user={user_id} type={notif_type} title={title!r}")
    return notif


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile", response_model=MechanicProfileOut)
def get_profile(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    profile = db.query(MechanicProfile).filter(
        MechanicProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.patch("/profile", response_model=MechanicProfileOut)
def update_profile(
    payload: MechanicProfileUpdate,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    profile = db.query(MechanicProfile).filter(
        MechanicProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Active Status Toggle
# ---------------------------------------------------------------------------

@router.post("/go-online", response_model=MechanicProfileOut)
def go_online(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """Toggle provider to ONLINE — ready to receive job dispatch."""
    profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.is_online = True
    profile.last_heartbeat = datetime.now(timezone.utc)
    db.commit()
    db.refresh(profile)
    logger.info(f"Provider {current_user.id} went ONLINE")
    return profile


@router.post("/go-offline", response_model=MechanicProfileOut)
def go_offline(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """Toggle provider to OFFLINE — stop receiving job dispatch."""
    profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.is_online = False
    db.commit()
    db.refresh(profile)
    logger.info(f"Provider {current_user.id} went OFFLINE")
    return profile


@router.post("/heartbeat")
def heartbeat(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """Update heartbeat timestamp. Call every 60s from client app.
    If no heartbeat for 5 minutes, provider auto-goes offline."""
    profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.last_heartbeat = datetime.now(timezone.utc)
    if not profile.is_online:
        profile.is_online = True
    db.commit()
    return {"status": "ok", "is_online": True}


# ---------------------------------------------------------------------------
# Job Board - filtered by provider's profession
# ---------------------------------------------------------------------------

@router.get("/board", response_model=List[ServiceRequestBoardOut])
def job_board(
    urgency: Optional[str] = Query(default=None),
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """List pending service requests matching this provider's profession.
    Only available to providers who are currently ONLINE."""
    profile = db.query(MechanicProfile).filter(
        MechanicProfile.user_id == current_user.id
    ).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Must be online to see the board
    if not profile.is_online:
        raise HTTPException(
            status_code=403,
            detail="You must go online to view available job requests. Use POST /api/provider/go-online first."
        )

    profession = profile.profession if profile else "mechanic"
    q = db.query(ServiceRequest).filter(
        ServiceRequest.status == "pending",
        ServiceRequest.profession_type == profession,
    )
    if urgency:
        q = q.filter(ServiceRequest.urgency == urgency)

    # Never surface requests from a client either side has blocked.
    blocked_ids = blocked_user_ids_involving(db, current_user.id)
    if blocked_ids:
        q = q.filter(ServiceRequest.client_id.notin_(blocked_ids))

    return q.order_by(ServiceRequest.created_at.asc()).all()


# ---------------------------------------------------------------------------
# Accept a request (creates a Job)
# ---------------------------------------------------------------------------

@router.post("/board/{request_id}/accept", response_model=JobOut, status_code=status.HTTP_201_CREATED)
def accept_request(
    request_id: int,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    req = db.query(ServiceRequest).filter(ServiceRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Service request not found")
    if req.status != "pending":
        raise HTTPException(status_code=409, detail="Request is no longer available")
    if is_blocked_pair(db, current_user.id, req.client_id):
        raise HTTPException(status_code=403, detail="You cannot accept a request from this client")

    # Verify profession match
    profile = db.query(MechanicProfile).filter(
        MechanicProfile.user_id == current_user.id
    ).first()
    if profile and profile.profession != req.profession_type:
        raise HTTPException(
            status_code=400,
            detail=f"This request requires a {req.profession_type} professional"
        )

    existing = db.query(Job).filter(Job.request_id == request_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Request already accepted")

    # Must be online to accept requests
    if not (profile and profile.is_online):
        raise HTTPException(
            status_code=403,
            detail="You must be online to accept job requests."
        )

    job = Job(request_id=request_id, mechanic_id=current_user.id)
    db.add(job)
    req.status = "assigned"
    db.flush()  # Get job.id before creating notifications

    # ── Notify the CLIENT that their request was accepted ──
    provider_name = profile.full_name if profile and profile.full_name else "A professional"
    profession_label = profile.profession.replace("_", " ").title() if profile else "Professional"

    _create_notification(
        db,
        user_id=req.client_id,
        notif_type="job_update",
        title=f"Your request has been accepted!",
        message=(
            f"{provider_name} ({profession_label}) has accepted your request "
            f"\"{req.title}\" and is now processing it. "
            f"You can message them directly from your request details."
        ),
        link=f"/client/requests/{req.id}",
    )

    # ── Notify the WORKER with next steps ──
    next_step = _WORKER_NEXT_STEPS.get("accepted", "Check the job details for next steps.")
    _create_notification(
        db,
        user_id=current_user.id,
        notif_type="job_update",
        title="Job accepted - here are your next steps",
        message=(
            f"You accepted \"{req.title}\". "
            f"Next step: {next_step} "
            f"You can message the client from the job details page."
        ),
        link=f"/provider/jobs/{job.id}",
    )

    db.commit()
    db.refresh(job)

    # Cancel any pending dispatch for this request since it's now accepted
    from dispatch import cancel_dispatch_for_request
    cancel_dispatch_for_request(db, request_id)

    return job


# ---------------------------------------------------------------------------
# My Jobs
# ---------------------------------------------------------------------------

@router.get("/jobs", response_model=List[JobDetail])
def list_my_jobs(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    q = (
        db.query(Job)
        .options(joinedload(Job.request))
        .filter(Job.mechanic_id == current_user.id)
    )
    if status_filter:
        q = q.filter(Job.status == status_filter)
    return q.order_by(Job.created_at.desc()).all()


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(
    job_id: int,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    job = (
        db.query(Job)
        .options(joinedload(Job.request))
        .filter(Job.id == job_id, Job.mechanic_id == current_user.id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.patch("/jobs/{job_id}/status", response_model=JobOut)
def update_job_status(
    job_id: int,
    payload: JobStatusUpdate,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    job = db.query(Job).filter(
        Job.id == job_id,
        Job.mechanic_id == current_user.id,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail="Job is already finalised")

    # Get profession-specific job statuses for validation
    req = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
    profession_type = req.profession_type if req else "mechanic"
    statuses = get_job_statuses(profession_type)

    # Build allowed transitions dynamically from profession's status flow
    # Each status can transition to the next status in the flow, or to "cancelled"
    _ALLOWED_TRANSITIONS = {}
    work_statuses = [s for s in statuses if s not in ("completed", "cancelled")]
    for i, st in enumerate(work_statuses):
        next_statuses = set()
        if i + 1 < len(work_statuses):
            next_statuses.add(work_statuses[i + 1])
        else:
            next_statuses.add("completed")
        next_statuses.add("cancelled")
        _ALLOWED_TRANSITIONS[st] = next_statuses

    allowed = _ALLOWED_TRANSITIONS.get(job.status, set())
    if payload.status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition from '{job.status}' to '{payload.status}'. "
                   f"Allowed: {sorted(allowed)}",
        )

    # Start work on the 3rd status (the "working" phase)
    if len(work_statuses) >= 3 and payload.status == work_statuses[2] and not job.started_at:
        job.started_at = datetime.utcnow()
    if payload.status == "completed":
        job.completed_at = datetime.utcnow()
        if req:
            req.status = "completed"

    job.status = payload.status
    if payload.mechanic_notes is not None:
        job.mechanic_notes = payload.mechanic_notes
    if payload.final_price is not None:
        job.final_price = payload.final_price

    # ── Notify the CLIENT of the status change ──
    if req:
        status_msg = _STATUS_MESSAGES.get(
            payload.status,
            f"updated job status to {payload.status.replace('_', ' ').title()}"
        )
        status_title = payload.status.replace("_", " ").title()
        _create_notification(
            db,
            user_id=req.client_id,
            notif_type="job_update",
            title=f"Job update: {status_title}",
            message=f"Your service provider {status_msg}.",
            link=f"/client/requests/{req.id}",
        )

    # ── Notify the WORKER with next steps ──
    next_step = _WORKER_NEXT_STEPS.get(payload.status)
    if next_step:
        _create_notification(
            db,
            user_id=current_user.id,
            notif_type="job_update",
            title=f"Status updated to {payload.status.replace('_', ' ').title()}",
            message=f"Next step: {next_step}",
            link=f"/provider/jobs/{job.id}",
        )

    db.commit()
    db.refresh(job)
    return job


# ---------------------------------------------------------------------------
# Reviews received
# ---------------------------------------------------------------------------

@router.get("/reviews", response_model=List[ReviewOut])
def my_reviews(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    from models import Review
    return (
        db.query(Review)
        .filter(Review.mechanic_id == current_user.id)
        .order_by(Review.created_at.desc())
        .all()
    )
