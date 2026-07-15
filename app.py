"""Lever – FastAPI application entry point.

Multi-profession on-demand service marketplace.
Supported professions: Mechanic, HVAC, Electrician, Construction, Car Wash.

CIA Triad Alignment:
  Confidentiality: CORS restricted, JWT auth on all protected endpoints, rate limiting
  Integrity:       Email verification enforced, request timing logged, input validation
  Availability:    Health endpoint, graceful startup, SMTP failure non-blocking

Day 30 additions:
  - Rate limiting middleware (enforced, not just config)
  - WebSocket real-time messaging endpoint
  - Notification system routes
  - Password reset routes (in auth router)

Day 60 additions:
  - Search + Geolocation routes (provider search, nearby requests, geocoding, map data)
"""
from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import List

from sqlalchemy import text
from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings
from models import Base, User
from auth import hash_password
from database import SessionLocal
from professions import PROFESSIONS, PROFESSION_KEYS

# Route routers
from routes.auth import router as auth_router
from routes.client import router as client_router
from routes.provider import router as provider_router
from routes.admin import router as admin_router
from routes.messages import router as messages_router
from routes.disputes import router as disputes_router
from routes.notifications import router as notifications_router
from routes.ws_messages import router as ws_router
from routes.search import router as search_router  # Day 60
from routes.tracking import router as tracking_router  # GPS Live Tracking
from routes.moderation import router as moderation_router  # Reports + blocking (GP-08)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(name)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("lever")

# ---------------------------------------------------------------------------
# Startup – ensure DB tables + admin user
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    from database import engine
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        admin = db.query(User).filter(User.email == settings.admin_email).first()
        if not admin:
            admin = User(
                email=settings.admin_email,
                password_hash=hash_password(settings.admin_password),
                role="admin",
                is_active=True,
                email_verified=True,  # Admin is pre-verified
            )
            db.add(admin)
            db.commit()
            logger.info(f"Admin user created: {settings.admin_email}")
        else:
            # Ensure existing admin is verified
            if not admin.email_verified:
                admin.email_verified = True
                db.commit()
                logger.info(f"Admin user marked as verified: {settings.admin_email}")
            else:
                logger.info(f"Admin user exists: {settings.admin_email}")
    finally:
        db.close()

    logger.info(f"SMTP configured: {settings.smtp_host}:{settings.smtp_port}")
    logger.info(f"Professions loaded: {', '.join(PROFESSION_KEYS)}")
    logger.info("Security headers middleware: ACTIVE (defense in depth)")
    logger.info("Rate limiting middleware: ACTIVE")
    logger.info("WebSocket messaging: ACTIVE (/ws/messages/{job_id})")
    logger.info("Notifications system: ACTIVE (/api/notifications)")
    logger.info("Search + Geolocation: ACTIVE (/api/search/*)")
    logger.info("GPS Live Tracking: ACTIVE (/ws/tracking/{job_id}/*)")

    yield


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Multi-profession on-demand service marketplace API",
    lifespan=lifespan,
    # In production (DEBUG=false) don't expose the interactive Swagger/ReDoc
    # UI or the raw OpenAPI schema — the endpoints are auth-protected, but
    # publishing the full API surface only aids attacker enumeration. These
    # stay available in local development for convenience.
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    openapi_url="/openapi.json" if settings.debug else None,
)

# Security Headers Middleware (defense in depth — supplements nginx headers)
from security_middleware import SecurityHeadersMiddleware, TrustedProxyMiddleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(TrustedProxyMiddleware)

# Rate Limiting Middleware (Day 30 – enforces config.py rate limits)
from rate_limiter import RateLimitMiddleware
app.add_middleware(RateLimitMiddleware)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Local development
        "http://localhost:8500",
        "http://127.0.0.1:8500",
        "http://0.0.0.0:8500",
        # Production — real domain, DNS pointed directly at this VPS (HTTPS enforced)
        "https://lever-ec.com",
        "https://www.lever-ec.com",
        # Legacy placeholder domain — HTTPS enforced
        "https://lever.test-test-now.com",
        # HTTP fallback (redirect to HTTPS via nginx, but allow during transition)
        "http://lever.test-test-now.com",
        # Capacitor native app WebView (bundled mode — Android default origin)
        "https://localhost",
        # Capacitor native app WebView (iOS default origin, if/when iOS is added)
        "capacitor://localhost",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
)


# ---------------------------------------------------------------------------
# Request timing middleware
# ---------------------------------------------------------------------------

@app.middleware("http")
async def log_requests(request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = (time.time() - start) * 1000
    if elapsed > 500:
        logger.warning(f"SLOW {request.method} {request.url.path} – {elapsed:.0f}ms")
    return response


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

@app.get("/health", tags=["ops"])
def health():
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        ram = psutil.virtual_memory().percent
    except ImportError:
        cpu = ram = None

    db = SessionLocal()
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    finally:
        db.close()

    # Check SMTP connectivity
    smtp_ok = True
    try:
        import smtplib, ssl
        if settings.smtp_port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, context=ctx, timeout=3) as s:
                s.login(settings.smtp_user, settings.smtp_password)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=3) as s:
                s.starttls()
                s.login(settings.smtp_user, settings.smtp_password)
    except Exception:
        smtp_ok = False

    from database import engine
    db_backend = str(engine.url).split("://")[0]

    payload = {
        "status": "healthy" if (db_ok and smtp_ok) else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "database": db_backend,
        "database_ok": db_ok,
        "smtp_ok": smtp_ok,
        "smtp_host": f"{settings.smtp_host}:{settings.smtp_port}",
        "professions": PROFESSION_KEYS,
        "features": {
            "rate_limiting": True,
            "websocket_messaging": True,
            "notifications": True,
            "password_reset": True,
            "email_verification": True,
            "geolocation_search": True,  # Day 60
            "gps_live_tracking": True,    # GPS Live Tracking
            "security_headers": True,     # Defense-in-depth security headers
        },
    }
    if cpu is not None:
        payload["cpu_pct"] = cpu
        payload["ram_pct"] = ram

    status_code = 200 if db_ok else 503
    return JSONResponse(payload, status_code=status_code)


# ---------------------------------------------------------------------------
# Professions endpoint (public – no auth required)
# ---------------------------------------------------------------------------

@app.get("/api/professions", tags=["professions"])
def list_professions():
    """Return all available professions with their metadata."""
    return [
        {
            "key": key,
            "label": p["label"],
            "icon": p["icon"],
            "description": p["description"],
            "specialties": p["specialties"],
            "service_noun": p["service_noun"],
            "vehicle_required": p["vehicle_required"],
            "job_statuses": p["job_statuses"],
        }
        for key, p in PROFESSIONS.items()
    ]


# ---------------------------------------------------------------------------
# Service catalog (public – guests browse before authenticating; see
# docs/service-catalog-ux-audit.md §9. Source of truth: services_catalog.py)
# ---------------------------------------------------------------------------

@app.get("/api/catalog", tags=["catalog"])
def get_catalog(response: Response):
    """Categories + every active service, both languages. Public and cacheable."""
    from services_catalog import ALL_SERVICES
    response.headers["Cache-Control"] = "public, max-age=300"
    categories = [
        {"key": key, "label": p["label"], "icon": p["icon"], "description": p["description"]}
        for key, p in PROFESSIONS.items()
    ]
    return {"categories": categories, "services": [s for s in ALL_SERVICES if s["is_active"]]}


@app.get("/api/catalog/search", tags=["catalog"])
def catalog_search(q: str = "", lang: str = "es"):
    """Search services by name, description and es-EC keyword synonyms."""
    from services_catalog import search_services
    if len(q) > 100:
        q = q[:100]
    return search_services(q, lang="en" if lang == "en" else "es", limit=20)


# ---------------------------------------------------------------------------
# Active market / service-area coverage (public — the landing page and the
# request flow read this so the launch city isn't hard-coded in the UI)
# ---------------------------------------------------------------------------

@app.get("/api/market", tags=["market"])
def get_market():
    """The currently active market (Guayaquil at launch). Public + cacheable."""
    from market import active_market
    m = active_market()
    return {
        "code": m["code"], "city": m["city"], "province": m["province"],
        "country_name": m["country_name"], "currency": m["currency"],
        "locale": m["locale"], "status": m["status"],
    }


@app.post("/api/market/check-location", tags=["market"])
def check_location(payload: dict):
    """Advisory address check for the coverage section / request flow. The
    authoritative check still runs server-side at request creation — this
    just lets the UI guide the user early."""
    from market import validate_service_location
    return validate_service_location(
        country_code=payload.get("country_code"),
        province=payload.get("province"),
        city=payload.get("city"),
        latitude=payload.get("latitude"),
        longitude=payload.get("longitude"),
    )


@app.post("/api/city-interest", tags=["market"], status_code=201)
def register_city_interest(payload: dict):
    """Capture interest from a visitor outside the active market. Stored only
    when the user gives explicit consent (checkbox enforced client-side; the
    server still requires a city). No marketing list, just planning data."""
    from database import SessionLocal
    from models import CityInterest
    city = (payload.get("city") or "").strip()[:120]
    if not city:
        return JSONResponse({"detail": "city is required"}, status_code=422)
    db = SessionLocal()
    try:
        row = CityInterest(
            city=city,
            province=(payload.get("province") or "").strip()[:120],
            service_category=(payload.get("service_category") or "").strip()[:80],
            contact=(payload.get("contact") or "").strip()[:255],
        )
        db.add(row)
        db.commit()
        return {"ok": True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API Routers
# ---------------------------------------------------------------------------

app.include_router(auth_router)
app.include_router(client_router)
app.include_router(provider_router)
app.include_router(admin_router)
app.include_router(messages_router)
app.include_router(disputes_router)
app.include_router(notifications_router)  # Day 30
app.include_router(ws_router)             # Day 30 – WebSocket
app.include_router(search_router)         # Day 60 – Search + Geolocation
app.include_router(tracking_router)       # GPS Live Tracking
app.include_router(moderation_router)     # Reports + blocking (GP-08)


# ---------------------------------------------------------------------------
# Frontend static files
# ---------------------------------------------------------------------------

FRONTEND_DIR = Path(__file__).parent / "frontend"
LEGAL_DIR = FRONTEND_DIR / "legal"


# ---------------------------------------------------------------------------
# Public legal / support pages — real, static, always reachable without
# authentication and without depending on the SPA's JS bundle loading
# correctly. Registered before the SPA catch-all below so they take
# priority over it. (See docs/google-play-readiness.md, GP-05/GP-06.)
# ---------------------------------------------------------------------------

@app.get("/privacy", include_in_schema=False)
def serve_privacy():
    return FileResponse(LEGAL_DIR / "privacy.html")


@app.get("/terms", include_in_schema=False)
def serve_terms():
    return FileResponse(LEGAL_DIR / "terms.html")


@app.get("/support", include_in_schema=False)
def serve_support():
    return FileResponse(LEGAL_DIR / "support.html")


@app.get("/delete-account", include_in_schema=False)
def serve_delete_account():
    return FileResponse(LEGAL_DIR / "delete-account.html")


@app.get("/", include_in_schema=False)
@app.get("/{path:path}", include_in_schema=False)
def serve_frontend(path: str = ""):
    """Serve the SPA – any non-API path returns index.html."""
    file_path = FRONTEND_DIR / path
    if file_path.is_file():
        return FileResponse(file_path)
    return FileResponse(FRONTEND_DIR / "index.html")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    logger.info(f"Starting on {settings.host}:{settings.port}")
    uvicorn.run(
        "app:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
