# Lever — Provider Identity Verification (facial recognition)

**Status:** Assessment + design. Not implemented. Owner reviewing.
**Decided (2026-07-15):** build **both** verification layers; **buy** a third-party
identity-verification API rather than build facial recognition in-house.
**Related:** resolves the trust gap behind GP-16 in
[google-play-readiness.md](google-play-readiness.md) (the app must not claim
"verified professionals" it does not actually verify).

---

## 1. Goal

Lever is an honesty-and-security-first marketplace connecting strangers for
in-person services. The specific threat this feature addresses:

> A professional passes onboarding, then **sends someone else** to physically do
> the job.

Solving that requires proving identity **twice**: once to bind a real person to
the account, and again **at the job** to prove the same person showed up. A
one-time onboarding check alone does *not* stop substitution — it just makes the
account trustworthy at signup.

### Non-goals
- This is **not** a background/criminal check (a separate product; some LATAM
  vendors offer it as an add-on).
- This does **not** guarantee the verified person performs the *entire* job — see
  [§11 Limitations](#11-honest-limitations). It raises the bar; it is not a
  perfect guarantee.

---

## 2. Two-layer model

| Layer | When | Check | Purpose |
|---|---|---|---|
| **L1 — Enrollment / KYC** | Once, during provider onboarding | Government ID (Ecuadorian *cédula*) authenticity + OCR, **live selfie**, **1:1 face match** selfie↔ID | Bind a real, identifiable person to the account. Enables a truthful "Verificado" badge. |
| **L2 — Job-time check-in** | At the start of each job (and optionally random spot-checks) | **Liveness** + **1:1 face match** against the *enrolled* face template | Prove the same person is on-site. This is the anti-substitution control. |

L2 is deliberately cheap: it is liveness + 1:1 match against the already-enrolled
identity, **not** a full re-KYC (no document re-scan). See [§13 Cost](#13-cost-model).

---

## 3. Build vs. buy — decision: **BUY**

Do **not** build facial recognition / liveness in-house. Rationale:

- **Anti-spoofing is adversarial.** Defeating printed photos, screen replays, 3D
  masks, and deepfakes is a moving target that specialist vendors invest heavily
  in and get **independently certified** for (ISO/IEC 30107-3 Presentation Attack
  Detection, iBeta Level 1/2, NIST). A hand-rolled model will lose to these
  attacks and you won't know until you're defrauded.
- **Liability.** Raw biometric templates are the highest-liability data class in
  the app. A vendor that **holds the biometric** (and processes-and-discards, or
  stores under its own certified controls) keeps that data — and much of the
  breach liability — off Lever's servers.
- **Local ID support.** Ecuadorian *cédula* authentication against the Registro
  Civil is a solved capability for LATAM vendors and painful to replicate.
- **Cost/time.** Vendor integration is days; a credible in-house system is
  months plus permanent maintenance.

---

## 4. Vendor shortlist

Selection criteria (score every candidate on these):

1. **Ecuadorian *cédula*** document verification (ideally validated against
   Registro Civil), Spanish UX.
2. **Liveness** independently certified to **ISO/IEC 30107-3 (Level 2)** /
   iBeta L2.
3. **1:1 face match** (selfie↔ID for L1, selfie↔enrolled for L2) exposed as an API.
4. **Data-retention model** — can *they* hold the biometric so Lever doesn't?
   What is their retention/deletion API and default TTL?
5. **Mobile SDK / web capture** that works inside a Capacitor WebView (camera
   access, no heavy native plugin required), or a hosted redirect flow.
6. **Pricing** per verification (L1) and per liveness+match (L2) at expected volume.
7. **Data residency / sub-processor** terms compatible with Ecuador LOPD.

Candidates (confirm all of the above **directly with each** — capabilities and
coverage change):

| Vendor | Why on the list | Watch-outs |
|---|---|---|
| **Didit** | Strongest direct Ecuador story: verifies *cédula* against Registro Civil, active liveness + 1:1 face match. | Confirm passive vs. active liveness cert level; SDK-in-WebView support. |
| **MetaMap** | LATAM-focused; uses Incode's **iBeta-certified passive liveness** (ISO 30107 / NIST). | Confirm current Ecuador *cédula* coverage + retention API. |
| **Verifik** | LATAM incl. Ecuador; passive liveness + face compare. | Confirm certification level + pricing at low volume. |
| **AWS Rekognition Face Liveness** | Cheapest (~$0.015/liveness check) + CompareFaces for 1:1; ISO 30107-3 PAD-tested. | **Primitive, not a solution:** no *cédula* document check, and **you** store/handle the biometric → pulls liability back onto Lever. Best only for **L2** if a full vendor handles **L1**. |
| **iProov** / **Entrust IDV (ex-Onfido)** / **Veriff** | Global leaders; strongest liveness (iProov is deepfake-resilient, ISO 30107-3 L1+L2 + FIDO + NIST 800-63-4). | Verify Ecuador *cédula* coverage + LATAM pricing; may be enterprise-priced. |

**Recommended path:** shortlist **Didit** and **MetaMap** for a bundled L1+L2
flow; get quotes and a retention-model answer from both. Consider **AWS Face
Liveness** for L2 only if it's materially cheaper *and* the L1 vendor can expose
the enrolled template for external matching (many can't — in which case do L2
with the same vendor as L1).

---

## 5. Architecture

Keep Lever **provider-agnostic**: all vendor calls go through one internal
adapter interface, so switching vendors (or using different vendors for L1 vs L2)
never touches business logic.

```
┌────────────────────┐        ┌──────────────────────────┐
│ Provider (WebView) │        │  Verification vendor      │
│  camera capture    │◄──SDK──►│  (Didit / MetaMap / …)    │
└─────────┬──────────┘        │  holds biometric template │
          │ session token      └────────────┬─────────────┘
          │ (never raw image to Lever)       │ webhook: result
          ▼                                   ▼
┌───────────────────────────────────────────────────────────┐
│  Lever FastAPI  —  verification adapter (single interface) │
│  stores: status + opaque vendor reference ONLY             │
└───────────────────────────────────────────────────────────┘
```

### L1 enrollment sequence
1. Provider opens **Perfil → Verificación**. Lever calls the adapter →
   `create_enrollment_session(user_id)` → vendor session token.
2. WebView runs the vendor's capture flow (cédula photos + live selfie).
   **Raw images go provider→vendor, never through Lever.**
3. Vendor verifies document + liveness + selfie↔ID match, then calls Lever's
   **webhook** with a signed result (pass/fail + opaque `verification_id`).
4. Lever records status; on pass, sets the provider "Verificado" and, if the
   vendor supports it, stores an opaque **enrolled-template reference** for L2.

### L2 job-time check-in sequence
1. Provider accepts a request → a `Job` is created (status `accepted`).
2. Before the provider can move the job to `en_route` / start work, the app
   requires a **check-in selfie**. Adapter →
   `create_checkin_session(user_id, job_id)`.
3. Vendor runs liveness + **1:1 match against the enrolled template**, webhooks
   the result.
4. **Pass →** the job may proceed (`accepted → en_route`), `Job.started_at` set,
   check-in recorded. **Fail →** the job is blocked from starting and routed to
   the failure path in [§10](#10-failure--edge-handling).

The existing GPS check-in (job has coordinates; tracking starts at `en_route`)
pairs naturally with L2: **liveness + location** together are much stronger than
either alone.

---

## 6. Data model changes

Extends the **existing** `User.verification_level` (today `"none"`/`"enhanced"`,
set manually by an admin via `PATCH /api/admin/users/{id}`). New Alembic
migration (next in chain, **0011**). **Store status and references only — never
raw selfies or face templates in Lever's DB.**

### New provider-verification fields (on `MechanicProfile` or a new 1:1 table)
```
identity_status         ENUM(unverified, pending, verified, failed, expired)  default 'unverified'
identity_provider       String(40)      # 'didit' | 'metamap' | ...  (which vendor)
identity_ref            String(255)      # opaque vendor verification id (NOT a biometric)
identity_template_ref   String(255)      # opaque enrolled-template handle for L2 (if vendor-held)
identity_verified_at    DateTime NULL
identity_expires_at     DateTime NULL     # re-verify cadence (e.g. annually)
```
Keep `User.verification_level` as the **coarse public signal** ("none" →
"verified") that the UI already reads; drive it from `identity_status` so
existing badge code keeps working.

### New table — per-job check-ins (`job_checkins`)
```
id            PK
job_id        FK jobs.id (ondelete CASCADE)
user_id       FK users.id            # the provider
result        ENUM(pending, passed, failed)
provider_ref  String(255)            # opaque vendor session/result id
created_at    DateTime
decided_at    DateTime NULL
```
The `Job` cannot leave `accepted` for a working status until a `passed` check-in
exists for it. (Enforce in `routes/provider.py` at the status-transition
endpoint, server-side — never trust a client "I passed" flag.)

### What is explicitly **NOT** stored
- No selfie images, no cédula images, no face vectors/templates on Lever infra.
- Only opaque vendor references + pass/fail + timestamps.

---

## 7. API surface (provider-agnostic)

All under auth, provider-role only. The adapter hides the vendor.

| Method / path | Purpose |
|---|---|
| `POST /api/provider/verification/enroll` | Start L1; returns a vendor session token/URL for the WebView. |
| `GET  /api/provider/verification/status` | Current `identity_status` + whether action is needed. |
| `POST /api/provider/jobs/{id}/checkin` | Start L2 for a job; returns a check-in session. |
| `POST /api/webhooks/verification/{vendor}` | **Vendor → Lever** signed result callback (verify signature; idempotent). |
| `PATCH /api/admin/users/{id}` (existing) | Manual override / manual-review outcome (keep as the fallback path). |

Webhook rules: verify the vendor signature, treat as idempotent (dedupe on
`identity_ref`/session id), and never accept a verification result from the
client — only from the signed webhook (or a server-side status poll).

---

## 8. Frontend touchpoints

- **Onboarding / Perfil:** a "Verificación de identidad" card that launches L1
  and reflects `identity_status` (pendiente / verificado / falló + retry).
- **"Verificado" badge:** show only when truly verified; render on the provider's
  profile, the job board card, and job detail. (This is the claim GP-16 said must
  not be shown falsely.)
- **Job start:** gate the "Iniciar / En camino" action behind the L2 check-in
  selfie; clear Spanish messaging on pass/fail and a retry.
- **Client-side confirmation:** on the client's job screen, show the provider's
  verified photo + a "¿La persona coincide con su foto? Reportar" prompt — a cheap
  human backstop to the automated check.
- All copy Spanish-first (es-EC), matching the app.

---

## 9. Compliance — treat as a launch gate, not an afterthought

Biometric data is **sensitive / special-category** under Ecuador's **LOPD** (Ley
Orgánica de Protección de Datos Personales) and GDPR-style regimes. This section
is a checklist, **not legal advice** — see the flag below.

- **Explicit, informed, purpose-limited consent** before any capture: a dedicated
  consent screen stating what is collected, by which processor, why, how long
  it's kept, and how to withdraw. Record consent (version + timestamp) the same
  way terms acceptance is already recorded (`terms_accepted_*` pattern).
- **Data minimization / retention:** prefer the vendor holding the biometric;
  define a retention + deletion policy and wire vendor-side deletion into the
  existing **account-deletion** flow (GP-07) so deleting a Lever account also
  purges the vendor record.
- **Google Play Data Safety:** declare biometric collection, its purpose, whether
  it's shared with a processor, and retention. Add an in-app camera-permission
  rationale. Update the **privacy policy** (`frontend/legal/privacy.html`) to name
  the verification processor as a sub-processor and describe the biometric
  handling.
- **Android permission:** `CAMERA` will be needed by the provider app for capture
  (currently only `INTERNET` + location are declared). Request it contextually at
  the verification/check-in screen, not at launch.
- **DPIA:** a data-protection impact assessment is advisable for biometric
  processing.

> ⚠️ **Legal review required before launch.** An Ecuador-licensed lawyer must
> review the consent flow, retention policy, and LOPD posture. Lever must not make
> unsupported compliance claims. Claude can draft accurate technical/consent
> scaffolding but will not make the legal determination.

---

## 10. Failure & edge handling

Automated biometrics produce false rejects; a rigid gate will lock legitimate
providers out of income. Required safeguards:

- **Manual-review fallback:** on repeated L1/L2 failure, route to an admin review
  queue (reuse the moderation/admin queue pattern from GP-08) where a human can
  approve after reviewing evidence out-of-band. `PATCH /api/admin/users/{id}`
  already exists as the manual lever.
- **Retry with guidance:** clear Spanish messaging (lighting, glare, hold steady)
  and a limited retry count before escalation.
- **Appeals path:** a support route for "I am me but keep failing."
- **Exclusion policy (owner decision):** what about providers without a smartphone
  camera of sufficient quality, or without a valid cédula? Decide before launch.
- **Check-in outage:** if the vendor is down, do **not** hard-block all jobs
  platform-wide — define a degraded mode (e.g., allow with a flag + retro
  check-in, or pause new starts) as an explicit, logged decision.

---

## 11. Honest limitations

State these plainly; do not oversell the feature internally or in marketing.

1. **Check-in ≠ whole-job guarantee.** L2 proves who took the selfie at check-in.
   A determined bad actor could pass check-in and then hand off. Mitigate with
   random re-checks during longer jobs, pairing with GPS/geofence, and the
   client-side "does this match their photo?" report path.
2. **False rejects are real** and disproportionately affect some users
   (lighting, camera quality, demographic bias in models). The manual-review
   fallback is mandatory, not optional.
3. **Cost scales with job volume** (L2 runs every job). Keep L2 to liveness+match,
   not re-KYC.
4. **Exclusion risk** for providers lacking a device/ID — a real fairness issue in
   the Ecuadorian market.
5. **Vendor dependency:** an outage or price change is now on Lever's critical
   path — hence the provider-agnostic adapter.

---

## 12. Rollout plan

1. **Vendor selection:** quotes + retention answers from Didit & MetaMap; pick one
   (or one for L1 + AWS for L2 if cheaper and technically compatible).
2. **Legal:** consent + retention + privacy-policy update reviewed by an
   Ecuador-licensed lawyer.
3. **L1 first:** enrollment flow, `identity_status`, badge, admin manual-review
   fallback. Ship and let providers get verified.
4. **L2 next:** job-start check-in gate + `job_checkins`, wired to the existing
   `accepted → en_route` transition and GPS.
5. **Play update:** Data Safety form, `CAMERA` permission + rationale, privacy
   policy, then release.

L1 and L2 are separable — L1 can ship and deliver the truthful "Verificado" badge
while L2 follows.

---

## 13. Cost model

Approximate, **confirm with vendors**:
- **L1 full KYC** (document + liveness + match): ~$0.50–$2.00 per verification,
  one-time per provider (+ periodic re-verification if you set `identity_expires_at`).
- **L2 liveness + 1:1 match:** cents per check (e.g. AWS Face Liveness ~$0.015 +
  a match call). Runs **per job**, so model it against expected job volume, and
  consider spot-checking (every Nth job / risk-based) instead of literally every
  job if volume makes per-job cost material.

---

## 14. Open decisions (owner)

1. **Vendor:** Didit vs. MetaMap (vs. split L1/L2). Pending quotes.
2. **Check-in frequency:** every job, or risk-based/random spot-checks?
3. **Re-verification cadence:** does L1 expire (e.g. annually)? Sets
   `identity_expires_at`.
4. **Mandatory vs. optional:** is verification required to offer services at
   launch, or a badge that boosts trust/visibility? (Mandatory maximizes safety
   but raises the onboarding bar and exclusion risk.)
5. **Exclusion policy** for providers without a device/valid cédula.
6. **Retention period** for verification records post-account-deletion.

---

## Sources

- Didit — Ecuador cédula verification: https://didit.me/solutions/countries/ecuador/
- MetaMap — LATAM verification (iBeta-certified passive liveness): https://www.metamap.com/verification-platform-latin-america/
- Verifik — LATAM identity verification: https://verifik.co/en/identity-verification-latam/
- AWS Rekognition Face Liveness (pricing + ISO 30107-3 PAD): https://aws.amazon.com/rekognition/face-liveness/
- iProov — liveness (ISO 30107-3 L1+L2, FIDO, NIST 800-63-4): https://www.iproov.com/liveness-detection
