# Lever — Customer Booking Flow (guest preview + deferred authentication)

Implemented 2026-07-13. The customer experiences nearly the whole request flow
without an account; authentication is required only to submit. Nothing reaches
the backend — and no professional can see anything — until the authenticated
user explicitly presses **Enviar solicitud**.

## Flow

```
Landing / native client app
→ #/services            Guest home: search («¿Qué servicio necesitas?»),
                         16-category grid, popular services, guest notice
→ #/services/<cat>       Service list for a category
→ #/service/<key>        Detail: description, pricing method, duration,
                         instant-vs-estimate note → «Solicitar este servicio»
→ #/request/new          Wizard (progress bar):
                           1. details   — description + service-specific
                                          questions (QUESTION_SETS)
                           2. schedule  — «Lo antes posible» / «Programar»
                                          + date + time window
                           3. location  — approximate only: city + sector
→ #/request/review       Summary with per-section Editar buttons and the
                         notice «Todavía no se enviará tu solicitud»
→ #/auth-gate            «Tu solicitud está lista» — Iniciar sesión / Crear
                         cuenta / Volver y editar (skipped if already
                         signed in)
→ (login / register → email verification)
→ #/finish-request       Draft restored. Exact address collected HERE, not
                         before. Optional budget. Explicit «Enviar solicitud»
→ POST /api/client/requests → existing tracker (#/request/<id>) = matching
  (auto-dispatch) + status timeline + chat
```

## Guest draft

`localStorage["lever_guest_draft"]`: serviceKey, description, answers,
urgency, date, timeWindow, city, sector, step, status
(`guest_draft`→`ready`), createdAt/updatedAt, expiresAt (**7 days**).
Survives navigation, refresh, and the whole auth flow (including email
verification). Cleared on successful submission; user-removable via
«Descartar borrador» (confirmed). Never sent to the server, never in URLs.

After any sign-in, `render()` forwards a client at `#/` with a ready draft to
`#/finish-request` — covers login, registration, and post-verification paths
with one hook.

## Guards

- Backend: `service_key` validated against the catalog (422 if unknown);
  profession derived server-side; auth + client role + rate limiting on
  submission (all pre-existing).
- Double-submit: `_submittingRequest` flag + disabled button while in flight.
- Failed submission keeps the draft and shows a recovery message.
- Provider/admin accounts hitting guest-flow routes are redirected home.
- Native client app opens into guest discovery; the provider app keeps
  login-first.

## Known limitations (deliberate, tracked)

- **No photos** — no media infrastructure exists yet (Phase 3, decision D3).
- **No offers/comparison yet** — submission goes to the existing
  auto-dispatch; the hybrid estimates model is Phase 3 (decision D2).
- **Full address visible to providers on the board** (pre-existing
  behavior; coordinates are already hidden per GP-17). Gating the exact
  address until acceptance ships with the offers flow in Phase 3.
- **Analytics events** deferred to Phase 5 (decision D7).
- Time window is stored in `answers._time_window` (no dedicated column yet).

## Verified end-to-end (live browser, 375px)

Guest browse → synonym search → plumbing wizard with service-specific
questions → review → auth gate → registration (draft survived) → email
verification → draft restored at final confirmation → explicit submit →
request #1 created with `service_key` + structured answers → visible on a
plumbing provider's board. Invalid `service_key` rejected (422); legacy
no-catalog request still works (201).
