# Lever — 30-60-90 Day Development Roadmap

## Mission

**Lever** exists to help Ecuador — a country rich in professional talent — generate more jobs and economic opportunity. It is a multi-profession on-demand service marketplace (like Uber, but for skilled trades and services) connecting clients who need home and auto services with verified providers: mechanics, HVAC technicians, electricians, construction professionals, and car wash detailers.

The platform removes friction on both sides of the marketplace so that more professionals find work and more clients find reliable, trusted service providers.

## End Goal

A production-ready, scalable platform where:

1. **Clients** can post service requests, browse verified providers, track job progress in real time, exchange messages, leave reviews, and resolve disputes
2. **Providers** can manage their profile, browse profession-filtered job boards, accept jobs, update status through profession-specific workflows, and build reputation through ratings
3. **Admins** can manage users, moderate disputes, view platform analytics, and oversee operations
4. The system is secure (defense-in-depth), observable (logging + health checks), resilient (PostgreSQL + Docker), and deployable to production with CI/CD
5. **Deployment documentation** is comprehensive and battle-tested for both Windows Server and Linux environments — zero ambiguity, zero room for failure

---

## Current State (v2.3.0)

### What Exists
- FastAPI backend with JWT auth + email verification (6-digit code, bcrypt hashed)
- SQLAlchemy ORM with SQLite/PostgreSQL dual support
- 5 professions: Mechanic, HVAC, Electrician, Construction, Car Wash
- Roles: client, mechanic (provider), admin
- Full CRUD: service requests, jobs, vehicles, profiles, messages, reviews, disputes
- Admin dashboard with platform stats + user management
- Single-file SPA frontend (vanilla JS)
- Alembic migrations, seed data, setup/start batch scripts
- Security: CORS, bcrypt passwords, hashed verification codes, rate limiting, ISO 27001 references
- Health endpoint with DB + SMTP checks
- Rate limiting middleware (enforced)
- Password reset flow (request + verify + reset)
- WebSocket real-time messaging
- In-app notification system
- Search + Geolocation (advanced provider search, map view, geocoding, Haversine distance)
- Docker Compose (PostgreSQL + Mailpit + App)
- Comprehensive README and architecture documentation

### What's Missing
- [ ] File upload system (profile photos, job attachments)
- [ ] Provider availability calendar/scheduling
- [ ] Email notifications for job status changes
- [ ] Payment integration (Stripe Connect or local Ecuador options)
- [ ] Frontend migration to React/Vue component architecture
- [ ] API versioning (v1 prefix)
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Automated test coverage > 60%
- [ ] CSRF protection middleware
- [ ] Request ID tracing for observability
- [ ] Performance optimization (query N+1 fixes, caching)
- [ ] Multilingual support (English/Spanish — critical for Ecuador)
- [ ] Mobile-responsive PWA
- [ ] Production deployment documentation (Windows Server + Linux)

---

## Day 30 — Hardening + Missing Core Features ✅

**Goal:** Close security gaps, add operational infrastructure, implement missing core features.

### Deliverables
- [x] 30-60-90 Roadmap document
- [x] Docker Compose (PostgreSQL + Mailpit + App)
- [x] Rate limiting middleware (enforce existing config)
- [x] Password reset flow (request + verify + reset)
- [x] WebSocket real-time messaging upgrade
- [x] In-app notification system (model + routes + frontend)
- [x] Frontend CSS deduplication and UX fixes
- [x] Comprehensive README.md
- [x] Architecture documentation

---

## Day 60 — Scale + Polish + Provider Tools

**Goal:** Production-grade features, enhanced provider experience, payment groundwork.

### Planned Deliverables
- [ ] File upload system (profile photos, job attachments)
- [x] Geolocation: map view for service requests + provider radius
- [ ] Provider availability calendar/scheduling
- [x] Advanced search with filters (location radius, price range, rating)
- [ ] Email notifications for job status changes
- [ ] Payment integration groundwork (Stripe Connect or local Ecuador options)
- [ ] Frontend migration to React SPA (or Vue) with component architecture
- [ ] API versioning (v1 prefix)
- [ ] CI/CD pipeline (GitHub Actions)
- [ ] Automated test coverage > 60%
- [ ] CSRF protection middleware
- [ ] Request ID tracing for observability
- [ ] Performance optimization (query N+1 fixes, caching)
- [x] Deployment documentation — Windows Server + Linux (internal, zero-failure)

---

## Day 90 — Production Launch + Analytics + Growth

**Goal:** Production-ready deployment with monitoring, analytics, and growth features for Ecuador market.

### Planned Deliverables
- [ ] Production deployment (Docker + cloud hosting + domain + TLS)
- [ ] Monitoring & alerting (Prometheus metrics, Grafana dashboards)
- [ ] Platform analytics dashboard (revenue, conversion, retention)
- [ ] Provider verification/badge system
- [ ] Client loyalty/referral program
- [ ] Multilingual support (English/Spanish) — critical for Ecuador
- [ ] Mobile-responsive PWA conversion
- [ ] Load testing and capacity planning
- [ ] Security audit (OWASP Top 10 review)
- [ ] Backup and disaster recovery procedures
- [ ] Operational runbook
- [ ] WCAG 2.1 AA accessibility audit
- [ ] SEO optimization
- [ ] Admin reporting and export tools
- [ ] Ecuador-specific payment methods research (bank transfers, mobile payments)
- [ ] Local hosting/cloud options for Ecuador (latency optimization)

---

## Architecture

```
Client Browser (SPA)
       |
       v
  FastAPI Application (app.py)
  ├── /api/auth     — Registration, login, email verification, password reset
  ├── /api/client   — Profile, vehicles, service requests, browse providers, reviews
  ├── /api/mechanic — Provider profile, job board, job management, status transitions
  ├── /api/admin    — User management, disputes, platform stats
  ├── /api/messages — REST + WebSocket messaging
  ├── /api/disputes — Dispute creation
  ├── /api/notifications — In-app notifications
  ├── /api/search   — Provider search, nearby requests, geocoding, map data
  ├── /ws/messages  — WebSocket real-time messaging
  └── /health       — Operational health check
       |
       v
  PostgreSQL (production) / SQLite (development)
       |
       v
  SMTP Server (Mailpit dev / Postfix production)
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------
| Backend | Python 3.11+ / FastAPI |
| ORM | SQLAlchemy 2.0 |
| Migrations | Alembic |
| Auth | JWT (python-jose) + bcrypt |
| Email | SMTP (smtplib) |
| Database | PostgreSQL 16 (prod) / SQLite (dev) |
| Frontend | Vanilla JS SPA (single index.html) |
| Geolocation | Haversine + OpenStreetMap Nominatim + Leaflet.js |
| Container | Docker + Docker Compose |
| Dev Mail | Mailpit |

---

*Last updated: 2026-03-27 — Day 60 build phase (v2.3.0)*
