# Lever — Provider Service Selection (Phase 3)

Implemented 2026-07-14. A provider is still tied to exactly one profession/
category (v1 scope, unchanged — see `service-catalog-ux-audit.md`). Within
that category they now choose specific catalog services instead of
implicitly offering everything.

## Model

`ProviderService` (migration `0008`): `provider_user_id`, `service_key`,
`is_active` (pause without losing price/history), `price` (optional,
meaning depends on the service's `pricing_type`). Unique per
(provider, service_key).

`User.verification_level` (`none` default, `enhanced`): gates any service
with `verification_required: enhanced` in `services_catalog.py` (electrical,
construction, home_security core work). No self-serve document upload yet
— an admin sets this from **Usuarios** after reviewing ID out-of-band
(email/WhatsApp). Tracked as decision D5, still partially open.

## Backward compatibility (the important part)

**A provider who never opens "Mis Servicios" is unaffected.** Zero rows in
`provider_services` = "offers everything in my profession", the exact
pre-existing behavior. The moment a provider saves *any* selection, they
switch to "only what I've enabled and haven't paused." This convention
(`_active_service_keys()` returning `None` vs. a set) is applied identically
in three places so the feature is real everywhere, not just cosmetic on the
profile page:

- `GET /api/provider/board` — board listing
- `POST /api/provider/board/{id}/accept` — defense-in-depth re-check
- `dispatch.py find_eligible_providers()` — the auto-dispatch engine

## API

- `GET /api/provider/services` — every service in the provider's category,
  merged with their selection state and a `selectable` flag (false = needs
  verification they don't have).
- `PUT /api/provider/services` — replace the full selection in one call
  (`{services: [{service_key, price}]}`). Rejects unknown keys (400) and
  enhanced-tier keys without verification (403), naming which ones failed.
  Anything previously selected but omitted is paused, not deleted.
- `PATCH /api/provider/services/{key}` — pause/resume one service without
  resubmitting the whole list.
- Admin verification: `PATCH /api/admin/users/{id}` with
  `{"verification_level": "enhanced"}` — no new endpoint; it's a field on
  the existing `UserAdminUpdate` schema the endpoint already applies
  generically.

## UI

- **Mis Servicios** (`#/my-services`, linked from the provider Profile
  screen): checkbox list of every service in the provider's category, price
  input where the pricing type takes one, a 🔒 note + disabled checkbox on
  services that need verification the provider doesn't have, one "Guardar
  cambios" that PUTs the full set.
- **Admin → Usuarios**: a Verification column + Verificar/Quitar
  verificación action per provider row (confirmation dialog only on
  granting, not revoking).

## Known limitations (deliberate, tracked)

- Emergency-availability opt-in, a dedicated min-price field, and
  working-hours/availability from the original UX-08 finding are **not**
  part of this pass — scoped out to keep this change reviewable; still
  open in the audit.
- Verification is manual/offline (no upload UI) — see D5 above.
- A provider still can't span multiple categories (v1 constraint, tracked
  separately, not part of this task).

## Verified end-to-end (live, API + browser)

Electrician with 19 catalog services, 18 flagged `enhanced`: listing shows
correct locked/unlocked split; `PUT` with a locked key → 403 naming it;
`PUT` with the one unlocked key + price → succeeds and persists. Admin
grants `enhanced` → previously-locked key now accepted by `PUT`. Selection
set to one service → client requests for a *different* service in the same
category no longer appear on that provider's board, but still appear for
providers who haven't configured anything; direct-accept on the
filtered-out request 400s. Admin Usuarios page renders the verification
badge/action and both toggle directions confirmed live.
