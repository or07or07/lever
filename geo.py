"""Lever — Geolocation utilities.

Provides:
  - Haversine distance calculation (works with SQLite and PostgreSQL)
  - Geocoding via OpenStreetMap Nominatim (free, no API key)
  - Bounding-box pre-filter for efficient radius queries

CIA Triad Alignment:
  Confidentiality: No user location data sent to third parties beyond geocoding
  Integrity:       Validated lat/lng ranges, Haversine formula accuracy
  Availability:    Geocoding failures are non-blocking (graceful degradation)

Day 60 addition — Search + Geolocation feature.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Optional, Tuple

import httpx

logger = logging.getLogger("lever.geo")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
EARTH_RADIUS_MILES = 3958.8  # Mean radius in miles
EARTH_RADIUS_KM = 6371.0    # Mean radius in kilometers

# Nominatim requires a descriptive User-Agent (their usage policy)
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_REVERSE_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_USER_AGENT = "Lever/2.3.0 (service-marketplace; contact: admin@lever.app)"

# Photon (Komoot) — OSM-based geocoder built for type-ahead autocomplete.
# Used instead of Nominatim for address suggestions because Nominatim's usage
# policy forbids autocomplete. No API key required.
PHOTON_URL = "https://photon.komoot.io/api"

# Guayaquil-area bias for address autocomplete, so suggestions stay local.
# Mirrors the active market's service area (see market.py). bbox is
# (min_lon, min_lat, max_lon, max_lat) as Photon expects.
_GYE_BIAS_LAT = -2.17
_GYE_BIAS_LNG = -79.90
_GYE_BBOX = (-80.05, -2.35, -79.75, -2.05)

# Rate limit: max 1 request per second per Nominatim policy
_last_geocode_time: float = 0.0


# ---------------------------------------------------------------------------
# Haversine distance
# ---------------------------------------------------------------------------

def haversine_miles(
    lat1: float, lng1: float,
    lat2: float, lng2: float,
) -> float:
    """Calculate the great-circle distance between two points in miles.

    Uses the Haversine formula, which is accurate to within ~0.3% for
    distances under 1000 miles — more than sufficient for service radius.
    """
    lat1_r, lng1_r = math.radians(lat1), math.radians(lng1)
    lat2_r, lng2_r = math.radians(lat2), math.radians(lng2)

    dlat = lat2_r - lat1_r
    dlng = lng2_r - lng1_r

    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1_r) * math.cos(lat2_r) * math.sin(dlng / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_MILES * c


# ---------------------------------------------------------------------------
# Bounding box pre-filter
# ---------------------------------------------------------------------------

def bounding_box(
    lat: float, lng: float, radius_miles: float
) -> Tuple[float, float, float, float]:
    """Return (min_lat, max_lat, min_lng, max_lng) for a rough bounding box.

    This is used as a cheap pre-filter before the more expensive Haversine
    calculation, dramatically reducing the number of rows that need the
    full trigonometric computation.
    """
    # 1 degree of latitude ~ 69.0 miles
    lat_delta = radius_miles / 69.0
    # 1 degree of longitude varies by latitude
    lng_delta = radius_miles / (69.0 * math.cos(math.radians(lat)))

    return (
        lat - lat_delta,  # min_lat
        lat + lat_delta,  # max_lat
        lng - lng_delta,  # min_lng
        lng + lng_delta,  # max_lng
    )


# ---------------------------------------------------------------------------
# Geocoding (OpenStreetMap Nominatim — free, no key)
# ---------------------------------------------------------------------------

def geocode(address: str) -> Optional[Tuple[float, float]]:
    """Geocode an address string to (latitude, longitude) using Nominatim.

    Returns None on failure (network error, no results, rate limit).
    Respects Nominatim's 1-request-per-second rate limit policy.
    """
    global _last_geocode_time

    if not address or not address.strip():
        return None

    # Enforce rate limit
    elapsed = time.time() - _last_geocode_time
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                NOMINATIM_URL,
                params={
                    "q": address.strip(),
                    "format": "json",
                    "limit": 1,
                    "addressdetails": 0,
                },
                headers={"User-Agent": NOMINATIM_USER_AGENT},
            )
            _last_geocode_time = time.time()

            if resp.status_code != 200:
                logger.warning(f"Geocoding HTTP {resp.status_code} for '{address}'")
                return None

            results = resp.json()
            if not results:
                logger.info(f"Geocoding: no results for '{address}'")
                return None

            lat = float(results[0]["lat"])
            lng = float(results[0]["lon"])
            logger.info(f"Geocoded '{address}' -> ({lat:.6f}, {lng:.6f})")
            return (lat, lng)

    except Exception as e:
        logger.warning(f"Geocoding error for '{address}': {e}")
        return None


# ---------------------------------------------------------------------------
# Address autocomplete (Photon) + reverse geocoding (Nominatim)
# ---------------------------------------------------------------------------

def _photon_label(props: dict) -> str:
    """Build a readable one-line address from Photon feature properties."""
    parts = []
    street = props.get("street")
    house = props.get("housenumber")
    name = props.get("name")
    if street and house:
        parts.append(f"{street} {house}")
    elif street:
        parts.append(street)
    elif name:
        parts.append(name)
    for key in ("district", "city", "state"):
        v = props.get(key)
        if v and v not in parts:
            parts.append(v)
    label = ", ".join(parts)
    return label or (name or "")


def search_addresses(query: str, limit: int = 6) -> list:
    """Type-ahead address search via Photon, biased to the Guayaquil area.

    Returns a list of {"label", "latitude", "longitude"} dicts. Empty list on
    any failure (network, bad status, no results) — the caller degrades to
    plain text entry, so this is never fatal.
    """
    q = (query or "").strip()
    if len(q) < 3:
        return []
    try:
        params = {
            "q": q,
            "limit": max(1, min(limit, 10)),
            "lat": _GYE_BIAS_LAT,
            "lon": _GYE_BIAS_LNG,
            "bbox": ",".join(str(x) for x in _GYE_BBOX),
        }
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(
                PHOTON_URL, params=params,
                headers={"User-Agent": NOMINATIM_USER_AGENT},
            )
        if resp.status_code != 200:
            logger.warning(f"Photon HTTP {resp.status_code} for '{q}'")
            return []
        out = []
        for feat in (resp.json() or {}).get("features", []):
            coords = ((feat.get("geometry") or {}).get("coordinates")) or []
            if len(coords) != 2:
                continue
            out.append({
                "label": _photon_label(feat.get("properties") or {}),
                "latitude": float(coords[1]),
                "longitude": float(coords[0]),
            })
        return out
    except Exception as e:
        logger.warning(f"Photon search error for '{q}': {e}")
        return []


def reverse_geocode(lat: float, lng: float) -> Optional[str]:
    """Reverse-geocode coordinates to a display address via Nominatim.

    A single call per pin drop is well within Nominatim's 1 req/sec policy.
    Returns None on failure.
    """
    global _last_geocode_time
    if not is_valid_coords(lat, lng):
        return None

    elapsed = time.time() - _last_geocode_time
    if elapsed < 1.1:
        time.sleep(1.1 - elapsed)

    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(
                NOMINATIM_REVERSE_URL,
                params={"lat": lat, "lon": lng, "format": "json", "zoom": 18, "addressdetails": 0},
                headers={"User-Agent": NOMINATIM_USER_AGENT},
            )
            _last_geocode_time = time.time()
        if resp.status_code != 200:
            logger.warning(f"Reverse geocode HTTP {resp.status_code} for ({lat}, {lng})")
            return None
        return (resp.json() or {}).get("display_name")
    except Exception as e:
        logger.warning(f"Reverse geocode error for ({lat}, {lng}): {e}")
        return None


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def is_valid_lat(lat: Optional[float]) -> bool:
    """Check if latitude is within valid range [-90, 90]."""
    return lat is not None and -90.0 <= lat <= 90.0


def is_valid_lng(lng: Optional[float]) -> bool:
    """Check if longitude is within valid range [-180, 180]."""
    return lng is not None and -180.0 <= lng <= 180.0


def is_valid_coords(lat: Optional[float], lng: Optional[float]) -> bool:
    """Check if both lat and lng are valid."""
    return is_valid_lat(lat) and is_valid_lng(lng)
