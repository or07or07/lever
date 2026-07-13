"""Lever — Search routes: advanced provider search, nearby requests, geocoding.

Day 60 addition — Search + Geolocation feature.

Provides:
  - GET  /api/search/providers    — Advanced provider search with geo + filters
  - GET  /api/search/requests     — Nearby service requests (for providers)
  - POST /api/search/geocode      — Address-to-coordinates lookup
  - GET  /api/search/map/providers — Providers for map view (returns all with coords)
  - GET  /api/search/map/requests  — Requests for map view (returns all with coords)

CIA Triad:
  Confidentiality: Auth-gated endpoints, no PII leakage in search results
  Integrity:       Validated coordinates, bounding-box pre-filter + Haversine verification
  Availability:    Geocoding failures are non-blocking, search degrades to non-geo filters
"""
from __future__ import annotations

import random
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from geo import bounding_box, haversine_miles, geocode, is_valid_coords
from models import MechanicProfile, ServiceRequest, User
from professions import PROFESSION_KEYS
from schemas import (
    GeocodeRequest,
    GeocodeResponse,
    MechanicCardWithDistance,
    SearchProvidersResponse,
    ServiceRequestWithDistance,
)

router = APIRouter(prefix="/api/search", tags=["search"])


# ---------------------------------------------------------------------------
# Advanced Provider Search
# ---------------------------------------------------------------------------

@router.get("/providers", response_model=SearchProvidersResponse)
def search_providers(
    latitude: Optional[float] = Query(default=None, ge=-90.0, le=90.0),
    longitude: Optional[float] = Query(default=None, ge=-180.0, le=180.0),
    radius_miles: float = Query(default=25.0, ge=1.0, le=500.0),
    profession: Optional[str] = Query(default=None),
    specialty: Optional[str] = Query(default=None),
    min_rating: Optional[float] = Query(default=None, ge=0.0, le=5.0),
    max_hourly_rate: Optional[float] = Query(default=None, ge=0.0),
    min_experience_years: Optional[int] = Query(default=None, ge=0),
    available_only: bool = Query(default=True),
    sort_by: str = Query(default="distance", pattern="^(distance|rating|price|experience)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search for service providers with location radius, rating, price, and specialty filters.

    If latitude/longitude are provided, results are filtered by radius and sorted by distance.
    If no coordinates are provided, all matching providers are returned (non-geo search).
    """
    if profession and profession not in PROFESSION_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid profession. Valid: {PROFESSION_KEYS}")

    has_geo = is_valid_coords(latitude, longitude)

    # Start query
    q = db.query(MechanicProfile)

    # Filter: availability
    if available_only:
        q = q.filter(MechanicProfile.is_available == True)

    # Filter: profession
    if profession:
        q = q.filter(MechanicProfile.profession == profession)

    # Filter: min rating
    if min_rating is not None:
        q = q.filter(MechanicProfile.avg_rating >= min_rating)

    # Filter: max hourly rate
    if max_hourly_rate is not None:
        q = q.filter(MechanicProfile.hourly_rate <= max_hourly_rate)

    # Filter: min experience
    if min_experience_years is not None:
        q = q.filter(MechanicProfile.years_experience >= min_experience_years)

    # Filter: specialty (JSON contains check)
    if specialty:
        # For SQLite, JSON contains uses text; for PostgreSQL, use native JSON
        q = q.filter(MechanicProfile.specialties.contains(specialty))

    # Geo: bounding-box pre-filter
    if has_geo:
        min_lat, max_lat, min_lng, max_lng = bounding_box(latitude, longitude, radius_miles)
        q = q.filter(
            MechanicProfile.latitude.isnot(None),
            MechanicProfile.longitude.isnot(None),
            MechanicProfile.latitude >= min_lat,
            MechanicProfile.latitude <= max_lat,
            MechanicProfile.longitude >= min_lng,
            MechanicProfile.longitude <= max_lng,
        )

    # Fetch candidates
    candidates = q.all()

    # Haversine filter + distance calculation
    results = []
    for provider in candidates:
        distance = None
        if has_geo and provider.latitude is not None and provider.longitude is not None:
            distance = haversine_miles(latitude, longitude, provider.latitude, provider.longitude)
            if distance > radius_miles:
                continue  # Outside radius (bounding box is an approximation)

        card = MechanicCardWithDistance(
            user_id=provider.user_id,
            profession=provider.profession,
            full_name=provider.full_name,
            specialties=provider.specialties or [],
            years_experience=provider.years_experience,
            hourly_rate=provider.hourly_rate,
            avg_rating=provider.avg_rating,
            total_jobs=provider.total_jobs,
            location=provider.location,
            service_radius_miles=provider.service_radius_miles,
            is_available=provider.is_available,
            avatar_url=provider.avatar_url,
            latitude=provider.latitude,
            longitude=provider.longitude,
            distance_miles=round(distance, 1) if distance is not None else None,
        )
        results.append(card)

    # Sort
    if sort_by == "distance" and has_geo:
        results.sort(key=lambda r: r.distance_miles if r.distance_miles is not None else float("inf"))
    elif sort_by == "rating":
        results.sort(key=lambda r: r.avg_rating, reverse=True)
    elif sort_by == "price":
        results.sort(key=lambda r: r.hourly_rate)
    elif sort_by == "experience":
        results.sort(key=lambda r: r.years_experience, reverse=True)
    else:
        # Default: by rating
        results.sort(key=lambda r: r.avg_rating, reverse=True)

    # Paginate
    total = len(results)
    start = (page - 1) * page_size
    end = start + page_size
    page_results = results[start:end]

    return SearchProvidersResponse(
        total=total,
        page=page,
        page_size=page_size,
        has_more=end < total,
        center_lat=latitude,
        center_lng=longitude,
        radius_miles=radius_miles if has_geo else None,
        results=page_results,
    )


# ---------------------------------------------------------------------------
# Nearby Service Requests (for providers)
# ---------------------------------------------------------------------------

@router.get("/requests", response_model=List[ServiceRequestWithDistance])
def search_nearby_requests(
    latitude: float = Query(ge=-90.0, le=90.0),
    longitude: float = Query(ge=-180.0, le=180.0),
    radius_miles: float = Query(default=25.0, ge=1.0, le=500.0),
    profession_type: Optional[str] = Query(default=None),
    urgency: Optional[str] = Query(default=None, pattern="^(immediate|scheduled)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Search for pending service requests near a location.

    Useful for providers to find nearby jobs. Returns requests with distance.
    """
    if profession_type and profession_type not in PROFESSION_KEYS:
        raise HTTPException(status_code=400, detail=f"Invalid profession. Valid: {PROFESSION_KEYS}")

    q = db.query(ServiceRequest).filter(ServiceRequest.status == "pending")

    if profession_type:
        q = q.filter(ServiceRequest.profession_type == profession_type)
    if urgency:
        q = q.filter(ServiceRequest.urgency == urgency)

    # Bounding-box pre-filter
    min_lat, max_lat, min_lng, max_lng = bounding_box(latitude, longitude, radius_miles)
    q = q.filter(
        ServiceRequest.latitude.isnot(None),
        ServiceRequest.longitude.isnot(None),
        ServiceRequest.latitude >= min_lat,
        ServiceRequest.latitude <= max_lat,
        ServiceRequest.longitude >= min_lng,
        ServiceRequest.longitude <= max_lng,
    )

    candidates = q.all()

    # Haversine verification
    results = []
    for req in candidates:
        dist = haversine_miles(latitude, longitude, req.latitude, req.longitude)
        if dist > radius_miles:
            continue

        results.append(ServiceRequestWithDistance(
            id=req.id,
            client_id=req.client_id,
            vehicle_id=req.vehicle_id,
            profession_type=req.profession_type,
            title=req.title,
            description=req.description,
            location=req.location,
            urgency=req.urgency,
            scheduled_date=req.scheduled_date,
            budget_min=req.budget_min,
            budget_max=req.budget_max,
            status=req.status,
            created_at=req.created_at,
            updated_at=req.updated_at,
            # Deliberately no latitude/longitude — see ServiceRequestBoardOut's
            # docstring. Precise coordinates are only appropriate once a
            # provider has actually accepted the request.
            distance_miles=round(dist, 1),
        ))

    results.sort(key=lambda r: r.distance_miles)
    return results


# ---------------------------------------------------------------------------
# Geocode endpoint
# ---------------------------------------------------------------------------

@router.post("/geocode", response_model=GeocodeResponse)
def geocode_address(
    payload: GeocodeRequest,
    current_user: User = Depends(get_current_user),
):
    """Convert an address string to latitude/longitude coordinates.

    Uses OpenStreetMap Nominatim (free, no API key required).
    Rate limited to 1 request per second per Nominatim usage policy.
    """
    result = geocode(payload.address)
    if result:
        return GeocodeResponse(
            address=payload.address,
            latitude=result[0],
            longitude=result[1],
            success=True,
        )
    return GeocodeResponse(
        address=payload.address,
        latitude=None,
        longitude=None,
        success=False,
    )


# ---------------------------------------------------------------------------
# Map data endpoints (lightweight — for rendering markers)
# ---------------------------------------------------------------------------

@router.get("/map/providers")
def map_providers(
    profession: Optional[str] = Query(default=None),
    available_only: bool = Query(default=True),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all providers with coordinates for map rendering.

    Returns minimal data for marker placement (id, name, profession, coords, rating).
    """
    q = db.query(MechanicProfile).filter(
        MechanicProfile.latitude.isnot(None),
        MechanicProfile.longitude.isnot(None),
    )
    if available_only:
        q = q.filter(MechanicProfile.is_available == True)
    if profession:
        q = q.filter(MechanicProfile.profession == profession)

    providers = q.all()

    return [
        {
            "user_id": p.user_id,
            "full_name": p.full_name,
            "profession": p.profession,
            "latitude": p.latitude,
            "longitude": p.longitude,
            "avg_rating": p.avg_rating,
            "hourly_rate": p.hourly_rate,
            "specialties": p.specialties or [],
            "service_radius_miles": p.service_radius_miles,
        }
        for p in providers
    ]


def _jittered(lat: float, lng: float, request_id: int) -> tuple[float, float]:
    """Offset a coordinate by up to ~300m, stable per request.

    Used only for the map-overview endpoint, where any authenticated user
    (not just a matched/accepted provider) can see pending-request pins.
    Seeding the jitter by request_id keeps a given pin visually stable
    across repeated map loads rather than jumping around randomly, while
    still not revealing the exact address. Precise coordinates remain
    available through the normal accept-a-job flow, where they're needed.
    """
    rng = random.Random(request_id)
    return (
        lat + rng.uniform(-0.003, 0.003),
        lng + rng.uniform(-0.003, 0.003),
    )


@router.get("/map/requests")
def map_requests(
    profession_type: Optional[str] = Query(default=None),
    status_filter: Optional[str] = Query(default="pending", alias="status"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all service requests with coordinates for map rendering."""
    q = db.query(ServiceRequest).filter(
        ServiceRequest.latitude.isnot(None),
        ServiceRequest.longitude.isnot(None),
    )
    if status_filter:
        q = q.filter(ServiceRequest.status == status_filter)
    if profession_type:
        q = q.filter(ServiceRequest.profession_type == profession_type)

    requests = q.all()

    results = []
    for r in requests:
        jlat, jlng = _jittered(r.latitude, r.longitude, r.id)
        results.append({
            "id": r.id,
            "title": r.title,
            "profession_type": r.profession_type,
            "location": r.location,
            "latitude": jlat,
            "longitude": jlng,
            "urgency": r.urgency,
            "budget_min": r.budget_min,
            "budget_max": r.budget_max,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
        })
    return results
