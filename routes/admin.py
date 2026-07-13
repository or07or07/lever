"""Lever — Admin routes: users, disputes, platform stats."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from auth import require_admin
from database import get_db
from models import Dispute, Job, MechanicProfile, Report, Review, ServiceRequest, User
from schemas import (
    AdminStats,
    DisputeAdminUpdate,
    DisputeOut,
    MessageResponse,
    PaginatedUsers,
    ReportAdminUpdate,
    ReportOut,
    UserAdminUpdate,
    UserOut,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Dashboard Stats
# ---------------------------------------------------------------------------

@router.get("/stats", response_model=AdminStats)
def platform_stats(
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    total_users = db.query(func.count(User.id)).scalar()
    total_clients = db.query(func.count(User.id)).filter(User.role == "client").scalar()
    total_mechanics = db.query(func.count(User.id)).filter(User.role == "mechanic").scalar()
    total_requests = db.query(func.count(ServiceRequest.id)).scalar()
    open_requests = (
        db.query(func.count(ServiceRequest.id))
        .filter(ServiceRequest.status == "pending")
        .scalar()
    )
    active_jobs = (
        db.query(func.count(Job.id))
        .filter(Job.status.in_(["accepted", "en_route", "diagnosing", "repairing",
                                "inspecting", "servicing", "working", "assessing",
                                "prepping", "washing"]))
        .scalar()
    )
    completed_jobs = (
        db.query(func.count(Job.id)).filter(Job.status == "completed").scalar()
    )
    open_disputes = (
        db.query(func.count(Dispute.id))
        .filter(Dispute.status.in_(["open", "reviewing"]))
        .scalar()
    )
    open_reports = (
        db.query(func.count(Report.id))
        .filter(Report.status.in_(["open", "reviewing"]))
        .scalar()
    )
    total_reviews = db.query(func.count(Review.id)).scalar()
    avg_rating_row = db.query(func.avg(Review.rating)).scalar()
    avg_rating = round(float(avg_rating_row or 0), 2)

    return AdminStats(
        total_users=total_users,
        total_clients=total_clients,
        total_mechanics=total_mechanics,
        total_service_requests=total_requests,
        open_requests=open_requests,
        active_jobs=active_jobs,
        completed_jobs=completed_jobs,
        open_disputes=open_disputes,
        open_reports=open_reports,
        total_reviews=total_reviews,
        avg_platform_rating=avg_rating,
    )


# ---------------------------------------------------------------------------
# User Management
# ---------------------------------------------------------------------------

@router.get("/users", response_model=PaginatedUsers)
def list_users(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=100),
    role: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(User)
    if role:
        q = q.filter(User.role == role)
    if search:
        q = q.filter(User.email.ilike(f"%{search}%"))

    total = q.count()
    users = q.offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedUsers(total=total, page=page, page_size=page_size, items=users)


@router.get("/users/{user_id}", response_model=UserOut)
def get_user(
    user_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserAdminUpdate,
    current_admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.id == current_admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(user, field, value)

    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Service Requests (admin view — all)
# ---------------------------------------------------------------------------

@router.get("/requests")
def all_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    profession_type: Optional[str] = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(ServiceRequest)
    if status_filter:
        q = q.filter(ServiceRequest.status == status_filter)
    if profession_type:
        q = q.filter(ServiceRequest.profession_type == profession_type)
    total = q.count()
    items = q.order_by(ServiceRequest.created_at.desc()).offset((page - 1) * page_size).limit(page_size).all()
    from schemas import ServiceRequestOut
    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [ServiceRequestOut.model_validate(r) for r in items],
    }


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------

@router.get("/disputes", response_model=List[DisputeOut])
def list_disputes(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Dispute)
    if status_filter:
        q = q.filter(Dispute.status == status_filter)
    return q.order_by(Dispute.created_at.asc()).all()


@router.get("/disputes/{dispute_id}", response_model=DisputeOut)
def get_dispute(
    dispute_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    d = db.get(Dispute, dispute_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dispute not found")
    return d


@router.patch("/disputes/{dispute_id}", response_model=DisputeOut)
def resolve_dispute(
    dispute_id: int,
    payload: DisputeAdminUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    d = db.get(Dispute, dispute_id)
    if not d:
        raise HTTPException(status_code=404, detail="Dispute not found")

    d.status = payload.status
    if payload.admin_notes is not None:
        d.admin_notes = payload.admin_notes
    if payload.status == "resolved":
        from datetime import datetime
        d.resolved_at = datetime.utcnow()

    db.commit()
    db.refresh(d)
    return d


# ---------------------------------------------------------------------------
# Reports (content moderation queue, GP-08)
# ---------------------------------------------------------------------------

@router.get("/reports", response_model=List[ReportOut])
def list_reports(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    q = db.query(Report)
    if status_filter:
        q = q.filter(Report.status == status_filter)
    return q.order_by(Report.created_at.asc()).all()


@router.get("/reports/{report_id}", response_model=ReportOut)
def get_report(
    report_id: int,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")
    return r


@router.patch("/reports/{report_id}", response_model=ReportOut)
def resolve_report(
    report_id: int,
    payload: ReportAdminUpdate,
    _admin: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(status_code=404, detail="Report not found")

    r.status = payload.status
    if payload.admin_notes is not None:
        r.admin_notes = payload.admin_notes
    if payload.status in ("resolved", "dismissed"):
        from datetime import datetime, timezone
        r.resolved_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(r)
    return r
