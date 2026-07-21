"""Lever - Provider routes: profile, job board, job management.

Works for all professions (mechanic, HVAC, electrician, construction, car wash).
The job board is filtered by the provider's profession.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session, joinedload

from auth import require_provider
from database import get_db
from models import ClientProfile, CustomerRating, Job, MechanicProfile, Notification, ProviderService, RequestDispatch, ServiceRequest, User
from professions import DEFAULT_PROFESSION, get_job_statuses
from routes.moderation import blocked_user_ids_involving, is_blocked_pair
from schemas import (
    JobDetail,
    JobOut,
    JobStatusUpdate,
    MechanicProfileOut,
    MechanicProfileUpdate,
    MessageResponse,
    CustomerRatingCreate,
    ProviderServiceOut,
    ProviderServiceToggle,
    ProviderServicesUpdate,
    ReviewOut,
    ServiceRequestBoardOut,
)

logger = logging.getLogger("lever.provider")

router = APIRouter(prefix="/api/provider", tags=["provider"])

# Minutes a professional has to reach the service location after accepting.
ARRIVAL_WINDOW_MINUTES = 45


# ---------------------------------------------------------------------------
# Helpers - notification creation
# ---------------------------------------------------------------------------

# Human-readable status messages for client notifications
_STATUS_MESSAGES = {
    "en_route": "va en camino a tu ubicación",
    "diagnosing": "llegó y está iniciando el trabajo",
    "repairing": "está trabajando en tu solicitud",
    "inspecting": "llegó y está iniciando el trabajo",
    "servicing": "está trabajando en tu solicitud",
    "working": "está trabajando en tu solicitud",
    "assessing": "llegó y está iniciando el trabajo",
    "prepping": "está trabajando en tu solicitud",
    "washing": "está trabajando en tu solicitud",
    "completed": "marcó el trabajo como terminado — confirma que todo quedó bien y califícalo",
    "cancelled": "canceló el trabajo",
}

# Next-step guidance for the worker after each status transition
_WORKER_NEXT_STEPS = {
    "accepted": "Dirígete al lugar del servicio.",
    "en_route": "Al llegar, presiona \"Iniciar trabajo\".",
    "diagnosing": "Cuando termines, presiona \"Completar trabajo\".",
    "repairing": "Cuando termines, presiona \"Completar trabajo\".",
    "inspecting": "Cuando termines, presiona \"Completar trabajo\".",
    "servicing": "Cuando termines, presiona \"Completar trabajo\".",
    "working": "Cuando termines, presiona \"Completar trabajo\".",
    "assessing": "Cuando termines, presiona \"Completar trabajo\".",
    "prepping": "Cuando termines, presiona \"Completar trabajo\".",
    "washing": "Cuando termines, presiona \"Completar trabajo\".",
    "completed": "¡Trabajo terminado! El cliente confirmará y podrá calificarte.",
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
    # Presence lease: expire ghost-online state BEFORE reporting it, so the
    # app shows the truth at login (a closed app goes offline in minutes,
    # not "online forever").
    from dispatch import expire_stale_providers
    expire_stale_providers(db)
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

    # ── Worker-set pricing (Phase 1) ──
    # The professional chooses their own hourly rate, bounded by an
    # honesty-first floor (above Ecuador's SBU-derived hourly, pricing.py)
    # and a sanity ceiling. 0 clears the rate → app reference pricing.
    if payload.hourly_rate is not None and payload.hourly_rate != 0:
        from config import settings
        lo, hi = settings.provider_min_hourly_rate, settings.provider_max_hourly_rate
        if not (lo <= payload.hourly_rate <= hi):
            raise HTTPException(
                status_code=400,
                detail=f"HOURLY_RATE_OUT_OF_RANGE: la tarifa debe estar entre "
                       f"USD {lo:g} y USD {hi:g} por hora",
            )

    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(profile, field, value)

    db.commit()
    db.refresh(profile)
    return profile


# ---------------------------------------------------------------------------
# Subscription (individual provider — free baseline + optional Pro tier)
# Billing is not wired yet: "upgrade" records intent; the subscription only
# becomes active when the payment integration (or an admin comp) flips it.
# ---------------------------------------------------------------------------

@router.get("/subscription")
def my_subscription(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    from subscriptions import ensure_subscription, subscription_public
    sub = ensure_subscription(db, "provider", current_user.id, tier="free")
    db.commit()
    return subscription_public(sub)


@router.post("/subscription/upgrade")
def upgrade_subscription(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    from subscriptions import ensure_subscription, subscription_public
    sub = ensure_subscription(db, "provider", current_user.id, tier="free")
    sub.tier = "pro"   # intent recorded; status stays inactive until billing/comp
    db.commit()
    db.refresh(sub)
    return {
        "subscription": subscription_public(sub),
        "billing_pending": True,
        "message": "Tu plan Pro está reservado. Se activará cuando el cobro esté disponible.",
    }


# ---------------------------------------------------------------------------
# Service selection (Phase 3 — service catalog)
#
# A provider is still tied to exactly one profession/category (v1 scope —
# see docs/service-catalog-ux-audit.md). Within that category they can pick
# which specific catalog services they actually offer, pause individual
# ones, and set a price. If a provider has never configured anything here
# (no rows at all), they're treated as offering every service in their
# profession — the pre-existing, zero-config behavior — so this feature is
# purely additive and doesn't break anyone who ignores it.
# ---------------------------------------------------------------------------

def _catalog_services_for_profession(profession: str) -> list[dict]:
    from services_catalog import ALL_SERVICES
    return [s for s in ALL_SERVICES if s["category"] == profession and s["is_active"]]


@router.get("/services", response_model=List[ProviderServiceOut])
def list_my_services(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    # Multi-profession (spec §5/§7): offer the FULL active catalog across every
    # profession, so a provider can select services outside their registration
    # profession. Each row still reports whether they currently offer it
    # (is_active) and whether they may enable it (selectable / verification).
    from services_catalog import ALL_SERVICES
    catalog_services = [s for s in ALL_SERVICES if s["is_active"]]
    selections = {
        ps.service_key: ps
        for ps in db.query(ProviderService).filter(ProviderService.provider_user_id == current_user.id).all()
    }
    out = []
    for svc in catalog_services:
        sel = selections.get(svc["key"])
        selectable = svc["verification_required"] == "none" or current_user.verification_level == "enhanced"
        out.append(ProviderServiceOut(
            service_key=svc["key"],
            name_es=svc["name_es"],
            name_en=svc["name_en"],
            icon=svc["icon"],
            category=svc["category"],
            pricing_type=svc["pricing_type"],
            verification_required=svc["verification_required"],
            is_active=sel.is_active if sel else False,
            price=sel.price if sel else None,
            selectable=selectable,
        ))
    return out


@router.put("/services", response_model=List[ProviderServiceOut])
def set_my_services(
    payload: ProviderServicesUpdate,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """Replace the provider's full service selection in one call."""
    profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    from services_catalog import ALL_SERVICES, SERVICES_BY_KEY
    # Multi-profession (spec §5/§7): a provider may offer ANY active catalog
    # service, across professions — not only their registration profession.
    # (Per-service enhanced-verification gating below still applies.)
    valid_keys = {s["key"] for s in ALL_SERVICES if s.get("is_active", True)}

    requested = {item.service_key: item for item in payload.services}
    unknown = [k for k in requested if k not in valid_keys]
    if unknown:
        raise HTTPException(status_code=400, detail=f"SERVICE_NOT_ACTIVE: {unknown}")

    blocked = [
        k for k in requested
        if SERVICES_BY_KEY[k]["verification_required"] == "enhanced" and current_user.verification_level != "enhanced"
    ]
    if blocked:
        raise HTTPException(
            status_code=403,
            detail=f"These services require additional verification before you can offer them: {blocked}. "
                   f"Contact support to get verified.",
        )

    existing = {
        ps.service_key: ps
        for ps in db.query(ProviderService).filter(ProviderService.provider_user_id == current_user.id).all()
    }
    for key, item in requested.items():
        if key in existing:
            existing[key].is_active = True
            existing[key].price = item.price
        else:
            db.add(ProviderService(provider_user_id=current_user.id, service_key=key, is_active=True, price=item.price))
    # Anything previously selected but not in this submission is paused, not deleted —
    # preserves the provider's price/history if they re-enable it later.
    for key, ps in existing.items():
        if key not in requested:
            ps.is_active = False

    db.commit()
    return list_my_services(current_user, db)


@router.patch("/services/{service_key}", response_model=ProviderServiceOut)
def toggle_my_service(
    service_key: str,
    payload: ProviderServiceToggle,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """Pause/resume a single service without touching the rest of the selection."""
    ps = db.query(ProviderService).filter(
        ProviderService.provider_user_id == current_user.id,
        ProviderService.service_key == service_key,
    ).first()
    if not ps:
        raise HTTPException(status_code=404, detail="You haven't selected this service")

    if payload.is_active:
        from services_catalog import SERVICES_BY_KEY
        svc = SERVICES_BY_KEY.get(service_key)
        if svc and svc["verification_required"] == "enhanced" and current_user.verification_level != "enhanced":
            raise HTTPException(status_code=403, detail="This service requires additional verification")

    ps.is_active = payload.is_active
    db.commit()
    results = list_my_services(current_user, db)
    return next(r for r in results if r.service_key == service_key)


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
    # Offer any pending requests this provider is eligible for RIGHT AWAY —
    # requests created while nobody was online must not sit silently on the
    # board (the popup then appears within one poll cycle, ~5s).
    from dispatch import redispatch_pending_for_provider
    redispatch_pending_for_provider(db, current_user.id)
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
    """Renew the presence lease. The app calls this every 60s WHILE the
    provider is online; miss heartbeats for provider_offline_after_minutes
    and expire_stale_providers() flips them offline (enforced lazily at
    every presence-reading surface). A heartbeat after expiry re-onlines
    them — an open app is intent to keep working."""
    profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == current_user.id).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    profile.last_heartbeat = datetime.now(timezone.utc)
    came_online = not profile.is_online
    if came_online:
        profile.is_online = True
    db.commit()
    if came_online:
        # Auto-reconnect counts as coming online: offer pending work right away
        from dispatch import redispatch_pending_for_provider
        redispatch_pending_for_provider(db, current_user.id)
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
    from dispatch import expire_stale_providers
    expire_stale_providers(db)
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

    profession = profile.profession if profile else DEFAULT_PROFESSION
    q = db.query(ServiceRequest).filter(ServiceRequest.status == "pending")
    # Phase 2: a request the client aimed at a specific professional is only
    # visible to that professional.
    q = q.filter(
        (ServiceRequest.preferred_provider_id.is_(None))
        | (ServiceRequest.preferred_provider_id == current_user.id)
    )
    if urgency:
        q = q.filter(ServiceRequest.urgency == urgency)

    # Never surface requests from a client either side has blocked.
    blocked_ids = blocked_user_ids_involving(db, current_user.id)
    if blocked_ids:
        q = q.filter(ServiceRequest.client_id.notin_(blocked_ids))

    # ── Multi-profession + exact-service board (spec §12) ──
    # A provider who configured services sees requests for the exact services
    # they've enabled (across ANY profession), plus legacy requests without a
    # service_key that fall in their own profession. A provider who never
    # configured services keeps the legacy behaviour: everything in their
    # profession.
    active_keys = _active_service_keys(db, current_user.id)   # None = unconfigured
    if active_keys is None:
        q = q.filter(ServiceRequest.profession_type == profession)
    else:
        q = q.filter(
            ServiceRequest.service_key.in_(active_keys)
            | (ServiceRequest.service_key.is_(None) & (ServiceRequest.profession_type == profession))
        )

    rows = q.order_by(ServiceRequest.created_at.asc()).all()
    # Attach the reference payment estimate for cards without a client budget
    # (Lever takes no commission, so this is what the professional receives).
    from pricing import ESTIMATES
    for r in rows:
        est = ESTIMATES.get(r.service_key or "")
        r.estimate_min = est[0] if est else None
        r.estimate_max = est[1] if est else None
    return rows


def _active_service_keys(db: Session, provider_user_id: int) -> Optional[set[str]]:
    """None means "no selection configured — show everything" (backward
    compatible default). An empty set means "configured but paused
    everything" — correctly shows nothing."""
    rows = db.query(ProviderService).filter(ProviderService.provider_user_id == provider_user_id).all()
    if not rows:
        return None
    return {r.service_key for r in rows if r.is_active}


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
    # Phase 2: the client chose someone — nobody else may take the job.
    if req.preferred_provider_id and req.preferred_provider_id != current_user.id:
        raise HTTPException(status_code=403, detail="RESERVED_FOR_CHOSEN_PROVIDER")
    if is_blocked_pair(db, current_user.id, req.client_id):
        raise HTTPException(status_code=403, detail="You cannot accept a request from this client")
    # ── Eligibility (multi-profession + exact service, spec §12/§27) ──
    # A provider may accept if they explicitly offer this exact service (active),
    # regardless of their MechanicProfile.profession. Providers who never
    # configured services fall back to the legacy profession match. This mirrors
    # find_eligible_providers so a provider can never accept a request that would
    # not have been offered to them.
    profile = db.query(MechanicProfile).filter(
        MechanicProfile.user_id == current_user.id
    ).first()
    active_keys = _active_service_keys(db, current_user.id)   # None = unconfigured
    if req.service_key and active_keys is not None:
        if req.service_key not in active_keys:
            raise HTTPException(status_code=400, detail="PROVIDER_NOT_ELIGIBLE")
    elif profile and profile.profession != req.profession_type:
        raise HTTPException(
            status_code=400,
            detail=f"This request requires a {req.profession_type} professional"
        )

    existing = db.query(Job).filter(Job.request_id == request_id).first()
    if existing:
        raise HTTPException(status_code=409, detail="Request already accepted")

    # ── ONE JOB AT A TIME ──
    # A professional with an unfinished job cannot take another. They free up
    # the moment their current job is completed (or cancelled) — and are then
    # immediately offered the next pending request they qualify for.
    active_job = db.query(Job).filter(
        Job.mechanic_id == current_user.id,
        ~Job.status.in_(("completed", "cancelled")),
    ).first()
    if active_job:
        raise HTTPException(status_code=409, detail="ACTIVE_JOB_EXISTS")

    # Must be online to accept requests
    if not (profile and profile.is_online):
        raise HTTPException(
            status_code=403,
            detail="You must be online to accept job requests."
        )

    # ── Worker-set pricing (Phase 1): snapshot THIS professional's quote ──
    # Their hourly rate × the service's catalog duration. Snapshotted here so
    # a later rate change never touches an already-hired job; the final
    # price is enforced inside this range at completion.
    quoted = None
    if req.service_key and profile and profile.hourly_rate:
        from services_catalog import SERVICES_BY_KEY
        from pricing import quote_for_provider
        quoted = quote_for_provider(profile.hourly_rate, SERVICES_BY_KEY.get(req.service_key))

    # Simplified flow: accepting means the professional is heading to the site
    # NOW — the job starts en route with a fixed arrival window.
    job = Job(
        request_id=request_id,
        mechanic_id=current_user.id,
        status="en_route",
        arrival_deadline=datetime.now(timezone.utc) + timedelta(minutes=ARRIVAL_WINDOW_MINUTES),
        quoted_min=quoted[0] if quoted else None,
        quoted_max=quoted[1] if quoted else None,
        # Phase 3: metered billing bills at THIS rate — snapshotted so a
        # later rate change can't touch an already-hired job.
        hourly_rate_snapshot=(profile.hourly_rate if quoted else None),
    )
    db.add(job)
    req.status = "assigned"
    db.flush()  # Get job.id before creating notifications

    # ── Notify the CLIENT that their request was accepted ──
    provider_name = profile.full_name if profile and profile.full_name else "Un profesional"
    profession_label = profile.profession.replace("_", " ").title() if profile else "Profesional"

    quote_line = ""
    if quoted:
        quote_line = (
            f" Su tarifa es USD {profile.hourly_rate:g}/h — "
            f"total estimado USD {quoted[0]:g}–{quoted[1]:g} (sin comisiones)."
        )
    _create_notification(
        db,
        user_id=req.client_id,
        notif_type="job_update",
        title="¡Tu solicitud fue aceptada!",
        message=(
            f"{provider_name} ({profession_label}) aceptó tu solicitud "
            f"\"{req.title}\" y ya va en camino.{quote_line} "
            f"Puedes escribirle directamente desde el detalle de tu solicitud."
        ),
        link=f"/client/requests/{req.id}",
    )

    # ── Notify the WORKER with next steps ──
    _create_notification(
        db,
        user_id=current_user.id,
        notif_type="job_update",
        title="Trabajo aceptado — ve al lugar del servicio",
        message=(
            f"Aceptaste \"{req.title}\". "
            f"Tienes {ARRIVAL_WINDOW_MINUTES} minutos para llegar al lugar. "
            f"Al llegar, presiona \"Iniciar trabajo\" en el detalle del trabajo."
        ),
        link=f"/provider/jobs/{job.id}",
    )

    db.commit()
    db.refresh(job)

    # Record THIS provider's offer as accepted (if one was live) and cancel
    # the rest of the queue — the dispatch history must show who took the job.
    from dispatch import mark_dispatch_accepted
    mark_dispatch_accepted(db, request_id, current_user.id)

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
    from dispatch import auto_confirm_stale_jobs
    auto_confirm_stale_jobs(db)   # lazy sweep: close out long-unconfirmed completions
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
    profession_type = req.profession_type if req else DEFAULT_PROFESSION
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
        # ── Simplified provider flow ──
        # "Iniciar trabajo": from en_route jump straight to the working phase
        # (3rd status) — arrival and start are one button press.
        if st == "en_route" and len(work_statuses) >= 3:
            next_statuses.add(work_statuses[2])
        # "Completar trabajo": any working-phase status can complete directly —
        # the profession's intermediate statuses are optional detail, not gates.
        if i >= 2:
            next_statuses.add("completed")
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

    # ── Phase 3: metered hourly billing ──
    # The clock is the APP (started_at → completed_at), never the worker's
    # word. Billed = clocked time × the snapshotted rate, clamped between
    # the quoted minimum (the call-out floor the client agreed to) and the
    # quoted maximum plus client-APPROVED extra time. If the professional
    # sends a price it must land in the same window (they may discount).
    metered = None
    lo = hi = None
    if payload.status == "completed":
        job.completed_at = datetime.utcnow()
        if req:
            req.status = "completed"
        if job.hourly_rate_snapshot and job.started_at:
            worked_min = max(0.0, (job.completed_at - job.started_at).total_seconds() / 60.0)
            job.billed_minutes = int(round(worked_min))
            lo = job.quoted_min or 0.0
            hi = (job.quoted_max or 0.0) + job.hourly_rate_snapshot * (job.extra_minutes_approved or 0) / 60.0
            metered = round(min(max(job.hourly_rate_snapshot * worked_min / 60.0, lo), hi), 2)

    job.status = payload.status
    if payload.mechanic_notes is not None:
        job.mechanic_notes = payload.mechanic_notes
    if payload.final_price is not None:
        # The final charge must stay inside the range the client hired
        # against: the metered window when hourly billing applies, else the
        # professional's quote, else the app reference range. Either way the
        # bounds were known up-front — no surprise billing.
        if lo is None:
            if job.quoted_min is not None and job.quoted_max is not None:
                lo, hi = job.quoted_min, job.quoted_max
            elif req and req.budget_min is not None and req.budget_max is not None:
                lo, hi = req.budget_min, req.budget_max
        if lo is not None and not (lo <= payload.final_price <= hi):
            raise HTTPException(
                status_code=400,
                detail=f"FINAL_PRICE_OUT_OF_RANGE: el precio final debe estar entre "
                       f"USD {lo:g} y USD {hi:g}",
            )
        job.final_price = payload.final_price
    elif metered is not None:
        # No price sent → the meter IS the price.
        job.final_price = metered

    # ── Notify the CLIENT of the status change ──
    if req:
        status_msg = _STATUS_MESSAGES.get(
            payload.status,
            f"updated job status to {payload.status.replace('_', ' ').title()}"
        )
        bill_line = ""
        if payload.status == "completed" and job.final_price is not None and job.billed_minutes is not None:
            h, m = divmod(job.billed_minutes, 60)
            bill_line = (
                f" Tiempo trabajado: {h}h {m:02d}m — total USD {job.final_price:g} "
                f"(tarifa USD {job.hourly_rate_snapshot:g}/h, sin comisiones)."
            )
        _create_notification(
            db,
            user_id=req.client_id,
            notif_type="job_update",
            title="Actualización de tu servicio",
            message=f"Tu profesional {status_msg}.{bill_line}",
            link=f"/client/requests/{req.id}",
        )

    # ── Notify the WORKER with next steps ──
    next_step = _WORKER_NEXT_STEPS.get(payload.status)
    if next_step:
        _create_notification(
            db,
            user_id=current_user.id,
            notif_type="job_update",
            title="Estado actualizado",
            message=next_step,
            link=f"/provider/jobs/{job.id}",
        )

    db.commit()
    db.refresh(job)

    # ── Freed up? Offer the next pending request right away ──
    # One-job-at-a-time means completing a job is the moment this professional
    # becomes eligible again — don't make them wait for the next go-online.
    if payload.status == "completed":
        from dispatch import redispatch_pending_for_provider
        redispatch_pending_for_provider(db, current_user.id)

    return job


# ---------------------------------------------------------------------------
# Extra time (Phase 3 — metered billing change-order)
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/request-extra-time", response_model=JobOut)
def request_extra_time(
    job_id: int,
    payload: dict,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """The job is outgrowing its estimate: ask the CLIENT to authorize more
    billable time. Nothing bills beyond the quote until they tap approve."""
    minutes = payload.get("minutes")
    if minutes not in (30, 60, 90, 120):
        raise HTTPException(status_code=422, detail="minutes must be 30, 60, 90 or 120")
    job = db.query(Job).filter(
        Job.id == job_id, Job.mechanic_id == current_user.id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status in ("completed", "cancelled"):
        raise HTTPException(status_code=400, detail="Job is already finalised")
    if not job.hourly_rate_snapshot:
        raise HTTPException(status_code=400, detail="NOT_HOURLY_BILLED")
    if job.extra_minutes_requested:
        raise HTTPException(status_code=409, detail="EXTRA_TIME_ALREADY_PENDING")

    job.extra_minutes_requested = minutes
    req = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
    if req:
        new_cap = (job.quoted_max or 0.0) + job.hourly_rate_snapshot * ((job.extra_minutes_approved or 0) + minutes) / 60.0
        h, m = divmod(minutes, 60)
        label = (f"{h}h" if not m else f"{h}h {m}m") if h else f"{m} min"
        _create_notification(
            db,
            user_id=req.client_id,
            notif_type="job_update",
            title="⏱️ Solicitud de tiempo adicional",
            message=(
                f'Tu profesional solicita {label} adicionales en "{req.title}". '
                f"Si apruebas, el total podría llegar hasta USD {new_cap:g}. "
                f"Apruébalo o recházalo desde el detalle de tu solicitud."
            ),
            link=f"/client/requests/{req.id}",
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


# ---------------------------------------------------------------------------
# Current active job offer (drives the in-app offer popup + countdown)
# ---------------------------------------------------------------------------

@router.get("/offer")
def current_offer(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """The provider's currently active dispatch offer, if any, with the
    seconds remaining in its acceptance window. The Provider APK polls this to
    pop up an incoming-job window with a countdown instead of requiring the
    provider to open the board manually. Sends expires_in_seconds (server-
    computed) so a wrong device clock can't distort the timer, and only a
    minimal job preview (title/payment/urgency — no exact address)."""
    from dispatch import DISPATCH_TIMEOUT_SECONDS, resolve_stale_offers

    # Recovery sweep: an offer whose timer was lost (deploy/restart) is
    # resolved here — the queue rotates and this provider frees up, so the
    # very next poll can hand them the follow-on offer.
    resolve_stale_offers(db, current_user.id)

    d = (
        db.query(RequestDispatch)
        .filter(
            RequestDispatch.provider_user_id == current_user.id,
            RequestDispatch.status == "offered",
        )
        .order_by(RequestDispatch.offered_at.desc())
        .first()
    )
    if not d or not d.offered_at:
        return {"offer": None}

    offered = d.offered_at
    if offered.tzinfo is None:  # stored naive-UTC by the DB driver
        offered = offered.replace(tzinfo=timezone.utc)
    remaining = DISPATCH_TIMEOUT_SECONDS - (datetime.now(timezone.utc) - offered).total_seconds()
    if remaining <= 0:
        return {"offer": None}   # window over; the rotation task handles the row

    req = db.query(ServiceRequest).filter(ServiceRequest.id == d.request_id).first()
    if not req or req.status != "pending":
        return {"offer": None}

    # Job details so the professional can DECIDE (pay, what, where-ish, how
    # long) — zone only, not the exact address (that comes after accepting).
    svc = None
    if req.service_key:
        from services_catalog import SERVICES_BY_KEY
        svc = SERVICES_BY_KEY.get(req.service_key)
    zone = None
    if req.location:
        parts = req.location.split("—")
        zone = parts[-1].strip() if len(parts) > 1 else None
    duration_label = None
    if svc and svc.get("duration_min") and svc.get("duration_max"):
        dmin, dmax = svc["duration_min"], svc["duration_max"]
        duration_label = (f"{dmin}–{dmax} min" if dmax < 60
                          else f"{round(dmin/60, 1):g}–{round(dmax/60, 1):g} h")

    # Worker-set pricing: when THIS professional has an hourly rate, the pay
    # they see is their own quote (rate × duration) — not the app reference.
    profile = db.query(MechanicProfile).filter(
        MechanicProfile.user_id == current_user.id
    ).first()
    from pricing import quote_for_provider
    quote = quote_for_provider(profile.hourly_rate if profile else None, svc)

    return {"offer": {
        "dispatch_id": d.id,
        "request_id": req.id,
        "title": req.title,
        "description": (req.description or "")[:180],
        "urgency": req.urgency,
        "zone": zone,
        "service_key": req.service_key,
        "service_name": svc["name_es"] if svc else None,
        "service_icon": svc["icon"] if svc else None,
        "duration_label": duration_label,
        "budget_min": req.budget_min,
        "budget_max": req.budget_max,
        "hourly_rate": profile.hourly_rate if profile and profile.hourly_rate else None,
        "quote_min": quote[0] if quote else None,
        "quote_max": quote[1] if quote else None,
        # Phase 2: the client picked THIS professional from the browse screen
        "direct": req.preferred_provider_id == current_user.id,
        "expires_in_seconds": int(remaining),
        "window_seconds": DISPATCH_TIMEOUT_SECONDS,
    }}


@router.post("/offer/decline")
def decline_offer(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """Explicitly pass on the current offer. The queue advances to the next
    candidate IMMEDIATELY instead of waiting out the window — declining is a
    courtesy to the client, never a penalty beyond losing this job."""
    from dispatch import decline_and_advance

    d = (
        db.query(RequestDispatch)
        .filter(
            RequestDispatch.provider_user_id == current_user.id,
            RequestDispatch.status == "offered",
        )
        .order_by(RequestDispatch.offered_at.desc())
        .first()
    )
    if not d:
        raise HTTPException(status_code=404, detail="No active offer")
    decline_and_advance(db, d)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Rate a customer (professional → customer) after a completed job
# ---------------------------------------------------------------------------

@router.post("/jobs/{job_id}/rate-customer", status_code=status.HTTP_201_CREATED)
def rate_customer(
    job_id: int,
    payload: CustomerRatingCreate,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    """The assigned professional rates the customer after a completed job.

    Authorization/eligibility is enforced entirely server-side:
      - only the professional assigned to the job may rate its customer,
      - only completed jobs are eligible (guest drafts / cancelled excluded),
      - exactly one rating per job (duplicate submissions rejected).
    The customer can never edit or delete a rating they received.
    """
    job = db.query(Job).options(joinedload(Job.request)).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.mechanic_id != current_user.id:
        raise HTTPException(status_code=403, detail="PROFESSIONAL_NOT_ASSIGNED_TO_JOB")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="JOB_NOT_ELIGIBLE_FOR_CUSTOMER_RATING")
    if db.query(CustomerRating).filter(CustomerRating.job_id == job_id).first():
        raise HTTPException(status_code=409, detail="CUSTOMER_RATING_ALREADY_EXISTS")

    client_user_id = job.request.client_id
    rating = CustomerRating(
        job_id=job_id,
        mechanic_id=current_user.id,
        client_id=client_user_id,
        rating=payload.rating,
        comment=(payload.comment or "")[:1000],
        communication=payload.communication,
        punctuality=payload.punctuality,
        respect=payload.respect,
        request_accuracy=payload.request_accuracy,
    )
    db.add(rating)
    db.flush()

    # Recompute the customer's aggregate from visible ratings (source of truth).
    from sqlalchemy import func
    cp = db.query(ClientProfile).filter(ClientProfile.user_id == client_user_id).first()
    if cp:
        agg = (
            db.query(func.count(CustomerRating.id), func.avg(CustomerRating.rating))
            .filter(
                CustomerRating.client_id == client_user_id,
                CustomerRating.moderation_status == "visible",
            )
            .one()
        )
        cp.total_ratings = int(agg[0] or 0)
        cp.avg_rating = round(float(agg[1] or 0.0), 2)

    # Notify the customer — no written feedback in the notification body.
    _create_notification(
        db, client_user_id, "review", "Nueva calificación",
        "Un profesional calificó tu experiencia como cliente.", link="#/account",
    )

    db.commit()
    db.refresh(rating)
    return {"id": rating.id, "job_id": rating.job_id, "rating": rating.rating,
            "created_at": rating.created_at.isoformat()}
