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

DISPATCH_TIMEOUT_SECONDS = 30


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

    # Sort: by distance first (None = infinity), then by rating descending
    scored.sort(key=lambda x: (
        x[1] if x[1] is not None else float('inf'),
        -(x[0].avg_rating or 0),
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
                + ". Tienes 30 segundos para aceptar antes de que se ofrezca al siguiente profesional."
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
        title="No providers available right now",
        message=(
            f'Your request "{request.title}" has been posted but no providers are currently online. '
            f"Providers will be able to find your request on the job board when they come online."
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

    notif = Notification(
        user_id=request.client_id,
        type="system",
        title="Still looking for a provider",
        message=(
            f'No provider has accepted your request "{request.title}" yet. '
            f"Your request remains active and visible on the job board."
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
        title="Job offer expired",
        message=f'The job request "{request.title}" has been forwarded to another provider.',
        link="/provider/board",
    )
    db.add(notif)
    db.commit()


async def _dispatch_timer(request_id: int, dispatch_id: int, next_position: int) -> None:
    """Wait 30 seconds, then check if the current offer was accepted.

    If the offer was accepted (status = "accepted"), do nothing.
    If the offer was not accepted, mark it as "timeout" and offer to
    the next provider in the queue.

    This runs as a background asyncio task. Each timer creates the next timer
    in the chain, until all providers have timed out or one accepts.

    Args:
        request_id: The ServiceRequest.id
        dispatch_id: The current RequestDispatch.id
        next_position: The position of the next provider to offer to
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

        # Find next in queue
        next_dispatch = db.query(RequestDispatch).filter(
            RequestDispatch.request_id == request_id,
            RequestDispatch.position == next_position,
            RequestDispatch.status == "queued",
        ).first()

        if next_dispatch:
            # Offer to next provider and schedule their timer
            offer_to_provider(db, next_dispatch)
            asyncio.create_task(
                _dispatch_timer(request_id, next_dispatch.id, next_position + 1)
            )
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
        dispatches = create_dispatch_queue(db, request_id, providers)

        # Offer to first provider
        first = dispatches[0]
        offer_to_provider(db, first)

        # Start 30-second timer for first provider
        asyncio.create_task(
            _dispatch_timer(request_id, first.id, 1)
        )

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
