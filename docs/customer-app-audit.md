# Lever — Customer application audit

Audit of the authenticated **customer** experience against the customer-shell +
ratings/Account specs. Covers the four-tab shell, Home, Services, Activity,
Account, two-way ratings, safe areas, accessibility, and authorization.

**Audit date:** 2026-07-17
**Scope:** `frontend/index.html` (SPA), FastAPI backend (`routes/`, `models.py`,
`schemas.py`, migrations), `tests/test_e2e.py`.

---

## 1. Acceptance criteria — status

| # | Criterion | Status | Where |
|---|---|---|---|
| 1 | Bottom nav has exactly 4 tabs | ✅ | `BOTTOM_TABS.client` |
| 2 | Order Home · Services · Activity · Account | ✅ | `BOTTOM_TABS.client` |
| 3 | Spanish labels Inicio/Servicios/Actividad/Cuenta | ✅ | i18n `tab.*` |
| 4 | Bottom nav floats above background | ✅ | `.bottom-tabs` (rounded, margins, shadow, safe-area) |
| 5 | Floating Home header only on Home | ✅ | `.route-home`, `renderClientHome` |
| 6 | Home header = only "Lever" + search | ✅ | `renderClientHome` |
| 7 | No extra Home header actions | ✅ | — |
| 8 | Complete word "Lever" (no icon substitution) | ✅ | `.home-wordmark` |
| 9 | Home search finds services fast | ✅ | debounced → `/api/catalog/search` |
| 10 | Services lists Guayaquil-active catalog | ✅ | `renderGuestHome` + `/api/catalog` |
| 11 | Activity = current + historical requests | ✅ | `renderClientRequests` (filtered cards) |
| 12 | Completed activity shows the professional | ✅ | `list_requests` professional summary → cards |
| 13 | Completed activity shows customer's rating status | ✅ | `has_review` → "Calificar" / "Reseña enviada" |
| 14 | Customers can rate completed services | ✅ | `POST /api/client/jobs/{id}/review` |
| 15 | Duplicate ratings prevented | ✅ | unique `reviews.job_id` + 409 |
| 16 | Account has comprehensive, grouped features | ✅ (see §6) | `renderClientProfile` + sub-pages |
| 17 | Backend endpoints support sections | ✅ | catalog/market/requests/reputation/rate-customer |
| 18 | Backend authorization protects data | ✅ | `require_client`/`require_provider` + ownership |
| 19 | Guayaquil-only enforced server-side | ✅ | `market.validate_service_location` |
| 20 | Request drafts survive navigation | ✅ | localStorage guest draft |
| 21 | Nested routes keep correct tab | ✅ | `activeTabHash()` |
| 22 | Content not covered by nav | ✅ | `--content-bottom-pad` token |
| 23 | Mobile safe areas respected | ✅ | `env(safe-area-inset-*)` on nav/header/topbar |
| 24 | Works mobile/tablet/desktop | ✅ | verified 320–1280px |
| 25 | Accessibility | ✅ (see §4) | `aria-current`, labels, text ratings |
| 26 | Existing auth still works | ✅ | unchanged + case-insensitive email |
| 27 | Existing request flow intact | ✅ | verified |
| 28 | Automated tests pass | ⚠️ added, run on live server | `tests/test_e2e.py` |
| 29 | No unrelated functionality broken | ✅ | verified per change |
| 30 | Feels unified + purpose-built | ✅ | one design system, Lever-green accents |

### Two-way ratings / Account-spec criteria
| Item | Status |
|---|---|
| Professionals can rate customers (assigned + completed only) | ✅ `POST /api/provider/jobs/{id}/rate-customer` |
| Duplicate customer rating prevented | ✅ unique `customer_ratings.job_id` + 409 |
| Customer cannot edit received rating | ✅ no customer write path |
| Customer sees own aggregate rating + count + "from professionals" | ✅ Account identity + `/api/client/reputation` |
| No-rating empty state (never fake 5★/0) | ✅ `ratingBlock` / `renderReputation` |
| Reputation detail (distribution + guidance) | ✅ `renderReputation` (`#/account/reputation`) |
| Services/Activity/Account top bars respect safe area | ✅ safe-area padding |
| Home header unchanged | ✅ |

---

## 2. Route map

| Tab | Route(s) | Screen | Redirects |
|---|---|---|---|
| Inicio | `#/`, `#/home` | `renderClientHome` | `#/dashboard`→`#/` |
| Servicios | `#/services`, `#/services/:cat`, `#/service/:key` | catalog (guest flow, nav retained) | `#/categories`→`#/services` |
| Actividad | `#/requests` (alias `#/activity`), `#/request/:id` | `renderClientRequests` / `renderRequestDetail` | `#/history`→`#/requests` |
| Cuenta | `#/profile` (alias `#/account`), `#/account/personal`, `#/account/reputation` | `renderClientProfile` / `renderProfileEdit` / `renderReputation` | — |

Nested routes keep the owning tab active via `activeTabHash()`. Nav is hidden
only during the full-screen request-submission workflow (`ensureGuestBottomNav`).

---

## 3. Backend / DB changes

- **`models.py`**: `CustomerRating` table (professional→customer, unique `job_id`,
  optional category ratings, moderation status); `ClientProfile.avg_rating` +
  `total_ratings`.
- **Migration `0011`**: creates `customer_ratings` + adds the two `client_profiles`
  columns (**must run** — `create_all` won't add columns).
- **`routes/provider.py`**: `POST /jobs/{id}/rate-customer` — enforces assigned
  professional + completed job + one-per-job; recomputes the aggregate; notifies
  the customer (no written feedback in the notification).
- **`routes/client.py`**: `GET /reputation` (own data only, anonymous feedback);
  `list_requests` now attaches the assigned professional's summary + `has_review`
  (batched, no N+1).
- **`routes/auth.py`**: email normalized to lowercase + case-insensitive
  (`func.lower`) on register / login / reset.
- **`schemas.py`**: `CustomerRatingCreate`; professional-summary fields on
  `ServiceRequestOut`.

Structured error codes: `JOB_NOT_ELIGIBLE_FOR_CUSTOMER_RATING`,
`PROFESSIONAL_NOT_ASSIGNED_TO_JOB`, `CUSTOMER_RATING_ALREADY_EXISTS`.

---

## 4. Accessibility

- Bottom nav is a `<nav aria-label>` of buttons with `aria-current="page"`, a
  non-color active indicator (top bar + icon scale + weight), and `focus-visible`.
- Customer name is an `<h1>`; rating exposed as text via `aria-label`
  ("Calificación como cliente: 4.9 de 5, basada en N…") — not stars alone.
- Nav badge has an accessible label ("Actividad, N acciones pendientes").
- Home search has an accessible label; 48px input; visible focus ring.
- Touch targets ≥ 44px; password fields have an accessible show/hide toggle.

---

## 5. Design tokens (no duplicated magic numbers)

`--bottom-nav-height`, `--bottom-nav-gap`, `--content-bottom-pad`
(`= nav-height + 32px + safe-area`), `--nav-green` / `--nav-green-soft`.

---

## 6. Account groups

Identity header (avatar, name `<h1>`, accessible rating, verified chip, edit) then
groups: **Tu cuenta** (personal info, vehicles), **Reputación y actividad**
(Mi reputación, Mi actividad), **Seguridad y privacidad** (settings), **Ayuda e
información** (help/terms/privacy), **Administración de cuenta** (sign out,
delete). Reputation + personal-info open as focused sub-pages.

---

## 7. Known limitations / not implemented (deliberately, per "don't fake it")

- **Account sub-features that don't exist yet** are not shown as functional:
  saved-addresses CRUD, payment methods/billing, passkeys/2FA-for-customers,
  notification-preference toggles, WhatsApp/SMS channels, data-export UI. These
  should be built as real features or clearly marked "próximamente" before being
  surfaced. The current Account exposes only what exists (profile, vehicles,
  security settings, reputation, help, legal, logout, delete).
- **Desktop** still uses the existing left sidebar (all four destinations
  reachable); a floating side-nav conversion is optional future work.
- **Analytics events** (§40) not wired — no analytics system exists in the app to
  reuse; adding one is a separate decision.
- **Automated tests** are added but run only against a live server + DB (the whole
  suite works this way); they are not executed in CI yet.
- **Professional photo on activity cards** shows name + rating + verification, not
  an avatar image (no customer-visible avatar pipeline).

---

## 8. Manual testing (on device / PWA)

1. **Nav**: all four tabs present, correct order + Spanish labels; active tab has
   the green top-bar indicator; badge on Actividad when a completed job is
   unreviewed. 320/360/375/390/414/768px — no overflow, no clipped labels.
2. **Home**: floating "Lever" + search only; type "plomero"/"limpieza" → live
   suggestions → open a service; "Ver todos los resultados" → Servicios.
3. **Services**: catalog with bottom nav retained on category/detail pages.
4. **Activity**: filter chips (Todos/Activos/Completados/Cancelados) with counts;
   completed cards show the professional + "Calificar al profesional" vs "Reseña
   enviada"; empty state when no requests.
5. **Account**: name as a large heading; rating block (or no-rating state);
   Mi reputación shows distribution + guidance; safe-area top spacing correct.
6. **Ratings loop** (needs 2 accounts): complete a job → customer rates the pro;
   the pro rates the customer → customer's Cuenta rating updates.
7. **Email**: register `You@X.com`, log in as `you@x.com` (and vice-versa).

## 9. Deploy note

Frontend ships via the test APK on each push. **The ratings features require the
backend deploy + migration `0011`**:
```bash
cd /opt/lever-new && sudo git pull origin main
cd deploy && sudo docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build app
```
