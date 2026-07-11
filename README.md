# Lever — Multi-Profession Service Marketplace

Lever is an on-demand service marketplace that connects clients with verified service providers across five professions: **Mechanic**, **HVAC**, **Electrician**, **Construction**, and **Car Wash**.

## Quick Start

### Option 1: Docker (Recommended)

```bash
docker compose up -d
```

This starts PostgreSQL, Mailpit (dev email), and the Lever app. Open http://localhost:8500.

View emails at http://localhost:8025 (Mailpit UI).

### Option 2: Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Start the app (uses SQLite by default)
python app.py

# Seed demo data
python seed.py
```

### Default Accounts

| Role | Email | Password |
|------|-------|----------|
| Admin | admin@lever.app | Admin123! |
| Client | client@demo.lever | Demo1234! |
| Mechanic | mech@demo.lever | Demo1234! |

## Architecture

```
FastAPI Application (port 8500)
├── Auth        /api/auth/*          JWT + email verification + password reset
├── Client      /api/client/*        Profile, vehicles, requests, browse, reviews
├── Provider    /api/mechanic/*      Profile, job board, job management
├── Admin       /api/admin/*         Users, disputes, platform stats
├── Messages    /api/messages/*      REST messaging
├── Disputes    /api/disputes/*      Dispute creation
├── Notify      /api/notifications/* In-app notifications
├── WebSocket   /ws/messages/{id}    Real-time messaging
├── Health      /health              Operational status
└── Frontend    /*                   SPA (index.html)
```

## Professions

Each profession has its own specialty options, job status workflow, and service terminology:

| Profession | Specialties | Job Flow |
|------------|------------|----------|
| Mechanic | Engine, Brakes, A/C, Diagnostics... | accepted → en_route → diagnosing → repairing → completed |
| HVAC | AC Install, Heating, Duct Cleaning... | accepted → en_route → inspecting → servicing → completed |
| Electrician | Wiring, Panel Upgrade, EV Charger... | accepted → en_route → inspecting → working → completed |
| Construction | Framing, Drywall, Roofing, Concrete... | accepted → en_route → assessing → working → completed |
| Car Wash | Exterior, Interior, Ceramic Coating... | accepted → en_route → prepping → washing → completed |

## API Documentation

FastAPI auto-generates interactive API docs:

- **Swagger UI**: http://localhost:8500/docs
- **ReDoc**: http://localhost:8500/redoc

## Security

- JWT authentication (HS256, 24h expiry)
- Bcrypt password hashing (12 rounds)
- Email verification with hashed 6-digit codes
- Password reset with hashed codes + TTL
- Rate limiting on auth endpoints (login: 10/15min, register: 5/15min)
- Global API rate limit (120/min per IP)
- CORS restricted to allowed origins
- ISO 27001 control references throughout codebase

## Project Structure

```
08_Lever/
├── app.py                 # Application entry point + middleware
├── auth.py                # JWT + password hashing + role guards
├── config.py              # Settings (env vars / .env)
├── database.py            # SQLAlchemy engine + session (SQLite/PostgreSQL)
├── models.py              # Database models (User, Job, Vehicle, etc.)
├── schemas.py             # Pydantic v2 request/response schemas
├── professions.py         # Profession registry (5 professions)
├── email_service.py       # Email verification service
├── password_reset.py      # Password reset service (Day 30)
├── rate_limiter.py        # Sliding window rate limiter (Day 30)
├── websocket_manager.py   # WebSocket connection manager (Day 30)
├── seed.py                # Demo data seeder
├── routes/
│   ├── auth.py            # Register, login, verify, password reset
│   ├── client.py          # Client profile, vehicles, requests, reviews
│   ├── mechanic.py        # Provider profile, job board, job management
│   ├── admin.py           # Admin dashboard, user mgmt, disputes
│   ├── messages.py        # REST messaging
│   ├── disputes.py        # Dispute creation
│   ├── notifications.py   # In-app notifications (Day 30)
│   └── ws_messages.py     # WebSocket messaging (Day 30)
├── frontend/
│   └── index.html         # Single-page application
├── migrations/            # Alembic database migrations
├── tests/
│   └── test_e2e.py        # End-to-end tests
├── scripts/               # Infrastructure setup scripts
├── Dockerfile             # Container image (Day 30)
├── docker-compose.yml     # Dev environment (Day 30)
├── ROADMAP-30-60-90.md    # Development roadmap (Day 30)
└── requirements.txt       # Python dependencies
```

## Environment Variables

See `config.py` for all settings. Key variables:

| Variable | Default | Description |
|----------|---------|-------------|
| DATABASE_URL | sqlite:///data/lever.db | Database connection string |
| SECRET_KEY | (change me) | JWT signing key |
| SMTP_HOST | 10.0.23.25 | SMTP server hostname |
| SMTP_PORT | 1025 | SMTP server port |
| ADMIN_EMAIL | admin@lever.app | Bootstrap admin email |

## Development

```bash
# Run tests
python -m pytest tests/ -v

# Run with auto-reload
python app.py  # (debug=True in config)

# Generate Alembic migration
alembic revision --autogenerate -m "description"
alembic upgrade head
```

## Changelog

### v2.3.0 (Day 60 — 2026-03-27)

- Added geolocation support (latitude/longitude on provider profiles and service requests)
- Added advanced provider search with filters (location radius, profession, price, rating, experience)
- Added Haversine distance calculation for radius-based search
- Added geocoding endpoint using OpenStreetMap Nominatim (free, no API key)
- Added interactive map view with Leaflet + OpenStreetMap tiles
- Added split view (list + map side-by-side) for provider search
- Added map data endpoints for lightweight marker rendering
- Added nearby service requests search for providers
- Updated seed data with realistic Austin, TX coordinates
- Updated frontend with search controls, map view, and distance badges
- Added httpx dependency for geocoding HTTP client

### v2.2.0 (Day 30 — 2026-03-27)

- Added rate limiting middleware (enforcing config limits)
- Added password reset flow (request + verify + new password)
- Added WebSocket real-time messaging (/ws/messages/{job_id})
- Added in-app notification system (model + API)
- Added Docker Compose configuration (PostgreSQL + Mailpit + App)
- Added Dockerfile for containerized deployment
- Added 30-60-90 development roadmap
- Added comprehensive README
- Enhanced health endpoint with feature flags
- Updated app.py to register all new routes and middleware

### v2.1.0 (Baseline)

- Multi-profession support (5 professions)
- Email verification system
- Full CRUD for all entities
- Admin dashboard with stats
- Messaging and review system
- Dispute resolution
