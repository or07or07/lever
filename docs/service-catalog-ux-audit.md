# Lever — Service Catalog & Mobile UX Audit (Phase 1)

Date: 2026-07-13
Status: **Audit complete — awaiting owner decisions before Phase 2 (see §9)**

This audit was produced by inspecting the running codebase, not from assumptions.
Where a claim references behavior, the file and line context is given. It builds on
(and does not repeat) `docs/google-play-readiness.md`, which already resolved the
trust-and-safety layer this spec asks for (reporting, blocking, account deletion,
legal pages, coordinate privacy, admin moderation, admin MFA).

---

## 1. Architecture snapshot

| Layer | What it actually is |
|---|---|
| Frontend | **One vanilla-JS single file** — `frontend/index.html` (~4,400 lines): inline CSS design tokens, inline `_translations` dict (es/en), hash routing (`#/...`), no build step, no framework |
| Mobile | Capacitor wraps that same file into two Android apps: `apps/client` (`com.lever.app`) and `apps/provider` (`com.lever.provider`), differentiated by an `appFlavor` config read at runtime |
| Backend | FastAPI + SQLAlchemy + Alembic; PostgreSQL in prod (Docker), SQLite in dev |
| Realtime | WebSocket chat per job (`routes/ws_messages.py`), GPS live tracking (`routes/tracking.py`), in-app notification polling |
| Auth | JWT (24h) with token-version revocation, email verification, admin TOTP MFA |
| Catalog | `professions.py` — a **flat, code-defined registry of 12 professions** (just replaced; migration `0006`). One level only: no services, no service options |
| Payments | **None, deliberately** — owner decision during Play-readiness work: launch fee-free, no processor, no fee claims anywhere |
| Media/files | **None** — no upload endpoint, no storage, no images anywhere in the product (avatars are URL strings nobody can set from the UI) |

### Current database tables
`users`, `client_profiles`, `mechanic_profiles` (provider profile; holds ONE
profession + specialty chips + hourly rate + radius + geo + online state),
`vehicles`, `service_requests` (profession_type + free-text title/description +
location + urgency + budget range + geo), `jobs` (status flow per profession),
`messages`, `reviews` (single rating + comment), `disputes`, `notifications`,
`request_dispatches` (auto-dispatch queue), `provider_locations` (GPS breadcrumbs),
`reports`, `blocks`.

### The current matching model (critical to understand before changing anything)
`dispatch.py`: when a client creates a request, the system finds online providers
matching the profession (distance+rating ranked), then offers the job to **one
provider at a time with a 30-second acceptance window**, rotating until someone
accepts. Providers can also browse an open board and accept directly. **First to
accept wins. There are no estimates, no offers, no comparison, no customer choice
after submission** (except an optional "preferred provider" picker for immediate
requests). This is a dispatch model (like ride-hailing), not a quotes marketplace
(like Thumbtack). The spec's flow 7–8 ("receive or compare provider offers → hire")
does not exist and is the single largest structural change requested.

---

## 2. Current workflows (as-built)

### Customer
1. Register (role client, terms acceptance) → email verification gate
2. Dashboard: stat cards + a **table** of requests (`renderClientDash`, frontend/index.html:1889) — an admin-console layout, not a marketplace home. No search, no category grid, no location selector
3. "Nueva Solicitud" — **one generic modal form for all 12 professions** (`showNewRequest`, :1952): profession dropdown → title → description → location text → optional vehicle → urgency → optional budget. No photos, no schedule picker beyond a date for "scheduled", no service-specific questions
4. Auto-dispatch assigns a provider (or a provider self-accepts from the board)
5. Status tracker + live GPS map + chat per job
6. Complete → single-dimension review (1–5 + comment)

### Provider
1. Register with **exactly one** profession → profile (name, phone, bio, specialty
   chips from the profession's list, years, hourly rate, location, radius)
2. Go online (heartbeat) → board of pending requests for their profession
3. Accept → walk the per-profession status flow → complete
4. No availability hours, no earnings view (no payments), no portfolio, no
   estimates, no way to serve multiple professions or opt out of specific services

---

## 3. Issue catalog

Severity: **Blocker** = blocks the spec's main customer journey; **High** = major
UX/competitive gap; **Medium** = quality gap; **Low** = polish.

| # | Issue | Severity | Blocks journey? | Affected files | Recommendation |
|---|---|---|---|---|---|
| UX-01 | No service level below profession — customer must write a free-text title/description instead of tapping "Destape de cañerías" | **Blocker** | Yes (steps 2–3) | `professions.py`, `models.py`, `frontend/index.html` | Add `Service` catalog table + browse UI (Phase 2) |
| UX-02 | No estimates/offers — auto-dispatch assigns first acceptor; customer cannot compare anything | **Blocker** | Yes (steps 7–8) | `dispatch.py`, `models.py`, `routes/provider.py`, frontend | Add `Offer` model + hybrid booking (see §6); keep dispatch for instant-book services |
| UX-03 | No photo upload anywhere (requests, chat, portfolios, reviews) | **Blocker** | Yes (step 5) | whole stack — no media infra exists | Add upload endpoint + storage + compression (Phase 3; storage decision needed, §9) |
| UX-04 | One generic request form for every service; no service-specific questions | **Blocker** | Yes (step 4) | `showNewRequest` frontend/index.html:1952 | Dynamic forms driven by per-service question config (Phase 3) |
| UX-05 | No date/time scheduling — only "immediate vs scheduled + a date"; providers have no working hours or availability | High | Partially (step 6) | `models.py`, request form, provider profile | Add provider availability + time-slot picker (Phase 3) |
| UX-06 | No service search, no synonyms ("llave de agua", "no tengo internet") — search only finds providers by geo | High | Yes (step 2) | `routes/search.py`, frontend | Keyword+synonym search over the new catalog (Phase 2) |
| UX-07 | Client home is a stats table, not a marketplace home (no category grid, popular services, search bar, location) | High | Yes (step 2) | `renderClientDash` :1889 | Rebuild home per spec (Phase 2) |
| UX-08 | Provider locked to ONE profession, can't select individual services, no min price, no emergency opt-in, no pause | High | Yes (provider steps 2–4) | `mechanic_profiles`, profile UI | `provider_services` join table + config UI (Phase 3) |
| UX-09 | No payments — payment UX in spec can't be built truthfully without a processor (prior owner decision: fee-free launch) | High | Step 9 impossible as specced | — | Owner decision required (§9). Recommend: v1 = "pago directo al profesional" clearly labeled, defer processor |
| UX-10 | Job states missing: draft, waiting-for-offers, offer-received, provider-arrived, waiting-customer-confirmation | Medium | No (flow works, coarser) | `models.py` job/request enums, tracker UI | Extend request-level states with offer stages (Phase 3); `en_route`→`arrived` needs enum migration |
| UX-11 | Reviews are single-dimension (no quality/punctuality/communication/value, no photos) | Medium | No | `reviews` table, review modal | Add subscores as nullable columns (Phase 4) |
| UX-12 | No skeleton loading states; data pages flash empty then fill | Medium | No | frontend | Skeleton components in design pass (Phase 4) |
| UX-13 | Tables used for mobile lists (requests, users) — poor small-screen ergonomics despite `table-wrap` scroll | Medium | No | frontend list renderers | Card-based lists on mobile (Phase 4) |
| UX-14 | ~4,400-line single HTML file — every phase of this spec compounds the maintainability risk | Medium | No | `frontend/index.html` | Owner decision §9: split into static JS/CSS modules (no build step needed) |
| UX-15 | No drafts — abandoning the request modal loses everything | Medium | No | request form | localStorage draft save (Phase 3) |
| UX-16 | No analytics of any kind | Medium | No | — | Self-hosted events endpoint + `docs/ux-analytics-events.md` (Phase 5) |
| UX-17 | Design tokens exist (CSS vars, cards, badges, buttons, toasts, modals, bottom tabs) but are **undocumented** and inconsistently applied (inline styles sprinkled through renderers) | Medium | No | frontend CSS | Write `docs/design-system.md`, consolidate (Phase 4) |
| UX-18 | Localization lives inline in JS (`_translations`) — workable, but 300+ services would bloat it; service names/descriptions must NOT live there | Medium | No | frontend | Catalog strings come from the backend catalog (single source of truth); `_t()` stays for UI chrome |
| UX-19 | No provider verification tiers — email-only; spec requires gating high-risk services (electrical, construction, security) behind stronger verification | High | Provider step 1 for high-risk | `users`, provider onboarding | Owner decision §9 — needs a real verification *process*, not just a schema |
| UX-20 | Provider "earnings" impossible (no payments) and no completed-jobs money view at all | Medium | Provider step 9 | — | Depends on UX-09 decision |
| UX-21 | Accessibility gaps: icon-only buttons without aria-labels, color-only status distinction in badges, no focus management in modals | Medium | No | frontend | Accessibility pass (Phase 4) |
| UX-22 | Emergency flow: "immediate" urgency exists but no emergency service subset, no safety guidance | Low | No | catalog | Booking-type field per service covers this (Phase 2) |

**What already matches the spec and must be preserved** (do not rebuild): job-scoped
chat with system-message groundwork, GPS tracking with jittered pre-acceptance
coordinates (privacy requirement already enforced server-side), reporting/blocking
with admin queue, account deletion, bilingual i18n mechanism, per-profession status
flows computed dynamically, dispatch engine (still correct for instant-booking),
bottom-tab navigation shells for both roles, rate limiting, token revocation.

---

## 4. Proposed catalog hierarchy

Structure (matches spec):

```
Category (16)            ← browse grid on home; maps 1:1 to today's "profession" concept
└── Profession (16)      ← what a provider registers as (kept 1:1 with category for v1*)
    └── Service (~330)   ← what a customer actually books ("Destape de cañerías")
        └── Options      ← per-service question/option config (drives dynamic forms)
```

\* v1 keeps Category ≡ Profession (the 12 shipped + 4 new). Splitting professions
finer than categories (e.g. "barbero" vs "estilista" inside Belleza) is a data
change later, not a schema change — the schema below supports it from day one.

### Categories

Existing 12 (live in prod as of migration `0006`): `home_cleaning`, `handyman`,
`plumbing`, `electrical`, `painting`, `construction`, `gardening`,
`appliance_repair`, `tech_support`, `beauty`, `automotive`, `moving`.

New 4 (owner decision §9-D1): `home_security` (Seguridad del Hogar), `pets`
(Mascotas), `events` (Eventos), `business_support` (Apoyo Administrativo).

### Services

The complete service lists are as specified by the owner (27 cleaning, 27 plumbing,
19 electrical, 17 handyman, 19 painting, 20 construction, 20 gardening, 17
appliance, 28 technology, 18 beauty, 19 automotive, 17 moving, 11 security, 9 pets,
15 events, 14 admin ≈ **297 services**). Each service record carries:

`key`, `category_key`, `name_es` (Ecuadorian Spanish), `name_en`, `description_es`,
`description_en`, `icon`, `booking_type` (instant | estimate | emergency-capable),
`pricing_type` (fixed | starting_at | hourly | per_m2 | per_room | per_item |
inspection_fee | estimate_required), `duration_min`/`duration_max` (minutes),
`materials_possible` (bool), `photos_requested` (bool), `risk_level` (low | medium |
high), `verification_required` (none | enhanced), `keywords` (search synonyms,
es-EC), `common_questions` (JSON — drives the dynamic form), `sort_order`,
`is_active`.

Booking-type defaults by category (per spec), with per-service overrides in seed
data: instant → cleaning, gardening basics, car wash, haircuts, dog walking,
computer setup; estimate → plumbing/electrical repairs, construction, painting,
appliance repair, remodels, tech troubleshooting; emergency-capable → serious leak,
electrical outage, lockout (→ handyman/lock services), roadside assistance,
emergency cleanup.

Compliance flags carried in seed data (per spec): high-risk electrical/construction/
security marked `verification_required: enhanced`; beauty limited to non-invasive;
pets exclude veterinary; automotive excludes high-risk repairs; business support
excludes regulated professional services. Enforcement = provider cannot enable a
`verification_required` service until their account has that verification level
(backend check, not just UI).

**Source of truth**: a `services` DB table seeded from a version-controlled data
file (`seed_services.py` or JSON), served via `GET /api/catalog` (cached,
ETag-friendly). Names/descriptions/keywords live in the catalog rows (es + en
columns) — NOT in the frontend `_translations` dict (UX-18).

---

## 5. Database & API changes required

### New tables (Phase 2 unless noted)
| Table | Purpose |
|---|---|
| `service_categories` | 16 categories: key, names es/en, icon, sort, active |
| `services` | ~297 rows, fields per §4 |
| `provider_services` | provider ⇄ service: enabled, price, pricing_type, min_price (Phase 3) |
| `provider_availability` | weekly hours + emergency opt-in + paused_until (Phase 3) |
| `offers` | Phase 3: request_id, provider_id, labor/materials/transport amounts, message, included/excluded work, expires_at, status (pending/accepted/rejected/expired/withdrawn) |
| `request_photos` | Phase 3: request_id, file path/URL, order (plus media storage infra) |
| `analytics_events` | Phase 5: event key, anonymous session id, minimal props |

### Modified tables
- `service_requests`: add `service_id` (nullable FK — null means legacy/free-text request, so **existing rows keep working**), `booking_type`, `scheduled_window_start/end`, `draft` flag, structured `answers` JSON (dynamic form responses)
- `mechanic_profiles`: profession stays as the primary category; per-service config moves to `provider_services`
- `reviews`: add nullable `quality`, `punctuality`, `communication`, `value` subscores (Phase 4)
- `users`: add `verification_level` (Phase 3, pending §9-D5)
- `jobs.status` enum: add `arrived` (one enum migration, Phase 3)

### New/changed API endpoints
- `GET /api/catalog` (categories + services, public, cached), `GET /api/catalog/search?q=` (name+keyword+synonym match)
- `POST /api/client/requests` accepts `service_id`, `answers`, `photos`, schedule window; new draft endpoints
- Offers: `POST /api/provider/requests/{id}/offers`, `GET /api/client/requests/{id}/offers`, `POST /api/client/offers/{id}/accept` (accept → creates Job, closes siblings)
- Provider config: `GET/PUT /api/provider/services`, `GET/PUT /api/provider/availability`
- `POST /api/media/upload` (auth, size/type-limited, image-only, re-encoded server-side)
- `POST /api/analytics/events` (fire-and-forget, allowlisted event keys)

### Dispatch engine changes (Phase 3)
Keep `dispatch.py` exactly as-is for `booking_type=instant` and emergency.
For `estimate` services: skip auto-assign; notify all eligible providers
("new opportunity"); collect offers until customer accepts one or request expires.
This is additive — the current model remains the fallback and nothing breaks.

---

## 6. UI component inventory

**Reusable as-is**: CSS token set (`--brand`, grays, radius, shadows), `showModal`/
`closeModal`, `showToast`, `alert_el`, `badge`/`profBadge`, `emptyState`,
`pageHeader`, bottom tabs + sidebar shells, code-input boxes, status tracker,
chat pane, Leaflet map integration, profession dropdown with search.

**Missing (build once, in the design-system pass)**: skeleton loaders, bottom
sheet (mobile-first alternative to centered modals), card-list item (replaces
tables on mobile), stepper/wizard (multi-step request form), photo picker +
thumbnail grid, date/time-slot picker, comparison list (offers), price-breakdown
block, chip-group selector (dynamic form options), progress timeline (extends
existing tracker), confirmation dialog (standardize the current `confirm()` calls).

---

## 7. Localization approach

Keep the existing `_t()`/`_translations` mechanism for UI chrome (it works and is
already bilingual). Catalog strings (names, descriptions, questions, keywords)
come from the catalog API in both languages — the frontend picks `_lang`. Rule
going forward: **no service data hard-coded in the frontend** (spec rule 4/5).
Currency already USD; addresses/phone formats already free-text Ecuador-friendly;
date formatting uses `toLocaleDateString` (adequate).

---

## 8. Phased implementation plan

| Phase | Scope | Real deliverables |
|---|---|---|
| **2 — Catalog + browse + search** | `service_categories` + `services` tables, migration 0007, seed file (~297 services with full metadata), `GET /api/catalog` + search w/ synonyms, new customer home (category grid, search bar, popular services, current bookings), category → service → detail screens. `service_id` added to requests (nullable). Nothing existing breaks: current generic form keeps working for requests without `service_id`. | `docs/service-catalog.md`, seed data, migration, new browse screens |
| **3 — Booking flows** | Dynamic request forms from `common_questions`, photo upload (pending §9-D3), schedule picker + provider availability, provider service selection (`provider_services`), offers model + comparison UI for estimate services, request-level states (draft → submitted → offers → scheduled…), `arrived` status, drafts. | `docs/customer-booking-flow.md`, `docs/provider-workflow.md`, `docs/job-status-model.md` |
| **4 — Design system + quality** | Documented tokens/components, skeletons, card lists replacing tables, bottom sheets, accessibility pass (labels, focus, contrast, non-color status), review subscores, confirmation dialogs. | `docs/design-system.md` |
| **5 — Analytics + testing** | Event pipeline + allowlist, automated tests for the critical workflows, edge-case tests (offline, permission-denied, duplicates, slow API), acceptance run. | `docs/ux-analytics-events.md`, `docs/mobile-ux-test-plan.md`, test suite |

Each phase ends with: tests run, mobile layouts verified in-browser at 375px,
a commit, and a changed-files + open-issues report (per spec).

---

## 9. Owner decisions required before Phase 2

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Adopt all 16 categories (adds Security, Pets, Events, Business Support) or stay at the 12 just shipped? | Adopt 16 — catalog is data-driven, marginal cost is seed data only |
| **D2** | Matching model: keep auto-dispatch for everything, or hybrid (instant-book keeps dispatch; estimate services get offers/comparison)? | Hybrid — it's what the spec describes and it's additive, not a rewrite |
| **D3** | Photo storage: local Docker volume (simple, single-server) vs S3-compatible object storage (scales, offsite)? | Local volume for v1 with an interface that can swap to S3 later |
| **D4** | Payments: keep "pago directo al profesional" (no processor, price transparency UI only) for v1, or integrate a processor now (which one operates in Ecuador — e.g. PayPhone, Kushki, DataFast)? | Keep direct payment v1; build the price-breakdown UI honestly labeled; processor is its own project |
| **D5** | Provider verification for high-risk services: what does "enhanced verification" actually mean operationally (cédula photo + admin review? references?) and who reviews it? | Cédula + selfie upload reviewed in the existing admin panel; gate high-risk services on approval |
| **D6** | Frontend: split `index.html` into static modules (still no build step) before Phase 3 grows it further? | Yes — split CSS + ~6 JS modules; mechanical change, do it at the start of Phase 3 |
| **D7** | Analytics: self-hosted events table (recommended, zero third parties) vs external tool? | Self-hosted table + simple admin chart |

---

## 10. What this audit deliberately does not do

Per the spec's own rules: no code was changed, no screens rebuilt, no schema
migrated. The 12-category catalog shipped earlier today (`7b5350f`) is the
foundation Phase 2 builds on, not something to redo.
