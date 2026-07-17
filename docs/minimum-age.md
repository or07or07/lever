# Lever — Minimum-age policy (18+)

Nobody under 18 may create a Lever customer or professional account. The rule is
enforced **server-side** and is not bypassable from a modified APK, a direct API
call, a device-clock change, or a client-sent flag.

**Policy version:** `2026-07-17.v1` · **Minimum age:** 18 · **Market timezone:**
`America/Guayaquil`

---

## 1. Existing age-data audit

Before this change the system stored **no** date of birth anywhere — no field on
`users`, no age check in `routes/auth.register`, nothing in either APK. §39 was
entirely unimplemented. Registration required only email, password, role and
terms acceptance.

## 2. Design

Single authoritative module: [`age.py`](../age.py).

| Function | Purpose |
|---|---|
| `market_today()` | Backend business date in `America/Guayaquil` (zoneinfo, with a fixed **UTC-5** fallback — Ecuador has no DST, so the fallback is exactly equivalent). Never the device clock. |
| `birthday_on(dob, years)` | Calendar date the person reaches `years`. |
| `is_valid_dob(dob)` | Rejects empty / future / absurdly old (>120y). |
| `is_old_enough(dob, 18)` | `today >= birthday_on(dob, 18)` — never `year - year`. |
| `assert_minimum_age(dob)` | Raises `403 MINIMUM_AGE_REQUIREMENT_NOT_MET` or `422 INVALID_DATE_OF_BIRTH`. |

**Leap-year business rule (documented):** a person born **29 February** reaches
their birthday on **1 March** in non-leap years (conservative — they are not
treated as 18 until 1 March). Leap target years keep 29 February.

## 3. Enforcement points

- **Schema** (`schemas.UserCreate`): `date_of_birth: date` is **required with no
  default** — omitting it fails validation (422) instead of defaulting to adult.
  (This mirrors the `accepted_terms` lesson: Pydantic v2 skips validators on
  defaults, so a default would have been bypassable.) An impossible calendar date
  such as `2000-02-31` never parses into a `date` → 422.
- **Route** (`routes/auth.register`): `assert_minimum_age(payload.date_of_birth)`
  runs **first — before the duplicate-email lookup and before any user, profile,
  role or device registration exists.** Ordering it first also means age
  validation can never reveal whether an account already exists.
- The DOB is persisted in the **same transaction** that proves eligibility, so it
  cannot be swapped between validation and account creation.

## 4. Database

Migration **`0012`** adds to `users` (all nullable — see §6):

| Column | Type | Notes |
|---|---|---|
| `date_of_birth` | `DATE` | A birthday is a calendar date, not a moment in time. |
| `age_verified_at` | `DATETIME` | When eligibility was proven. |
| `minimum_age_policy_version` | `VARCHAR(32)` | Policy is versioned, not scattered in the APKs. |

Age is **never** stored — it changes over time. Source of truth = DOB + policy +
authoritative evaluation date.

## 5. Privacy

DOB is personal data. It is **not** exposed in job requests, offers, provider
notifications, chat, public profiles, analytics, or provider-facing customer
details — only the owner's own registration flow. The underage error deliberately
**does not echo the submitted date** and is identical regardless of how far under
18 the applicant is. Registration is already rate-limited
(`rate_limiter.py` → `/api/auth/register`). Explanation shown to users:
*"Usamos tu fecha de nacimiento para confirmar que cumples con la edad mínima
requerida para usar Lever."*

## 6. Existing-account migration plan

The new columns are **nullable on purpose**. Accounts created before this policy
have no DOB on file and are **not** deleted or suspended by the migration.

Phased plan (not yet executed — needs a product/legal decision):
1. **Phase 1 (done):** enforce for all *new* registrations.
2. **Phase 2:** report how many existing accounts lack a DOB.
3. **Phase 3:** add an in-app verification prompt for those accounts.
4. **Phase 4:** require verification before sensitive marketplace actions
   (providers receiving new jobs), with a grace period + comms. Never interrupt
   an active job; preserve support/recovery access; admin review for exceptions.

## 7. Test evidence

Pure-function policy tests (run locally, all **PASS**):

```
PASS | turns 18 TODAY -> allowed        (dob 2008-07-17)
PASS | turned 18 YESTERDAY -> allowed   (dob 2008-07-16)
PASS | turns 18 TOMORROW -> rejected    (dob 2008-07-18)
PASS | 17y 364d -> rejected
PASS | older than 18 -> allowed
PASS | newborn -> rejected
PASS | 29-Feb-2008 @ 2026-02-28 -> rejected   (18th bday = 2026-03-01)
PASS | 29-Feb-2008 @ 2026-03-01 -> allowed
PASS | 29-Feb-2004 +16y -> 2020-02-29 (leap target keeps 29 Feb)
PASS | None / future / year-0001 -> invalid ; 1990 -> valid
market_today() (America/Guayaquil) = 2026-07-17
```

API/e2e tests: `tests/test_e2e.py::test_minimum_age` — boundary (today /
tomorrow / yesterday), underage customer **and** provider, missing DOB, future
DOB, `2000-02-31`, non-date text, year 0001, `isAdult=true` cannot replace or
override a DOB, and the error never echoes the DOB.

Frontend verified in-browser: `type=date` with `max` = today (no future dates),
label *"Fecha de nacimiento"*, `aria-describedby` help text; empty DOB blocked
client-side; underage → **"No puedes crear una cuenta / Debes tener al menos 18
años para registrarte en Lever."** and stays on the form (no account, no
navigation); adult → registers normally.

## 8. Known limitations

- **Social login (Google/Apple) is not implemented in Lever**, so the
  social-signup DOB step in §39 has nothing to attach to. If OAuth signup is
  added, it must collect the DOB and call `assert_minimum_age` **before** the
  account is created (`User.oauth_provider` exists but no OAuth signup route does).
- **Phone registration does not exist** (email only) — same note.
- Existing accounts' backfill (§6 phases 2–4) is planned, not executed.
- Self-declared DOB is not identity-verified; document-based age assurance would
  require the provider-verification vendor work (see `docs/provider-verification.md`).

## 9. Rollback

```bash
cd /opt/lever-new/deploy
# revert code, then:
docker compose -f docker-compose.prod.yml --env-file .env.prod exec app alembic downgrade 0011
```
`0012` only adds nullable columns, so downgrade is non-destructive to existing
rows. Reverting the code alone (leaving the columns) is also safe — the columns
are simply unused.

## 10. Deploy

```bash
cd /opt/lever-new && sudo git pull origin main
cd deploy && sudo docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build app
```
⚠️ **Breaking API change:** `POST /api/auth/register` now requires
`date_of_birth`. Any installed APK older than this build will fail registration
with 422 until updated — rebuild/ship both APKs alongside this deploy. Login and
all existing accounts are unaffected.
