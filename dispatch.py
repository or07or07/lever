"""Lever — Job request dispatch engine.

Dispatches new service requests to eligible online providers with a 30-second
acceptance window. If a provider doesn't accept within 30 seconds, the request
is forwarded to the next qualified provider in the queue.

Flow:
  1. Client creates ServiceRequest → triggers start_dispatch()
  2. System finds all online, qualified providers (matching profession, within radius)
  3. Ranks by: distance (if geo available), then rating
  4. Creates RequestDispatch records for each eligible provider
  5. Offers to first provider (sends notification)
  6. 30-second asyncio timer starts
  7. If not accepted → mark timeout, offer to next provider
  8. Repeat until accepted or queue exhausted
  9. If all timeout → request stays pending, client notified
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from database import SessionLocal
from models import Job, MechanicProfile, Notification, RequestDispatch, ServiceRequest

logger = logging.getLogger("lever.dispatch")

from config import settings
DISPATCH_TIMEOUT_SECONDS = settings.dispatch_offer_seconds

# Job statuses that mean the professional is DONE with that job.
FINISHED_JOB_STATUSES = ("completed", "cancelled")

# ── Event-loop bridge ──
# FastAPI runs sync (def) endpoints in a worker THREADPOOL, where
# asyncio.create_task() raises RuntimeError — so every dispatch task scheduled
# straight from a request handler silently never ran. The app's real event
# loop is captured once at startup (app.py lifespan) and _schedule() hands
# coroutines to it from any thread.
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def init_dispatch_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once from the app lifespan, on the server's event loop."""
    global _MAIN_LOOP
    _MAIN_LOOP = loop
    logger.info("Dispatch: event loop captured for cross-thread scheduling")


def _schedule(coro) -> bool:
    """Run an async dispatch task from ANY context — event loop or threadpool.

    Returns False only when no loop exists at all (bare sync scripts/tests);
    resolve_stale_offers() covers dispatch progression in that case."""
    try:
        asyncio.get_running_loop()
        asyncio.create_task(coro)
        return True
    except RuntimeError:
        pass
    if _MAIN_LOOP is not None and not _MAIN_LOOP.is_closed():
        asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)
        return True
    coro.close()   # suppress the "coroutine was never awaited" warning
    return False


def schedule_start_dispatch(request_id: int) -> bool:
    """Entry point for request creation (sync endpoint): begin dispatching."""
    return _schedule(start_dispatch(request_id))


def provider_is_busy(db: Session, provider_user_id: int) -> bool:
    """ONE JOB AT A TIME: a professional who has an unfinished job — or is
    currently holding a live offer for another request — must not receive a
    new offer. Busy providers stay 'queued' and are re-considered when the
    queue advances or when they free up (job completion / go-online)."""
    active_job = db.query(Job).filter(
        Job.mechanic_id == provider_user_id,
        ~Job.status.in_(FINISHED_JOB_STATUSES),
    ).first()
    if active_job:
        return True
    offers = db.query(RequestDispatch).filter(
        RequestDispatch.provider_user_id == provider_user_id,
        RequestDispatch.status == "offered",
    ).all()
    # Only offers still inside their window count — a stale row (its timer was
    # lost to a restart) must never lock a provider out of new work.
    return any(not _offer_window_lapsed(d) for d in offers)


def _offer_window_lapsed(dispatch: RequestDispatch, grace_seconds: int = 5) -> bool:
    """True if this offer's acceptance window is over (plus a small grace)."""
    ts = dispatch.offered_at
    if ts is None:
        return True
    if ts.tzinfo is None:   # stored naive-UTC by the DB driver
        ts = ts.replace(tzinfo=timezone.utc)
    elapsed = (datetime.now(timezone.utc) - ts).total_seconds()
    return elapsed > DISPATCH_TIMEOUT_SECONDS + grace_seconds


def resolve_stale_offers(db: Session, provider_user_id: Optional[int] = None) -> int:
    """Resolve 'offered' rows whose window already lapsed, exactly as the
    rotation timer would have: mark timeout, notify the provider, advance the
    request's queue (or tell the client everyone passed).

    Timers are asyncio tasks — they die on every deploy/restart. This lazy
    sweep is the recovery path, run from the polling/dispatch entry points, so
    a lost timer can only ever delay rotation, never wedge it. Returns the
    number of rows resolved."""
    q = db.query(RequestDispatch).filter(RequestDispatch.status == "offered")
    if provider_user_id is not None:
        q = q.filter(RequestDispatch.provider_user_id == provider_user_id)
    stale = [d for d in q.all() if _offer_window_lapsed(d)]
    for d in stale:
        d.status = "timeout"
        d.responded_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            f"Dispatch: resolved STALE offer {d.id} (request {d.request_id}, "
            f"provider {d.provider_user_id}) — lost timer"
        )
        _notify_provider_timeout(db, d)
        req = db.query(ServiceRequest).filter(ServiceRequest.id == d.request_id).first()
        if req and req.status == "pending":
            nxt = _offer_next(db, d.request_id)
            if nxt:
                _schedule(_dispatch_timer(d.request_id, nxt.id))
            else:
                _notify_client_timeout_all(db, d.request_id)
    return len(stale)


def _offer_next(db: Session, request_id: int) -> Optional[RequestDispatch]:
    """Offer the request to the first QUEUED candidate who is not busy.

    Busy candidates are skipped but left queued, so a later advance (or their
    freeing up) re-considers them. Returns the dispatch that was offered, or
    None if every remaining candidate is busy / the queue is exhausted."""
    queued = (
        db.query(RequestDispatch)
        .filter(
            RequestDispatch.request_id == request_id,
            RequestDispatch.status == "queued",
        )
        .order_by(RequestDispatch.position.asc())
        .all()
    )
    for dispatch in queued:
        if provider_is_busy(db, dispatch.provider_user_id):
            continue
        offer_to_provider(db, dispatch)
        return dispatch
    return None


def find_eligible_providers(
    db: Session,
    request: ServiceRequest,
) -> list[MechanicProfile]:
    """Find all online providers matching the request's profession,
    ordered by distance (if geo available) then rating.

    Filters:
    - is_online == True (recent heartbeat, actively available)
    - is_available == True (not on another job)
    - profession matches request type
    - within their service radius (if geo data available)

    Returns providers sorted by:
    1. Distance (closest first; if no geo data, sorted last)
    2. Average rating (descending)
    """
    base = db.query(MechanicProfile).filter(
        MechanicProfile.is_online == True,
        MechanicProfile.is_available == True,
    )

    if request.service_key:
        # ── Multi-profession + EXACT-service matching (spec §12) ──
        # A provider is eligible if they EXPLICITLY offer this exact service and
        # keep it active — regardless of which profession it belongs to, so a
        # provider can span professions via their ProviderService selection.
        # Providers who have never configured any service keep the legacy
        # behaviour: they receive every request in their single
        # MechanicProfile.profession. A provider who HAS configured services
        # receives only the ones they left active (so a plumber who selected
        # only faucet-installation never gets a water-heater request), and a
        # paused service (is_active=False) produces no offers.
        from models import ProviderService
        sk = request.service_key
        active_ids = {
            r[0] for r in db.query(ProviderService.provider_user_id)
            .filter(ProviderService.service_key == sk, ProviderService.is_active == True).all()
        }
        configured_ids = {
            r[0] for r in db.query(ProviderService.provider_user_id).distinct().all()
        }
        candidates = [
            p for p in base.all()
            if (p.user_id in active_ids)
            or (p.user_id not in configured_ids and p.profession == request.profession_type)
        ]
    else:
        # Legacy request without a specific service — match the profession.
        candidates = base.filter(MechanicProfile.profession == request.profession_type).all()

    # Score and sort candidates
    scored = []
    for provider in candidates:
        distance = None
        if (request.latitude and request.longitude and
            provider.latitude and provider.longitude):
            from geo import haversine_miles
            distance = haversine_miles(
                request.latitude, request.longitude,
                provider.latitude, provider.longitude
            )
            # Skip if outside provider's service radius
            if distance > provider.service_radius_miles:
                continue

        scored.append((provider, distance))

    # Sort: BEST-QUALIFIED FIRST — the marketplace policy is that opportunities
    # go to the best-rated professionals before anyone else. Rating is the
    # primary key, proven experience (completed jobs) breaks ties, and
    # distance only orders otherwise-equal candidates.
    scored.sort(key=lambda x: (
        -(x[0].avg_rating or 0),
        -(x[0].total_jobs or 0),
        x[1] if x[1] is not None else float('inf'),
    ))

    return [provider for provider, _ in scored]


def create_dispatch_queue(
    db: Session,
    request_id: int,
    providers: list[MechanicProfile],
) -> list[RequestDispatch]:
    """Create dispatch queue entries for all eligible providers.

    Each provider gets a RequestDispatch record with:
    - status = "queued" (waiting for their turn)
    - position = their position in the queue (0-indexed)

    Args:
        db: Database session
        request_id: The ServiceRequest.id
        providers: Sorted list of eligible MechanicProfile objects

    Returns:
        List of created RequestDispatch objects
    """
    dispatches = []
    for position, provider in enumerate(providers):
        dispatch = RequestDispatch(
            request_id=request_id,
            provider_user_id=provider.user_id,
            status="queued",
            position=position,
        )
        db.add(dispatch)
        dispatches.append(dispatch)
    db.commit()
    return dispatches


def offer_to_provider(db: Session, dispatch: RequestDispatch) -> None:
    """Send notification to provider that they have a job offer.

    Updates dispatch status to "offered" and sends a push/in-app notification
    with the request details and a 30-second deadline.

    Args:
        db: Database session
        dispatch: RequestDispatch object to offer
    """
    dispatch.status = "offered"
    dispatch.offered_at = datetime.now(timezone.utc)

    # Get request details for notification
    request = db.query(ServiceRequest).filter(
        ServiceRequest.id == dispatch.request_id
    ).first()

    if request:
        # Payment shown up-front: the client's real budget when set, otherwise
        # the backend reference estimate (labelled as such) — never fabricated.
        # Lever charges no commission, so this is what the professional
        # receives. Deliberately NO exact address here (privacy): the zone is
        # enough for a preview; full details come from the board after opening.
        from pricing import payment_line_es
        pay = payment_line_es(request.budget_min, request.budget_max, request.service_key)
        notif = Notification(
            user_id=dispatch.provider_user_id,
            type="job_offer",
            title="Nueva oportunidad de trabajo",
            message=(
                f'"{request.title}"'
                + (f" — {pay} (recibes el 100%)" if pay else "")
                + f". Tienes {DISPATCH_TIMEOUT_SECONDS} segundos para aceptar antes de que se ofrezca al siguiente profesional."
            ),
            link=f"/provider/board",
        )
        db.add(notif)

    db.commit()
    logger.info(
        f"Dispatch: offered request {dispatch.request_id} to provider {dispatch.provider_user_id} "
        f"(position {dispatch.position})"
    )


def cancel_dispatch_for_request(db: Session, request_id: int) -> None:
    """Cancel all pending/queued dispatches for a request.

    Called when a provider accepts a request. Cancels all other offers
    in the queue so they don't receive notifications later.

    Args:
        db: Database session
        request_id: The ServiceRequest.id
    """
    db.query(RequestDispatch).filter(
        RequestDispatch.request_id == request_id,
        RequestDispatch.status.in_(["queued", "offered"]),
    ).update({"status": "cancelled"}, synchronize_session="fetch")
    db.commit()
    logger.info(f"Dispatch: cancelled remaining queue for request {request_id}")


def _notify_client_no_providers(db: Session, request_id: int) -> None:
    """Notify the client that no providers are currently available.

    Sent when start_dispatch() finds zero eligible online providers.
    Request remains pending and visible on the job board for when
    providers come online.

    Args:
        db: Database session
        request_id: The ServiceRequest.id
    """
    request = db.query(ServiceRequest).filter(
        ServiceRequest.id == request_id
    ).first()
    if not request:
        return

    notif = Notification(
        user_id=request.client_id,
        type="system",
        title="Buscando profesionales disponibles",
        message=(
            f'Tu solicitud "{request.title}" fue publicada, pero por ahora no hay profesionales disponibles. '
            f"Se ofrecerá automáticamente en cuanto un profesional se libere o se conecte."
        ),
        link=f"/client/requests/{request_id}",
    )
    db.add(notif)
    db.commit()
    logger.info(f"Dispatch: no providers available for request {request_id}")


def _notify_client_timeout_all(db: Session, request_id: int) -> None:
    """Notify client that all providers timed out — request stays pending.

    Sent when the entire provider queue has timed out without accepting.
    Request remains active and visible on the job board.

    Args:
        db: Database session
        request_id: The ServiceRequest.id
    """
    request = db.query(ServiceRequest).filter(
        ServiceRequest.id == request_id
    ).first()
    if not request:
        return

    # The queue can exhaust repeatedly (each go-online/free-up retries) — the
    # client only needs to hear "still searching" once every little while,
    # not on every rotation cycle.
    from datetime import timedelta
    recent_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    already = (
        db.query(Notification)
        .filter(
            Notification.user_id == request.client_id,
            Notification.title == "Seguimos buscando un profesional",
            Notification.link == f"/client/requests/{request_id}",
        )
        .order_by(Notification.created_at.desc())
        .first()
    )
    if already:
        ts = already.created_at
        if ts is not None and ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        if ts is not None and ts > recent_cutoff:
            return

    notif = Notification(
        user_id=request.client_id,
        type="system",
        title="Seguimos buscando un profesional",
        message=(
            f'Ningún profesional ha aceptado tu solicitud "{request.title}" todavía. '
            f"Tu solicitud sigue activa y visible en el tablero."
        ),
        link=f"/client/requests/{request_id}",
    )
    db.add(notif)
    db.commit()
    logger.info(f"Dispatch: all providers timed out for request {request_id}")


def _notify_provider_timeout(db: Session, dispatch: RequestDispatch) -> None:
    """Notify a provider that their offer expired.

    Sent when a provider's 30-second acceptance window passes without
    responding. They can see other jobs on the board.

    Args:
        db: Database session
        dispatch: The RequestDispatch that timed out
    """
    request = db.query(ServiceRequest).filter(
        ServiceRequest.id == dispatch.request_id
    ).first()
    if not request:
        return

    notif = Notification(
        user_id=dispatch.provider_user_id,
        type="job_update",
        title="La oferta expiró",
        message=f'La solicitud "{request.title}" se ofreció al siguiente profesional disponible.',
        link="/provider/board",
    )
    db.add(notif)
    db.commit()


def decline_and_advance(db: Session, dispatch: RequestDispatch) -> None:
    """Provider explicitly declined the offer: resolve it NOW and immediately
    offer the next queued candidate instead of waiting out the window.

    The pending timer for the declined offer will still fire later, see the
    status is no longer 'offered', and return without acting — so declining
    never double-advances the queue.
    """
    dispatch.status = "timeout"   # reuse the existing enum value for "did not take it"
    dispatch.responded_at = datetime.now(timezone.utc)
    db.commit()
    logger.info(
        f"Dispatch: provider {dispatch.provider_user_id} DECLINED request "
        f"{dispatch.request_id} (position {dispatch.position}) — advancing queue"
    )
    next_dispatch = _offer_next(db, dispatch.request_id)
    if next_dispatch:
        _schedule(_dispatch_timer(dispatch.request_id, next_dispatch.id))
    else:
        _notify_client_timeout_all(db, dispatch.request_id)


def _provider_eligible_for(db: Session, profile: MechanicProfile, request: ServiceRequest) -> bool:
    """Single-provider eligibility, mirroring find_eligible_providers: exact
    service match when the request has a service_key (with the legacy
    profession fallback for providers who never configured services)."""
    from models import ProviderService
    if request.service_key:
        mine = db.query(ProviderService).filter(
            ProviderService.provider_user_id == profile.user_id
        ).all()
        if mine:
            return any(s.service_key == request.service_key and s.is_active for s in mine)
        return profile.profession == request.profession_type
    return profile.profession == request.profession_type


def redispatch_pending_for_provider(db: Session, provider_user_id: int) -> int:
    """A provider just came ONLINE (or freed up): offer them the OLDEST
    pending request they're eligible for that nobody is currently holding.

    Without this, dispatch only ever considered providers online at request-
    creation time — a request created while everyone was offline sat silently
    on the board forever. Re-offers requests this provider previously timed
    out on (they were probably offline), never ones they accepted.

    ONE AT A TIME: offers at most one request, and never to a provider who
    already has a live offer or an unfinished job.
    Returns the number of offers created (0 or 1).
    """
    from sqlalchemy import func as safunc

    profile = db.query(MechanicProfile).filter(
        MechanicProfile.user_id == provider_user_id
    ).first()
    if not profile or not profile.is_online or not profile.is_available:
        return 0
    # Global recovery sweep first: requests wedged on a stale offer (lost
    # timer) must rotate before we decide there's "already a live offer".
    resolve_stale_offers(db)
    if provider_is_busy(db, provider_user_id):
        return 0

    pending = (
        db.query(ServiceRequest)
        .filter(ServiceRequest.status == "pending")
        .order_by(ServiceRequest.created_at.asc())
        .all()
    )
    offered = 0
    for req in pending:
        if not _provider_eligible_for(db, profile, req):
            continue
        # Someone is already holding an active offer for this request.
        if db.query(RequestDispatch).filter(
            RequestDispatch.request_id == req.id,
            RequestDispatch.status == "offered",
        ).first():
            continue
        mine = (
            db.query(RequestDispatch)
            .filter(
                RequestDispatch.request_id == req.id,
                RequestDispatch.provider_user_id == provider_user_id,
            )
            .order_by(RequestDispatch.id.desc())
            .first()
        )
        if mine and mine.status == "accepted":
            continue
        if mine and mine.status in ("queued", "timeout"):
            dispatch = mine
        else:
            max_pos = db.query(safunc.max(RequestDispatch.position)).filter(
                RequestDispatch.request_id == req.id
            ).scalar()
            dispatch = RequestDispatch(
                request_id=req.id,
                provider_user_id=provider_user_id,
                position=(max_pos if max_pos is not None else -1) + 1,
                status="queued",
            )
            db.add(dispatch)
            db.flush()
        offer_to_provider(db, dispatch)
        _schedule(_dispatch_timer(req.id, dispatch.id))
        offered += 1
        break  # one offer at a time — the next request waits its turn
    if offered:
        logger.info(
            f"Dispatch: re-offered {offered} pending request(s) to provider "
            f"{provider_user_id} on go-online"
        )
    return offered


async def _dispatch_timer(request_id: int, dispatch_id: int) -> None:
    """Wait out the acceptance window, then check if the offer was accepted.

    If the offer was accepted (status = "accepted"), do nothing.
    If the offer was not accepted, mark it as "timeout" and offer to
    the next free provider in the queue (busy providers are skipped
    but stay queued).

    This runs as a background asyncio task. Each timer creates the next timer
    in the chain, until all providers have timed out or one accepts.

    Args:
        request_id: The ServiceRequest.id
        dispatch_id: The current RequestDispatch.id
    """
    await asyncio.sleep(DISPATCH_TIMEOUT_SECONDS)

    db = SessionLocal()
    try:
        # Check if the request has already been accepted
        request = db.query(ServiceRequest).filter(
            ServiceRequest.id == request_id
        ).first()
        if not request or request.status != "pending":
            logger.info(
                f"Dispatch timer: request {request_id} already handled "
                f"(status={request.status if request else 'gone'})"
            )
            # Never leave the row 'offered' — a stuck live offer would make
            # this provider permanently "busy" and invisible to dispatch.
            current = db.query(RequestDispatch).filter(
                RequestDispatch.id == dispatch_id
            ).first()
            if current and current.status == "offered":
                current.status = "cancelled"
                current.responded_at = datetime.now(timezone.utc)
                db.commit()
            return

        # Check current dispatch status
        current = db.query(RequestDispatch).filter(
            RequestDispatch.id == dispatch_id
        ).first()
        if not current or current.status != "offered":
            logger.info(
                f"Dispatch timer: dispatch {dispatch_id} already resolved "
                f"(status={current.status if current else 'gone'})"
            )
            return

        # Timeout this offer
        current.status = "timeout"
        current.responded_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            f"Dispatch: provider {current.provider_user_id} timed out on request {request_id}"
        )

        # Notify the provider that they missed it
        _notify_provider_timeout(db, current)

        # Offer to the next FREE provider in the queue (skips busy ones)
        next_dispatch = _offer_next(db, request_id)

        if next_dispatch:
            _schedule(_dispatch_timer(request_id, next_dispatch.id))
        else:
            # All providers exhausted
            _notify_client_timeout_all(db, request_id)
            logger.info(f"Dispatch: all providers exhausted for request {request_id}")
    except Exception as e:
        logger.error(f"Dispatch timer error for request {request_id}: {e}", exc_info=True)
    finally:
        db.close()


async def start_dispatch(request_id: int) -> None:
    """Entry point: begin dispatching a service request to eligible providers.

    Called when a client creates a new ServiceRequest. This function:
    1. Finds all eligible online providers
    2. Creates a dispatch queue
    3. Offers to the first provider
    4. Starts the 30-second timer loop

    If no providers are eligible, notifies the client and exits.

    Args:
        request_id: The ServiceRequest.id to dispatch
    """
    db = SessionLocal()
    try:
        request = db.query(ServiceRequest).filter(
            ServiceRequest.id == request_id
        ).first()
        if not request:
            logger.error(f"Dispatch: request {request_id} not found")
            return

        logger.info(f"Dispatch: starting dispatch for request {request_id}")

        # Find eligible online providers
        providers = find_eligible_providers(db, request)

        if not providers:
            _notify_client_no_providers(db, request_id)
            return

        logger.info(
            f"Dispatch: found {len(providers)} eligible providers for request {request_id}"
        )

        # Create dispatch queue
        create_dispatch_queue(db, request_id, providers)

        # Offer to the first FREE provider (busy ones stay queued and are
        # re-considered as the queue advances or when they free up)
        first = _offer_next(db, request_id)
        if not first:
            _notify_client_no_providers(db, request_id)
            return

        # Start the acceptance-window timer for the first offer
        _schedule(_dispatch_timer(request_id, first.id))

    except Exception as e:
        logger.error(f"Dispatch error for request {request_id}: {e}", exc_info=True)
    finally:
        db.close()


def mark_dispatch_accepted(db: Session, request_id: int, provider_user_id: int) -> Optional[RequestDispatch]:
    """Mark the dispatch as accepted by this provider.

    Called from the provider's accept endpoint. Updates the dispatch status
    to "accepted", records the response time, and cancels all remaining
    offers in the queue.

    Args:
        db: Database session
        request_id: The ServiceRequest.id
        provider_user_id: The User.id of the accepting provider

    Returns:
        The accepted RequestDispatch if found, else None
    """
    dispatch = db.query(RequestDispatch).filter(
        RequestDispatch.request_id == request_id,
        RequestDispatch.provider_user_id == provider_user_id,
        RequestDispatch.status == "offered",
    ).first()

    if dispatch:
        dispatch.status = "accepted"
        dispatch.responded_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(
            f"Dispatch: provider {provider_user_id} accepted request {request_id}"
        )
    else:
        logger.warning(
            f"Dispatch: no active offer found for provider {provider_user_id} "
            f"on request {request_id}"
        )

    # Cancel remaining offers in queue
    cancel_dispatch_for_request(db, request_id)

    return dispatch
