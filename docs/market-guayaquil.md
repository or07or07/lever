# Lever — Market restriction (Guayaquil launch)

Lever launches Guayaquil-only. The restriction is centralized in `market.py`
and enforced authoritatively on the backend — the frontend only guides.

## How it works

- **`market.py`** holds `MARKETS` (a registry keyed by market code) and
  `ACTIVE_MARKET_CODE = "GYE"`. Guayaquil carries a bounding box, accepted
  city names, province, and country.
- **`validate_service_location(...)`** is the single check. Coordinates, when
  present, decide (must be valid ranges AND inside the service-area box);
  otherwise a normalized city match is the gate. Country/province, when given,
  must not contradict the market. Returns `{supported, market_code,
  service_area_id}` or `{supported: false, reason}`.
- **Enforcement** lives in `POST /api/client/requests` (routes/client.py):
  every request is validated before creation. Unsupported → `422` with a
  reason code (`ADDRESS_OUTSIDE_GUAYAQUIL`, `INVALID_LOCATION`,
  `MARKET_NOT_ACTIVE`). `market_code` is assigned **server-side** and never
  read from the client payload, so the frontend cannot bypass the restriction
  by editing the request body. Dispatch/matching only runs after a request is
  validated and persisted, so unsupported addresses never reach professionals.
- **Public endpoints:** `GET /api/market` (active market, drives the landing
  copy so the launch city isn't hard-coded in the UI) and
  `POST /api/market/check-location` (advisory pre-check for the coverage
  section and request flow).
- **Frontend:** the guest request flow only offers the launch city (fixed
  Guayaquil chip + coverage banner), sends structured `city`/`province`/
  `country_code`, and shows out-of-area messaging + a future-city interest
  form (`/api/city-interest`, consent-gated) for everyone else.

## Adding another city later (e.g. Quito)

No changes to the request system, dispatch, or the frontend flow are needed.

1. In `market.py`, add a `MARKETS["UIO"]` entry (bounding box, city aliases,
   province) with `"status": "active"`.
2. Decide the model: to run **multiple** active cities, generalize
   `validate_service_location` to loop over active markets and return the
   first match (today it validates against the single `ACTIVE_MARKET_CODE`).
   To **switch** launch cities instead, just point `ACTIVE_MARKET_CODE` at the
   new code.
3. Providers already carry no city coupling beyond their free-text location;
   provider onboarding and matching read the same market layer.

The `service_requests.market_code` column already records which market each
request belongs to, so multi-market reporting works the moment a second
market goes active.

## Known limitations

- The Guayaquil area is a **bounding box**, not a precise polygon — it covers
  the city proper but deliberately not Samborondón/Durán/Daule. A polygon can
  replace `bbox` behind the same `validate_service_location` interface without
  touching callers.
- The guest flow has no map/geocoder yet, so requests without coordinates are
  validated on the (fixed) city. When map-based address selection is added,
  the coordinate path already takes precedence.
