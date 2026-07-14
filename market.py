"""Lever — Active-market configuration and service-area validation.

Single source of truth for where Lever currently operates. Launch is
Guayaquil-only; the structure is deliberately a registry keyed by market
code so Quito/Cuenca/etc. can be switched on later by adding a MARKETS
entry and a service area — without touching the request system.

The backend is the authoritative enforcement point (frontend validation
only guides the user). Nothing the client sends — market_code, coordinates,
a hand-typed "Guayaquil" — is trusted on its own; create-request calls
validate_service_location() server-side.
"""
from __future__ import annotations

from typing import Optional, TypedDict

# ---------------------------------------------------------------------------
# Active markets
# ---------------------------------------------------------------------------

MARKETS: dict[str, dict] = {
    "GYE": {
        "code": "GYE",
        "country_code": "EC",
        "country_name": "Ecuador",
        "province": "Guayas",
        "city": "Guayaquil",
        "currency": "USD",
        "locale": "es-EC",
        "timezone": "America/Guayaquil",
        "status": "active",
        # Approximate bounding box for the Guayaquil urban service area.
        # Used when a request carries coordinates. Deliberately conservative:
        # it covers the city proper but NOT Samborondón/Durán/Daule, matching
        # the "don't claim we cover the whole province" requirement. A precise
        # polygon can replace this later without changing the interface.
        "service_area_id": "guayaquil-primary",
        "bbox": {"min_lat": -2.32, "max_lat": -2.05, "min_lng": -80.05, "max_lng": -79.80},
        # City strings we accept as "Guayaquil" (accent/spacing tolerant match
        # happens in _norm). Kept explicit so a typo like "Guayaquil " or a
        # neighboring city can't slip through on the text path.
        "city_aliases": ["guayaquil"],
    },
}

# The one market currently open for business. Everything user-facing reads
# from here so flipping the launch city is a one-line change.
ACTIVE_MARKET_CODE = "GYE"


def active_market() -> dict:
    return MARKETS[ACTIVE_MARKET_CODE]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class LocationResult(TypedDict, total=False):
    supported: bool
    market_code: str
    service_area_id: str
    reason: str


def _norm(text: Optional[str]) -> str:
    """Lowercase, strip accents/extra spaces so 'Guayaquil' == 'guayaquil '."""
    if not text:
        return ""
    import unicodedata
    t = "".join(
        c for c in unicodedata.normalize("NFD", text.strip().lower())
        if unicodedata.category(c) != "Mn"
    )
    return " ".join(t.split())


def _in_bbox(lat: float, lng: float, bbox: dict) -> bool:
    return (
        bbox["min_lat"] <= lat <= bbox["max_lat"]
        and bbox["min_lng"] <= lng <= bbox["max_lng"]
    )


def validate_service_location(
    *,
    country_code: Optional[str] = None,
    province: Optional[str] = None,
    city: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> LocationResult:
    """Authoritative check that a service address is inside an active market.

    Rules (in order):
    - The market must be active.
    - If coordinates are present they are the strongest signal: they must be
      valid ranges AND fall inside the market's service-area box.
    - If no coordinates, fall back to a normalized city match against the
      market's accepted city names (NOT a bare substring of user text).
    - country_code / province, when provided, must not contradict the market.

    Returns {"supported": True, "market_code", "service_area_id"} or
    {"supported": False, "reason": <CODE>}.
    """
    market = active_market()
    if market["status"] != "active":
        return {"supported": False, "reason": "MARKET_NOT_ACTIVE"}

    # Coordinate validation (when present, they decide).
    has_coords = latitude is not None and longitude is not None
    if has_coords:
        try:
            lat, lng = float(latitude), float(longitude)
        except (TypeError, ValueError):
            return {"supported": False, "reason": "INVALID_LOCATION"}
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0):
            return {"supported": False, "reason": "INVALID_LOCATION"}
        if not _in_bbox(lat, lng, market["bbox"]):
            return {"supported": False, "reason": "ADDRESS_OUTSIDE_GUAYAQUIL"}

    # Country/province must not contradict the active market when supplied.
    if country_code and _norm(country_code) not in (_norm(market["country_code"]), _norm(market["country_name"])):
        return {"supported": False, "reason": "ADDRESS_OUTSIDE_GUAYAQUIL"}
    if province and _norm(province) != _norm(market["province"]):
        return {"supported": False, "reason": "ADDRESS_OUTSIDE_GUAYAQUIL"}

    # City check — the text-path gate when there are no coordinates.
    if not has_coords:
        if _norm(city) not in [_norm(a) for a in market["city_aliases"]]:
            return {"supported": False, "reason": "ADDRESS_OUTSIDE_GUAYAQUIL"}

    return {
        "supported": True,
        "market_code": market["code"],
        "service_area_id": market["service_area_id"],
    }
