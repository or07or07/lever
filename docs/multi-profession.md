# Lever — Multi-profession providers (exact-service matching)

A professional can now offer services **across multiple professions**, and job
matching is by **exact service** rather than broad profession.

---

## Existing-system audit (what was already there)

- **Canonical catalog, backend-owned:** `professions.py` (16 professions) +
  `services_catalog.py` (297 services, each with a stable `key` and its
  `profession`), served by `GET /api/catalog`. **Both APKs bundle the same
  frontend** and fetch this one catalog — there is no hard-coded catalog in
  either APK, and IDs are stable (§3/§4 already satisfied).
- **Client sends `service_key`;** the backend **derives** `profession_type` from
  the catalog (`ServiceRequestCreate.validate_service_key`) — it never trusts a
  client-sent profession/category relationship (§9 already satisfied).
- **`ProviderService(provider_user_id, service_key, is_active, price)`** with
  `UNIQUE(provider_user_id, service_key)` already gave multi-**service**
  selection and pause/resume.

## The actual limitation (now fixed)

Matching filtered **profession-first**, and service configuration was capped to
the provider's one registration profession, at four points:

| Location | Was | Now |
|---|---|---|
| `dispatch.find_eligible_providers` | `profession == request.profession_type` then narrow by service | **exact-service**: eligible if an *active* `ProviderService` matches the requested `service_key` (any profession); unconfigured providers fall back to profession |
| `provider.py GET /board` | profession filter first | same exact-service rule (configured → active service_keys across professions; unconfigured → profession) |
| `provider.py POST /board/{id}/accept` | rejected profession mismatch | allows accept when the exact service is active; mirrors matching so you can't accept what wasn't offered |
| `provider.py GET/PUT /services` | only own-profession services | **full active catalog** across professions (per-service enhanced-verification gate kept) |

**Eligibility rule** (identical in matching, board, accept):

```
if request has a service_key:
    eligible  =  provider has an ACTIVE ProviderService(service_key)     # cross-profession, exact
             OR  (provider configured NO services  AND  profession == request.profession_type)   # legacy
else:  # legacy request without a service
    eligible  =  profession == request.profession_type
```

Consequences: a plumber who selected only *faucet installation* never gets a
*water-heater* request; a paused service (`is_active=false`) yields no offers; a
provider who never touched service selection keeps receiving everything in their
profession (backward compatible).

## Database

- Reuses `provider_services` (no new table).
- Migration **`0013`**: add `INDEX(service_key, is_active)` so matching looks up
  providers by exact service efficiently (§13). The `UNIQUE(provider_user_id,
  service_key)` constraint already prevents duplicate provider-service records.

## Frontend (Provider "Mis servicios")

`renderMyServices` now renders the **full catalog grouped by profession** into
expandable `<details>` sections with an accent-insensitive **search**, a live
"N servicios seleccionados" count, and a per-group `active/total` badge. A
provider registered as *electrical* can search "fuga", expand *Plomería*, and
enable plumbing services. Verified in-browser (375px): 16 groups, 297 rows,
search filters correctly, no horizontal overflow, no console errors.

## Authorization / concurrency (already enforced, unchanged)

- `PUT /services` requires `require_provider`; per-service enhanced-verification
  gate blocks activating restricted services; a provider edits only their own
  rows.
- Accept is guarded by `Job.request_id` uniqueness + a `status == pending` check
  (first-accept-wins). The active-job snapshot (`Job` + its `request`) is
  independent of later profile edits, so pausing/removing a service never
  rewrites an active job (§8/§10).

## Tests

`tests/test_e2e.py::test_multi_profession_matching` (runs against a live server):
electrician **enables a plumbing service** → plumbing request appears on their
board and they can **accept** it; a second electrician who didn't enable it does
**not** see it; a **paused** service produces no board entry. The eligibility
predicate was also unit-verified locally across all §12 cases (cross-profession,
exact-service, paused, unconfigured-legacy, wrong-profession).

## NOT done (deliberately — out of honest scope)

- **Earnings / pricing (§14–17):** Lever has **no payments, pricing engine,
  platform fee, or payouts** (launched fee-free, GP-10). There is nothing to
  calculate, so provider-earnings notifications/offer screens were **not** built
  — doing so would fabricate financial figures, which the spec forbids. This
  needs a payments decision first.
- **Per-service verification status / coverage-area / availability / hourly-rate
  fields (§5):** `ProviderService` today carries `is_active` + optional `price`.
  Richer per-service qualification/coverage/availability columns are a follow-up.
- **Real-time refresh (§19–24):** the app already uses a WebSocket for chat +
  GPS and polling for notifications; a full unified event bus + reconnect/missed-
  event recovery is a large separate workstream, not part of this change.
- **`profession` column deprecation:** kept as the unconfigured-provider fallback
  and as the registration default; not removed (phased-deprecation, per §6).

## Deploy

```bash
cd /opt/lever-new && sudo git pull origin main
cd deploy && sudo docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build app
```
Runs migration `0013` (adds one index; non-destructive). No breaking API change —
existing single-profession providers keep working unchanged.
