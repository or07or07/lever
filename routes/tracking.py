"""Lever — GPS Live Tracking routes.

WebSocket endpoints for real-time location streaming + REST endpoints
for tracking status and location history.

Endpoints:
  WS  /ws/tracking/{job_id}/provider?token={jwt}  — Provider broadcasts location
  WS  /ws/tracking/{job_id}/client?token={jwt}     — Client receives location updates
  GET /api/tracking/{job_id}/status                — Current tracking state + ETA
  GET /api/tracking/{job_id}/trail                 — Location breadcrumb trail
  GET /api/tracking/{job_id}/latest                — Most recent location point

CIA Triad:
  Confidentiality: JWT auth on all endpoints; only job participants
  Integrity:       Server-side validation of coords; DB persistence before broadcast
  Availability:    Non-blocking location writes; graceful WS disconnect
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import desc
from sqlalchemy.orm import Session

from auth import decode_token, get_current_user, require_client_or_provider
from database import SessionLocal, get_db
from geo import haversine_miles, is_valid_coords
from models import Job, MechanicProfile, Notification, ProviderLocation, ServiceRequest, User
from schemas import LocationOut, LocationTrail, LocationUpdate, TrackingStatus
from tracking_manager import tracking_manager

logger = logging.getLogger("lever.tracking")

router = APIRouter()

# Average driving speed assumption for ETA (mph) — conservative for urban
AVG_SPEED_MPH = 25.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_job_participants(db: Session, job_id: int) -> tuple[Optional[int], Optional[int], Optional[Job]]:
    """Return (client_id, provider_id, job) for a given job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return None, None, None
    request = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
    if not request:
        return None, None, None
    return request.client_id, job.mechanic_id, job


def _estimate_eta_minutes(
    provider_lat: float, provider_lng: float,
    dest_lat: float, dest_lng: float,
    speed_mps: Optional[float] = None,
) -> Optional[float]:
    """Estimate ETA in minutes using Haversine distance.

    If the provider's speed is available and > 2 m/s, use it.
    Otherwise, fall back to average urban driving speed.
    """
    distance = haversine_miles(provider_lat, provider_lng, dest_lat, dest_lng)

    if speed_mps and speed_mps > 2.0:
        speed_mph = speed_mps * 2.237  # m/s to mph
    else:
        speed_mph = AVG_SPEED_MPH

    if speed_mph <= 0:
        return None

    return round((distance / speed_mph) * 60, 1)


# ---------------------------------------------------------------------------
# WebSocket: Provider broadcasts location
# ---------------------------------------------------------------------------


async def _authenticate_tracking_ws(websocket, token):
    """Auth via token param OR first message. Returns (user_id, role) or (None, None)."""
    if token:
        try:
            payload = decode_token(token)
            return int(payload.get("sub")), payload.get("role")
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return None, None
    try:
        data = await websocket.receive_text()
        msg = json.loads(data)
        if msg.get("type") != "auth" or not msg.get("token"):
            await websocket.close(code=4001, reason="First message must be auth")
            return None, None
        payload = decode_token(msg["token"])
        return int(payload.get("sub")), payload.get("role")
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return None, None

@router.websocket("/ws/tracking/{job_id}/provider")
async def ws_tracking_provider(
    websocket: WebSocket,
    job_id: int,
    token: Optional[str] = Query(None),
):
    """Provider streams GPS location for an active job.

    Send: {"type": "location", "latitude": float, "longitude": float,
           "accuracy": float?, "heading": float?, "speed": float?,
           "altitude": float?, "recorded_at": ISO8601?}
    Send: {"type": "tracking_stop"}
    """
    # Accept then authenticate via token or first message
    await websocket.accept()
    user_id, role = await _authenticate_tracking_ws(websocket, token)
    if user_id is None:
        return

    if role != "mechanic":
        await websocket.close(code=4003, reason="Only providers can broadcast location")
        return

    # Verify provider is assigned to this job
    db = SessionLocal()
    try:
        client_id, provider_id, job = _get_job_participants(db, job_id)
        if not job:
            await websocket.close(code=4004, reason="Job not found")
            return
        if user_id != provider_id:
            await websocket.close(code=4003, reason="Not the provider for this job")
            return
        if job.status in ("completed", "cancelled"):
            await websocket.close(code=4005, reason="Job is not active")
            return

        # Get destination coords from service request
        request = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
        dest_lat = request.latitude if request else None
        dest_lng = request.longitude if request else None
    finally:
        db.close()

    # Connect provider
    await tracking_manager.connect_provider(websocket, job_id, user_id, already_accepted=True)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "location")

            if msg_type == "tracking_stop":
                await tracking_manager.broadcast_to_clients(job_id, {"type": "tracking_stopped"})
                break

            if msg_type == "location":
                lat = msg.get("latitude")
                lng = msg.get("longitude")

                if not is_valid_coords(lat, lng):
                    await websocket.send_json({"type": "error", "message": "Invalid coordinates"})
                    continue

                accuracy = msg.get("accuracy")
                heading = msg.get("heading")
                speed = msg.get("speed")
                altitude = msg.get("altitude")
                recorded_at_str = msg.get("recorded_at")

                try:
                    recorded_at = (
                        datetime.fromisoformat(recorded_at_str)
                        if recorded_at_str
                        else datetime.now(timezone.utc)
                    )
                except (ValueError, TypeError):
                    recorded_at = datetime.now(timezone.utc)

                # Persist breadcrumb to database
                db = SessionLocal()
                try:
                    loc = ProviderLocation(
                        job_id=job_id,
                        provider_user_id=user_id,
                        latitude=lat,
                        longitude=lng,
                        accuracy=accuracy,
                        heading=heading,
                        speed=speed,
                        altitude=altitude,
                        recorded_at=recorded_at,
                    )
                    db.add(loc)

                    # Also update provider's profile location
                    profile = db.query(MechanicProfile).filter(
                        MechanicProfile.user_id == user_id
                    ).first()
                    if profile:
                        profile.latitude = lat
                        profile.longitude = lng
                        profile.last_heartbeat = datetime.now(timezone.utc)
                        profile.is_online = True

                    db.commit()
                    db.refresh(loc)
                    loc_id = loc.id
                finally:
                    db.close()

                # Calculate ETA if destination is known
                eta_minutes = None
                distance_miles = None
                if dest_lat and dest_lng and is_valid_coords(dest_lat, dest_lng):
                    distance_miles = round(haversine_miles(lat, lng, dest_lat, dest_lng), 2)
                    eta_minutes = _estimate_eta_minutes(lat, lng, dest_lat, dest_lng, speed)

                # Broadcast to watching clients
                broadcast = {
                    "type": "location_update",
                    "id": loc_id,
                    "latitude": lat,
                    "longitude": lng,
                    "accuracy": accuracy,
                    "heading": heading,
                    "speed": speed,
                    "altitude": altitude,
                    "recorded_at": recorded_at.isoformat(),
                    "distance_miles": distance_miles,
                    "eta_minutes": eta_minutes,
                }
                await tracking_manager.broadcast_to_clients(job_id, broadcast)

                # Ack back to provider
                await websocket.send_json({
                    "type": "location_ack",
                    "id": loc_id,
                    "distance_miles": distance_miles,
                    "eta_minutes": eta_minutes,
                    "watchers": len(tracking_manager.get_watching_clients(job_id)),
                })

    except WebSocketDisconnect:
        tracking_manager.disconnect_provider(job_id, user_id)
        await tracking_manager.broadcast_to_clients(job_id, {"type": "tracking_stopped"})
    except Exception as e:
        logger.error(f"Tracking WS error: provider={user_id} job={job_id}: {e}")
        tracking_manager.disconnect_provider(job_id, user_id)
        await tracking_manager.broadcast_to_clients(job_id, {"type": "tracking_stopped"})


# ---------------------------------------------------------------------------
# WebSocket: Client watches provider location
# ---------------------------------------------------------------------------

@router.websocket("/ws/tracking/{job_id}/client")
async def ws_tracking_client(
    websocket: WebSocket,
    job_id: int,
    token: Optional[str] = Query(None),
):
    """Client connects to receive real-time provider location updates.

    Receives:
      {"type": "tracking_started", "provider_user_id": int}
      {"type": "location_update", "latitude": float, "longitude": float, ...}
      {"type": "tracking_stopped"}
    """
    # Accept then authenticate via token or first message
    await websocket.accept()
    user_id, _ = await _authenticate_tracking_ws(websocket, token)
    if user_id is None:
        return

    # Verify client is participant
    db = SessionLocal()
    try:
        client_id, provider_id, job = _get_job_participants(db, job_id)
        if not job:
            await websocket.close(code=4004, reason="Job not found")
            return
        if user_id != client_id:
            await websocket.close(code=4003, reason="Not the client for this job")
            return
    finally:
        db.close()

    # Connect client
    await tracking_manager.connect_client(websocket, job_id, user_id, already_accepted=True)

    # Send current tracking state
    if tracking_manager.is_provider_tracking(job_id):
        # Fetch latest location
        db = SessionLocal()
        try:
            latest = (
                db.query(ProviderLocation)
                .filter(ProviderLocation.job_id == job_id)
                .order_by(desc(ProviderLocation.created_at))
                .first()
            )
            if latest:
                request = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
                dest_lat = request.latitude if request else None
                dest_lng = request.longitude if request else None

                distance_miles = None
                eta_minutes = None
                if dest_lat and dest_lng and is_valid_coords(dest_lat, dest_lng):
                    distance_miles = round(
                        haversine_miles(latest.latitude, latest.longitude, dest_lat, dest_lng), 2
                    )
                    eta_minutes = _estimate_eta_minutes(
                        latest.latitude, latest.longitude, dest_lat, dest_lng, latest.speed
                    )

                await websocket.send_json({
                    "type": "tracking_started",
                    "provider_user_id": tracking_manager.get_tracking_provider_id(job_id),
                })
                await websocket.send_json({
                    "type": "location_update",
                    "id": latest.id,
                    "latitude": latest.latitude,
                    "longitude": latest.longitude,
                    "accuracy": latest.accuracy,
                    "heading": latest.heading,
                    "speed": latest.speed,
                    "altitude": latest.altitude,
                    "recorded_at": latest.recorded_at.isoformat(),
                    "distance_miles": distance_miles,
                    "eta_minutes": eta_minutes,
                })
        finally:
            db.close()

    try:
        # Keep connection alive — client mostly just receives
        while True:
            data = await websocket.receive_text()
            # Client can send pings or acknowledgments
            try:
                msg = json.loads(data)
                if msg.get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        tracking_manager.disconnect_client(job_id, user_id)
    except Exception as e:
        logger.error(f"Tracking WS error: client={user_id} job={job_id}: {e}")
        tracking_manager.disconnect_client(job_id, user_id)


# ---------------------------------------------------------------------------
# REST: Tracking status
# ---------------------------------------------------------------------------

@router.get("/api/tracking/{job_id}/status", response_model=TrackingStatus, tags=["tracking"])
def get_tracking_status(
    job_id: int,
    current_user: User = Depends(require_client_or_provider),
    db: Session = Depends(get_db),
):
    """Get current tracking status for a job, including ETA and distance."""
    client_id, provider_id, job = _get_job_participants(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.id not in (client_id, provider_id):
        raise HTTPException(status_code=403, detail="Not a participant of this job")

    # Get latest location
    latest = (
        db.query(ProviderLocation)
        .filter(ProviderLocation.job_id == job_id)
        .order_by(desc(ProviderLocation.created_at))
        .first()
    )

    # Get destination
    request = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
    dest_lat = request.latitude if request else None
    dest_lng = request.longitude if request else None

    # Get provider name
    profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == provider_id).first()
    provider_name = profile.full_name if profile else None

    distance_miles = None
    eta_minutes = None
    current_loc = None

    if latest:
        current_loc = LocationOut.model_validate(latest)
        if dest_lat and dest_lng and is_valid_coords(dest_lat, dest_lng):
            distance_miles = round(
                haversine_miles(latest.latitude, latest.longitude, dest_lat, dest_lng), 2
            )
            eta_minutes = _estimate_eta_minutes(
                latest.latitude, latest.longitude, dest_lat, dest_lng, latest.speed
            )

    return TrackingStatus(
        job_id=job_id,
        is_tracking=tracking_manager.is_provider_tracking(job_id),
        provider_user_id=provider_id,
        provider_name=provider_name,
        current_location=current_loc,
        destination_latitude=dest_lat,
        destination_longitude=dest_lng,
        distance_miles=distance_miles,
        eta_minutes=eta_minutes,
        job_status=job.status,
    )


# ---------------------------------------------------------------------------
# REST: Location trail (breadcrumbs)
# ---------------------------------------------------------------------------

@router.get("/api/tracking/{job_id}/trail", response_model=LocationTrail, tags=["tracking"])
def get_location_trail(
    job_id: int,
    limit: int = Query(default=500, ge=1, le=5000),
    current_user: User = Depends(require_client_or_provider),
    db: Session = Depends(get_db),
):
    """Get the location breadcrumb trail for a job (newest first)."""
    client_id, provider_id, job = _get_job_participants(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.id not in (client_id, provider_id):
        raise HTTPException(status_code=403, detail="Not a participant of this job")

    points = (
        db.query(ProviderLocation)
        .filter(ProviderLocation.job_id == job_id)
        .order_by(desc(ProviderLocation.created_at))
        .limit(limit)
        .all()
    )

    return LocationTrail(
        job_id=job_id,
        provider_user_id=provider_id or 0,
        total_points=len(points),
        trail=[LocationOut.model_validate(p) for p in points],
    )


# ---------------------------------------------------------------------------
# REST: Latest location
# ---------------------------------------------------------------------------

@router.get("/api/tracking/{job_id}/latest", response_model=Optional[LocationOut], tags=["tracking"])
def get_latest_location(
    job_id: int,
    current_user: User = Depends(require_client_or_provider),
    db: Session = Depends(get_db),
):
    """Get the most recent location point for a job's provider."""
    client_id, provider_id, job = _get_job_participants(db, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.id not in (client_id, provider_id):
        raise HTTPException(status_code=403, detail="Not a participant of this job")

    latest = (
        db.query(ProviderLocation)
        .filter(ProviderLocation.job_id == job_id)
        .order_by(desc(ProviderLocation.created_at))
        .first()
    )

    if not latest:
        return None

    return LocationOut.model_validate(latest)
