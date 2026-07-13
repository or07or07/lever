"""Lever — Client routes: profile, vehicles, service requests, browse providers, reviews."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

import asyncio
from auth import get_current_user, require_client
from database import get_db
from models import (
    ClientProfile,
    Job,
    MechanicProfile,
    Review,
    ServiceRequest,
    User,
    Vehicle,
)
from professions import PROFESSION_KEYS
from schemas import (
    ClientProfileOut,
    ClientProfileUpdate,
    JobOut,
    MechanicCard,
    MessageResponse,
    ReviewCreate,
    ReviewOut,
    ServiceRequestCreate,
    ServiceRequestDetail,
    ServiceRequestOut,
    ServiceRequestUpdate,
    VehicleCreate,
    VehicleOut,
    VehicleUpdate,
)

router = APIRouter(prefix="/api/client", tags=["client"])


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

@router.get("/profile", response_model=ClientProfileOut)
def get_profile(
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    profile = db.query(ClientProfile).filter(ClientProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.patch("/profile", response_model=ClientProfileOut)
def update_profile(
    payload: ClientProfileUpdate,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    profile = db.query(ClientProfile).filter(ClientProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------

@router.get("/vehicles", response_model=List[VehicleOut])
def list_vehicles(
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    return db.query(Vehicle).filter(Vehicle.client_id == current_user.id).all()


@router.post("/vehicles", response_model=VehicleOut, status_code=status.HTTP_201_CREATED)
def add_vehicle(
    payload: VehicleCreate,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    vehicle = Vehicle(client_id=current_user.id, **payload.model_dump())
    db.add(vehicle)
    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.get("/vehicles/{vehicle_id}", response_model=VehicleOut)
def get_vehicle(
    vehicle_id: int,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.client_id == current_user.id,
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    return vehicle


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut)
def update_vehicle(
    vehicle_id: int,
    payload: VehicleUpdate,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.client_id == current_user.id,
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(vehicle, field, value)

    db.commit()
    db.refresh(vehicle)
    return vehicle


@router.delete("/vehicles/{vehicle_id}", response_model=MessageResponse)
def delete_vehicle(
    vehicle_id: int,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    vehicle = db.query(Vehicle).filter(
        Vehicle.id == vehicle_id,
        Vehicle.client_id == current_user.id,
    ).first()
    if not vehicle:
        raise HTTPException(status_code=404, detail="Vehicle not found")
    db.delete(vehicle)
    db.commit()
    return MessageResponse(message="Vehicle deleted")


# ---------------------------------------------------------------------------
# Service Requests
# ---------------------------------------------------------------------------

@router.get("/requests", response_model=List[ServiceRequestOut])
def list_requests(
    status_filter: Optional[str] = Query(default=None, alias="status"),
    profession_type: Optional[str] = Query(default=None),
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    q = db.query(ServiceRequest).filter(ServiceRequest.client_id == current_user.id)
    if status_filter:
        q = q.filter(ServiceRequest.status == status_filter)
    if profession_type:
        q = q.filter(ServiceRequest.profession_type == profession_type)
    return q.order_by(ServiceRequest.created_at.desc()).all()


@router.post("/requests", response_model=ServiceRequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: ServiceRequestCreate,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    # Validate vehicle belongs to client (if provided)
    if payload.vehicle_id:
        v = db.query(Vehicle).filter(
            Vehicle.id == payload.vehicle_id,
            Vehicle.client_id == current_user.id,
        ).first()
        if not v:
            raise HTTPException(status_code=400, detail="Vehicle not found or not yours")

    req = ServiceRequest(client_id=current_user.id, **payload.model_dump())
    db.add(req)
    db.commit()
    db.refresh(req)

    # Trigger dispatch — find online providers and start 30-second offer rotation
    from dispatch import start_dispatch
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(start_dispatch(req.id))
    except RuntimeError:
        # No running loop (e.g. in sync test context) — skip async dispatch
        pass

    return req


@router.get("/requests/{request_id}", response_model=ServiceRequestDetail)
def get_request(
    request_id: int,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    req = (
        db.query(ServiceRequest)
        .options(joinedload(ServiceRequest.vehicle), joinedload(ServiceRequest.job))
        .filter(ServiceRequest.id == request_id, ServiceRequest.client_id == current_user.id)
        .first()
    )
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    return req


@router.patch("/requests/{request_id}", response_model=ServiceRequestOut)
def update_request(
    request_id: int,
    payload: ServiceRequestUpdate,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    req = db.query(ServiceRequest).filter(
        ServiceRequest.id == request_id,
        ServiceRequest.client_id == current_user.id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status not in ("pending",):
        raise HTTPException(
            status_code=400,
            detail="Only pending requests can be edited",
        )

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(req, field, value)

    db.commit()
    db.refresh(req)
    return req


@router.delete("/requests/{request_id}", response_model=MessageResponse)
def cancel_request(
    request_id: int,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    req = db.query(ServiceRequest).filter(
        ServiceRequest.id == request_id,
        ServiceRequest.client_id == current_user.id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status not in ("pending", "assigned"):
        raise HTTPException(
            status_code=400,
            detail="Cannot cancel a request that is already in progress or completed",
        )
    req.status = "cancelled"
    db.commit()
    return MessageResponse(message="Request cancelled")


# ---------------------------------------------------------------------------
# Browse Providers (filtered by profession)
# ---------------------------------------------------------------------------

@router.get("/providers", response_model=List[MechanicCard])
def browse_providers(
    profession: Optional[str] = Query(default=None),
    location: Optional[str] = Query(default=None),
    specialty: Optional[str] = Query(default=None),
    available_only: bool = Query(default=True),
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    q = db.query(MechanicProfile)
    if available_only:
        q = q.filter(MechanicProfile.is_available == True)
    if profession:
        q = q.filter(MechanicProfile.profession == profession)
    if location:
        q = q.filter(MechanicProfile.location.ilike(f"%{location}%"))
    if specialty:
        q = q.filter(MechanicProfile.specialties.contains(specialty))
    return q.order_by(MechanicProfile.avg_rating.desc()).all()


# ---------------------------------------------------------------------------
# Jobs (read-only — for the chat header to resolve who the other party is)
# ---------------------------------------------------------------------------

@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(
    job_id: int,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    job = (
        db.query(Job)
        .options(joinedload(Job.request))
        .filter(Job.id == job_id)
        .first()
    )
    if not job or not job.request or job.request.client_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ---------------------------------------------------------------------------
# Reviews
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/review", response_model=ReviewOut, status_code=status.HTTP_201_CREATED)
def leave_review(
    job_id: int,
    payload: ReviewCreate,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    job = (
        db.query(Job)
        .options(joinedload(Job.request))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.request.client_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your job")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not yet completed")
    if job.review:
        raise HTTPException(status_code=409, detail="Review already submitted")

    mechanic_user_id = job.mechanic_id
    review = Review(
        job_id=job_id,
        client_id=current_user.id,
        mechanic_id=mechanic_user_id,
        rating=payload.rating,
        comment=payload.comment or "",
    )
    db.add(review)

    # Update mechanic aggregate rating
    mech_profile = db.query(MechanicProfile).filter(
        MechanicProfile.user_id == mechanic_user_id
    ).first()
    if mech_profile:
        existing_total = mech_profile.avg_rating * mech_profile.total_jobs
        mech_profile.total_jobs += 1
        mech_profile.avg_rating = (existing_total + payload.rating) / mech_profile.total_jobs

    db.commit()
    db.refresh(review)
    return review
