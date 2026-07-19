"""Lever — Client routes: profile, vehicles, service requests, browse providers, reviews."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from auth import get_current_user, require_client
from database import get_db
from models import (
    ClientProfile,
    CustomerRating,
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
    reqs = (
        q.options(joinedload(ServiceRequest.job).joinedload(Job.review))
        .order_by(ServiceRequest.created_at.desc())
        .all()
    )

    # Attach the assigned professional's summary + whether the customer has
    # reviewed the job, for the Activity cards. Batched to avoid N+1.
    mech_ids = {r.job.mechanic_id for r in reqs if r.job and r.job.mechanic_id}
    profiles, verified = {}, {}
    if mech_ids:
        for mp in db.query(MechanicProfile).filter(MechanicProfile.user_id.in_(mech_ids)).all():
            profiles[mp.user_id] = mp
        for u in db.query(User).filter(User.id.in_(mech_ids)).all():
            verified[u.id] = (u.verification_level == "enhanced")
    for r in reqs:
        r.professional_name = None
        r.professional_rating = None
        r.professional_verified = None
        r.professional_hourly_rate = None
        r.professional_jobs = None
        r.has_review = None
        job = r.job
        if job and job.mechanic_id:
            mp = profiles.get(job.mechanic_id)
            if mp:
                r.professional_name = mp.full_name or None
                r.professional_rating = round(mp.avg_rating, 1) if mp.total_jobs else None
                # Worker-set pricing + trust: their rate and verified track record
                r.professional_hourly_rate = mp.hourly_rate or None
                r.professional_jobs = mp.total_jobs or 0
            r.professional_verified = verified.get(job.mechanic_id, False)
            r.has_review = job.review is not None
    return reqs


@router.post("/requests", response_model=ServiceRequestOut, status_code=status.HTTP_201_CREATED)
def create_request(
    payload: ServiceRequestCreate,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    # ── ONE REQUEST AT A TIME ──
    # A client may only have a single active request (searching or with a
    # professional on the way / working). They must complete or cancel it
    # before sending another — keeps dispatch simple and expectations clear.
    active = db.query(ServiceRequest).filter(
        ServiceRequest.client_id == current_user.id,
        ServiceRequest.status.in_(("pending", "assigned", "in_progress")),
    ).first()
    if active:
        raise HTTPException(status_code=409, detail="ACTIVE_REQUEST_EXISTS")

    # Validate vehicle belongs to client (if provided)
    if payload.vehicle_id:
        v = db.query(Vehicle).filter(
            Vehicle.id == payload.vehicle_id,
            Vehicle.client_id == current_user.id,
        ).first()
        if not v:
            raise HTTPException(status_code=400, detail="Vehicle not found or not yours")

    # ── Authoritative Guayaquil service-area enforcement ──
    # This is the gate the frontend cannot bypass: no matter what the client
    # sends, a request is only created (and only dispatched to professionals)
    # if the address validates into an active market. market_code is assigned
    # here, server-side — never taken from the payload.
    from market import validate_service_location
    result = validate_service_location(
        country_code=payload.country_code,
        province=payload.province,
        city=payload.city,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    if not result.get("supported"):
        raise HTTPException(status_code=422, detail=result.get("reason", "ADDRESS_OUTSIDE_GUAYAQUIL"))

    data = payload.model_dump()
    # Strip validation-only fields that aren't columns on ServiceRequest.
    for k in ("city", "province", "country_code"):
        data.pop(k, None)

    # ── Lever sets the price ──
    # For catalog services the price is the app's researched Guayaquil labor
    # estimate (pricing.py), snapshotted onto the request at creation. Any
    # client-sent budget is IGNORED: price is not negotiated between client
    # and professional. The final charge must stay within this range
    # (enforced at job completion in routes/provider.py).
    if data.get("service_key"):
        from pricing import ESTIMATES
        est = ESTIMATES.get(data["service_key"])
        if est:
            data["budget_min"], data["budget_max"] = float(est[0]), float(est[1])

    req = ServiceRequest(client_id=current_user.id, market_code=result["market_code"], **data)

    # ── Phase 2: client chose a specific professional ──
    # Validate they're real, currently reachable, and actually offer this
    # service — a stale browse card must fail loudly, not dispatch into a void.
    if req.preferred_provider_id:
        from dispatch import (_provider_eligible_for, expire_stale_providers,
                              provider_is_busy)
        expire_stale_providers(db)
        pref = db.query(MechanicProfile).filter(
            MechanicProfile.user_id == req.preferred_provider_id
        ).first()
        if (not pref or not pref.is_online or not pref.is_available
                or provider_is_busy(db, pref.user_id)
                or not _provider_eligible_for(db, pref, req)):
            raise HTTPException(status_code=409, detail="PROVIDER_NOT_AVAILABLE")

    db.add(req)
    db.commit()
    db.refresh(req)

    # Matching only begins AFTER the request is validated and persisted —
    # unsupported addresses never reach this line, so professionals are
    # never notified about them. schedule_start_dispatch works from this
    # threadpool context (asyncio.create_task here never did).
    from dispatch import schedule_start_dispatch
    schedule_start_dispatch(req.id)

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
    # Assigned professional's summary for the detail screen: name, rating,
    # their hourly rate + verified track record (worker-set pricing Phase 1).
    if req.job and req.job.mechanic_id:
        mp = db.query(MechanicProfile).filter(
            MechanicProfile.user_id == req.job.mechanic_id
        ).first()
        if mp:
            req.professional_name = mp.full_name or None
            req.professional_rating = round(mp.avg_rating, 1) if mp.total_jobs else None
            req.professional_hourly_rate = mp.hourly_rate or None
            req.professional_jobs = mp.total_jobs or 0
        u = db.query(User).filter(User.id == req.job.mechanic_id).first()
        req.professional_verified = bool(u and u.verification_level == "enhanced")
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

    from models import Job, Notification, RequestDispatch

    # Tell anyone currently holding a live offer for this request — their
    # popup is about a job that no longer exists.
    offered = db.query(RequestDispatch).filter(
        RequestDispatch.request_id == request_id,
        RequestDispatch.status == "offered",
    ).all()
    for d in offered:
        db.add(Notification(
            user_id=d.provider_user_id,
            type="job_update",
            title="Solicitud cancelada",
            message=f'El cliente canceló la solicitud "{req.title}".',
            link="/provider/board",
        ))

    # An assigned request has a live Job — cancel it and FREE the
    # professional (one-job-at-a-time would otherwise lock them forever).
    freed_provider_id = None
    job = db.query(Job).filter(Job.request_id == request_id).first()
    if job and job.status not in ("completed", "cancelled"):
        job.status = "cancelled"
        freed_provider_id = job.mechanic_id
        db.add(Notification(
            user_id=job.mechanic_id,
            type="job_update",
            title="Trabajo cancelado por el cliente",
            message=(
                f'El cliente canceló "{req.title}". '
                f"No necesitas ir al lugar. Ya puedes recibir nuevas ofertas."
            ),
            link="/provider/jobs",
        ))

    req.status = "cancelled"
    db.commit()

    # Resolve the dispatch queue and hand the freed professional (or the one
    # whose offer just vanished) the next pending request right away.
    from dispatch import cancel_dispatch_for_request, redispatch_pending_for_provider
    cancel_dispatch_for_request(db, request_id)
    for provider_id in {d.provider_user_id for d in offered} | ({freed_provider_id} - {None}):
        redispatch_pending_for_provider(db, provider_id)

    return MessageResponse(message="Request cancelled")


@router.post("/requests/{request_id}/broadcast", response_model=MessageResponse)
def broadcast_request(
    request_id: int,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    """Fallback when the CHOSEN professional didn't respond: clear the
    preference and dispatch the request to every eligible professional."""
    req = db.query(ServiceRequest).filter(
        ServiceRequest.id == request_id,
        ServiceRequest.client_id == current_user.id,
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "pending":
        raise HTTPException(status_code=400, detail="Request is no longer pending")
    if not req.preferred_provider_id:
        raise HTTPException(status_code=400, detail="Request is already open to everyone")

    req.preferred_provider_id = None
    db.commit()

    # Resolve the targeted dispatch rows and start a fresh open dispatch.
    from dispatch import cancel_dispatch_for_request, schedule_start_dispatch
    cancel_dispatch_for_request(db, request_id)
    schedule_start_dispatch(request_id)
    return MessageResponse(message="Request broadcast to all professionals")


# ---------------------------------------------------------------------------
# Choose a professional (worker-set pricing Phase 2)
# ---------------------------------------------------------------------------

@router.get("/providers/for-service")
def providers_for_service(
    service_key: str = Query(min_length=1, max_length=80),
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    """Professionals AVAILABLE RIGHT NOW for a specific catalog service, with
    everything the client needs to choose honestly: each one's own hourly
    rate and quoted total for this service, star rating, verified completed
    jobs, and identity-verification badge. Rating-first order (the same
    priority auto-dispatch uses)."""
    from services_catalog import SERVICES_BY_KEY
    from pricing import quote_for_provider, ESTIMATES
    from dispatch import expire_stale_providers, provider_is_busy, _provider_eligible_for

    svc = SERVICES_BY_KEY.get(service_key)
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")

    expire_stale_providers(db)
    # Build a probe request (never persisted) so eligibility matches dispatch.
    probe = ServiceRequest(
        client_id=current_user.id, service_key=service_key,
        profession_type=svc.get("profession", ""), title="probe", description="probe",
        location="probe",
    )
    candidates = db.query(MechanicProfile).filter(
        MechanicProfile.is_online == True,
        MechanicProfile.is_available == True,
    ).all()
    verified_ids = {
        u.id for u in db.query(User).filter(
            User.id.in_([c.user_id for c in candidates] or [0]),
            User.verification_level == "enhanced",
        ).all()
    }
    cards = []
    for p in candidates:
        if not _provider_eligible_for(db, p, probe):
            continue
        if provider_is_busy(db, p.user_id):
            continue
        quote = quote_for_provider(p.hourly_rate, svc)
        cards.append({
            "user_id": p.user_id,
            "full_name": p.full_name or "Profesional Lever",
            "profession": p.profession,
            "avg_rating": round(p.avg_rating, 1) if p.total_jobs else None,
            "total_jobs": p.total_jobs or 0,
            "years_experience": p.years_experience or 0,
            "verified": p.user_id in verified_ids,
            "hourly_rate": p.hourly_rate or None,
            "quote_min": quote[0] if quote else None,
            "quote_max": quote[1] if quote else None,
            "avatar_url": p.avatar_url or "",
        })
    # Best-qualified first — same policy as auto-dispatch.
    cards.sort(key=lambda c: (-(c["avg_rating"] or 0), -(c["total_jobs"] or 0)))
    ref = ESTIMATES.get(service_key)
    return {
        "service_key": service_key,
        "reference_min": ref[0] if ref else None,
        "reference_max": ref[1] if ref else None,
        "providers": cards,
    }


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
    # The client must confirm the work was completed before rating — the
    # rating is what drives dispatch priority, so it must follow an explicit
    # confirmation, not just the professional's own "completed" claim.
    if not job.client_confirmed_at:
        raise HTTPException(status_code=400, detail="CONFIRM_COMPLETION_FIRST")
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


# ---------------------------------------------------------------------------
# Client confirms the job was completed (unlocks rating)
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/confirm-completion")
def confirm_completion(
    job_id: int,
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    """The client confirms the professional finished the work. Required before
    the job can be rated (ratings drive who gets offers first). Owner-only,
    completed jobs only, idempotent-safe (409 on repeat)."""
    from datetime import datetime, timezone

    job = db.query(Job).options(joinedload(Job.request)).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.request.client_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your job")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job is not yet completed")
    if job.client_confirmed_at:
        raise HTTPException(status_code=409, detail="Already confirmed")

    job.client_confirmed_at = datetime.now(timezone.utc)

    from models import Notification
    db.add(Notification(
        user_id=job.mechanic_id,
        type="job_update",
        title="El cliente confirmó tu trabajo",
        message=f'El cliente confirmó que completaste "{job.request.title}". ¡Buen trabajo!',
        link=f"/provider/jobs/{job.id}",
    ))
    db.commit()
    return {"ok": True, "confirmed_at": job.client_confirmed_at.isoformat()}


# ---------------------------------------------------------------------------
# Customer reputation (professional → customer ratings) — own data only
# ---------------------------------------------------------------------------

@router.get("/reputation")
def my_reputation(
    current_user: User = Depends(require_client),
    db: Session = Depends(get_db),
):
    """The authenticated customer's own reputation. Recent feedback is returned
    anonymously (no professional identity). A customer can only read their own."""
    from sqlalchemy import func

    rows = (
        db.query(CustomerRating)
        .filter(
            CustomerRating.client_id == current_user.id,
            CustomerRating.moderation_status == "visible",
        )
        .order_by(CustomerRating.created_at.desc())
        .all()
    )
    count = len(rows)
    avg = round(sum(r.rating for r in rows) / count, 2) if count else None

    def _catavg(attr):
        vals = [getattr(r, attr) for r in rows if getattr(r, attr) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    completed = (
        db.query(func.count(Job.id))
        .join(ServiceRequest, Job.request_id == ServiceRequest.id)
        .filter(ServiceRequest.client_id == current_user.id, Job.status == "completed")
        .scalar()
    ) or 0

    dist = {str(i): 0 for i in range(1, 6)}
    for r in rows:
        k = str(int(r.rating))
        if k in dist:
            dist[k] += 1

    return {
        "average_rating": avg,
        "rating_count": count,
        "completed_job_count": int(completed),
        "distribution": dist,
        "category_averages": {
            "communication": _catavg("communication"),
            "punctuality": _catavg("punctuality"),
            "respect": _catavg("respect"),
            "request_accuracy": _catavg("request_accuracy"),
        },
        "recent_ratings": [
            {"overall_rating": r.rating, "comment": r.comment or "", "created_at": r.created_at.isoformat()}
            for r in rows[:5]
        ],
    }
