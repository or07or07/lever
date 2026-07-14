# Lever — Google Play Store Readiness Audit

**Status:** Phase 1 (audit only). No implementation changes were made while producing this document, per the requirement to complete the audit and prioritized plan before large changes begin.

**Audit date:** 2026-07-13
**Auditor:** Claude (Sonnet 5), working with the Lever owner
**Scope:** Backend (FastAPI/PostgreSQL), frontend (vanilla JS SPA), two Capacitor Android apps (client + provider), production VPS deployment

---

## 1. Current Architecture Summary

```
┌─────────────────┐     ┌──────────────────┐
│  Client APK      │     │  Provider APK     │
│  com.lever.app*  │     │  com.lever.provider│
└────────┬─────────┘     └────────┬──────────┘
         │  both load the SAME bundled frontend/index.html
         │  (Capacitor WebView, appFlavor flag locks role at launch)
         └───────────────┬───────────────────┘
                          │ HTTPS (REST) + WSS (WebSocket)
                          ▼
              ┌───────────────────────┐
              │  Cloudflare (proxy)    │  DNS, TLS, DDoS protection
              └───────────┬────────────┘
                          ▼
              ┌───────────────────────┐
              │  nginx (Docker)        │  reverse proxy
              └───────────┬────────────┘
                          ▼
              ┌───────────────────────┐
              │  FastAPI app (Docker)  │  Python 3, SQLAlchemy, JWT auth
              └───────────┬────────────┘
                          ▼
              ┌───────────────────────┐
              │  PostgreSQL (Docker)   │
              └───────────────────────┘
```

*See Finding GP-01 — the client app's real `applicationId` does not match its documented one.

- **Hosting:** Single VPS (Hostinger), Docker Compose (`app`, `nginx`, `db`, `certbot` containers)
- **Domain:** `lever-ec.com`, DNS hosted at Cloudflare (migrated from GoDaddy nameservers), proxied, `Full (strict)` TLS mode with a Cloudflare Origin Certificate on the VPS
- **Firewall:** UFW restricts SSH to a static IP + WireGuard VPN; `DOCKER-USER` iptables rules restrict ports 80/443 to Cloudflare's published IP ranges only (origin IP is not directly reachable)
- **CI/CD:** GitHub Actions builds both Android debug APKs on every push to `main` (matrix build, `apps/client` and `apps/provider`)
- **No staging or test environment exists** — there is only local dev and production (see Finding GP-19)

---

## 2. Current Mobile Implementation Type

**Capacitor wrapper around a vanilla JavaScript single-page app**, built as **two separate native Android projects** sharing one web codebase.

- Not a basic empty WebView: the SPA (`frontend/index.html`, ~4,200 lines) implements real client and provider dashboards, job creation/acceptance workflows, job-scoped real-time chat, live GPS tracking with a Leaflet map, vehicle management, dispute filing, notifications, and role-locked auth — this is a legitimate functional marketplace app, not a "website in a box." This satisfies the spirit of requirement #9/#24 ("not merely a low-functionality WebView"), though several features have real gaps (see Section 4).
- Native layer is minimal by design: only `@capacitor/core`, `@capacitor/android`, and `@capacitor/app` (for the hardware back button) are installed. No native plugins for camera, geolocation, or push notifications are integrated — those features either don't exist yet, or (in the case of GPS) rely on the WebView's JS `navigator.geolocation` API, which needs a manifest permission that is currently **missing** (Finding GP-02).
- Both apps are built via one shared GitHub Actions matrix workflow (`.github/workflows/android-build.yml`) and currently only produce **unsigned debug APKs** — no release signing, no `.aab`, no Play App Signing setup exists yet (Finding GP-03).

---

## 3. Website Availability Findings

| URL | Status | Notes |
|---|---|---|
| `https://lever-ec.com` | ✅ `200`, real TLS cert (Cloudflare) | The 502 issue mentioned in the requirements was already resolved during earlier infrastructure work this session (VPS redeploy, Cloudflare cutover, firewall lockdown) — confirmed working now |
| `https://lever-ec.com/privacy` | ⚠️ `200`, but **no real content** | Falls through to the SPA's catch-all route and serves the same landing page as `/`. No privacy policy exists anywhere in the codebase. |
| `https://lever-ec.com/terms` | ⚠️ `200`, but **no real content** | Same catch-all fallback. No terms document exists. |
| `https://lever-ec.com/delete-account` | ⚠️ `200`, but **no real content** | Same catch-all fallback. No account-deletion flow exists, in-app or on the web. |
| `https://lever-ec.com/support` | ⚠️ `200`, but **no real content** | Same catch-all fallback. There is an in-app `#/support` hash route with an FAQ (web/PWA only, not shown in the native apps — see earlier session work), but no plain HTTPS path works pre-login the way Play Store review expects. |

**Verified:** HTTPS redirect works, TLS cert is valid and trusted, health checks exist (`GET /health` reports app/DB/SMTP status). **Not verified/present:** friendly error pages for 4xx/5xx (FastAPI's default JSON error responses are returned, not a styled page — acceptable for an API but the SPA itself has no error boundary for a failed initial load), centralized log aggregation (currently just `docker logs`), and there is no separate frontend-only or database-only health check — the single `/health` endpoint conflates all three.

---

## 4. Google Play Compliance Gap Analysis

Findings are numbered `GP-01` onward, ordered roughly by severity. Each includes what blocks submission.

### GP-01 — Client app's real package ID doesn't match its documented one
- **Status: RESOLVED** — owner decided to keep `com.lever.app` (already built/tested); `apps/client/capacitor.config.json` corrected to match. `build.gradle`/`MainActivity.java` were already correct.
- **Severity:** High
- **Description:** `apps/client/capacitor.config.json` declares `appId: "com.lever.client"`, and all commit messages/documentation from this session refer to it as such. But the actual Android `applicationId` in `apps/client/android/app/build.gradle` — and the Java package of `MainActivity.java` — is still `com.lever.app`, the original ID from before the client/provider split. Capacitor's `appId` config only takes effect at `cap add` time for a brand-new native project; it does not retroactively rename an existing one, and `cap sync` was run on the pre-existing `android/` folder rather than a fresh `cap add`.
- **Evidence:** `apps/client/android/app/build.gradle:7` → `applicationId "com.lever.app"`; `apps/client/capacitor.config.json` → `"appId": "com.lever.client"`; `apps/client/android/app/src/main/java/com/lever/app/MainActivity.java` package matches `com.lever.app`.
- **Risk:** Not a functional bug (the app builds and runs fine), but the package ID is what Google Play permanently binds a listing to — it cannot be changed after first publish without creating an entirely new listing and losing all reviews/install history. Publishing under an ID that doesn't match your own documentation/branding is a decision that needs to be made deliberately, once, before submission.
- **Recommended fix:** Decide the final production package ID now (`com.lever.app`, `com.lever.client`, or something else entirely — e.g. many teams use a reverse-DNS of a real owned domain) and make `build.gradle`, the Java package folder/`MainActivity.java`, and `capacitor.config.json` consistent. This is a "decide once, get it right" item — see Section 10.
- **Affected files:** `apps/client/android/app/build.gradle`, `apps/client/android/app/src/main/java/com/lever/app/MainActivity.java` (and its directory path), `apps/client/capacitor.config.json`
- **Complexity:** Low (mechanical rename), but requires an explicit decision first
- **Blocks submission:** Yes — must be resolved before you can create the Play Console listing, since the package ID is permanent

### GP-02 — Missing location permission breaks GPS tracking on Android
- **Status: RESOLVED** — added `ACCESS_COARSE_LOCATION`/`ACCESS_FINE_LOCATION` to the **provider** app's manifest only (confirmed via a full-file grep that `navigator.geolocation` is called exclusively from `startProviderTracking()` — the client app only *watches* a provider's shared position via WebSocket against the request's already-known coordinates, and never reads its own device GPS, so it correctly gets zero location permission). Verified Capacitor's `BridgeWebChromeClient.onGeolocationPermissionsShowPrompt()` already handles the native runtime-permission dialog automatically and contextually (triggered exactly when the tracking screen calls `navigator.geolocation`, not at app launch) — no custom native code was needed beyond the manifest declaration. Also fixed a real UX bug found while verifying this: on permission denial or a GPS error, the tracking UI previously got stuck showing "Starting GPS..." forever; it now shows a clear Spanish/English message and cleanly reverts to idle.
- **Severity:** Critical
- **Description:** Both `AndroidManifest.xml` files declare only `android.permission.INTERNET`. The app's core "live GPS tracking" feature (client watches provider location; provider broadcasts location) uses the WebView's JS `navigator.geolocation` API. On Android, a WebView's geolocation calls will not work — the WebView has no permission to grant — unless the hosting app holds `ACCESS_FINE_LOCATION` (and ideally `ACCESS_COARSE_LOCATION`) and the host `WebChromeClient` implements `onGeolocationPermissionsShowPrompt`. Capacitor's default `WebChromeClient` does handle that callback, but only if the manifest permission exists for it to check against.
- **Evidence:** `apps/client/android/app/src/main/AndroidManifest.xml`, `apps/provider/android/app/src/main/AndroidManifest.xml` — both show only `<uses-permission android:name="android.permission.INTERNET" />`.
- **Risk:** A core advertised feature (live tracking) is almost certainly non-functional in the installed APKs right now, even though the JavaScript code for it is fully implemented. This would also likely surface as a confusing silent failure during Google's review if a reviewer tries to use tracking.
- **Recommended fix:** Add `ACCESS_FINE_LOCATION` and `ACCESS_COARSE_LOCATION` to both manifests. Per the task's own permission requirements (Section 10), request it contextually (only when the user opens a job that needs tracking, not at app launch), and avoid `ACCESS_BACKGROUND_LOCATION` unless truly required — the current design (tracking only while a job screen is open) does not need background location.
- **Affected files:** `apps/client/android/app/src/main/AndroidManifest.xml`, `apps/provider/android/app/src/main/AndroidManifest.xml`
- **Complexity:** Low for the manifest change; Medium if a proper runtime-permission request flow with rationale UI is added (Android 6+ requires requesting dangerous permissions at runtime, not just declaring them in the manifest)
- **Blocks submission:** Yes — a core feature must actually work before submission, and Play's review process actively tests declared functionality

### GP-03 — No release signing, no `.aab`, no Play App Signing
- **Status: RESOLVED (code + workflow; you still need to do the one-time key generation)** — added a `signingConfigs.release` block to both `apps/client/android/app/build.gradle` and `apps/provider/android/app/build.gradle` that reads either a local, gitignored `keystore.properties` file or environment variables — never a hardcoded value. If neither is present, the release build type is simply left unsigned rather than failing, so `assembleDebug`/everyday development is completely unaffected. Added `.github/workflows/android-release.yml`, manually triggered (`workflow_dispatch`, not on every push), with two explicit jobs (client, provider — GitHub Actions can't index secrets dynamically by a matrix variable, and the two apps need distinct keys anyway) that decode a base64-encoded keystore secret to a temp file, run `bundleRelease`, upload the signed `.aab`, and delete the decoded keystore afterward. Full instructions — including the exact `keytool` commands, why losing the upload key is unrecoverable, and the full secrets list — are in the new `docs/release-signing.md`.
  **What I could not verify:** this sandbox's network access couldn't reliably download the Gradle distribution (`Connection reset` partway through `gradle-8.14.3-all.zip`), so I hand-reviewed the Groovy for correctness but never actually ran `./gradlew bundleRelease` against it. The pattern is the standard, extremely well-documented one for Capacitor/Android signing, but please run a real build locally (`docs/release-signing.md` section 2) before relying on the CI workflow for your first submission.
- **Severity:** Critical
- **Description:** The only CI build target is `gradlew assembleDebug`, producing a debug-signed `.apk`. Google Play requires an **App Bundle** (`.aab`), signed with a release key, uploaded via Play App Signing.
- **Evidence:** `.github/workflows/android-build.yml` — `run: ./gradlew assembleDebug --no-daemon`. No `signingConfigs` block exists in either `apps/*/android/app/build.gradle`.
- **Risk:** Cannot submit to Play Console at all without this.
- **Recommended fix:** Generate a release keystore per app (kept out of the repo — see GP-04), add a `release` signing config, and add an `assembleRelease`/`bundleRelease` CI job that produces a signed `.aab`. Enroll in Play App Signing during the first Play Console upload so Google manages the signing key for updates.
- **Affected files:** `apps/client/android/app/build.gradle`, `apps/provider/android/app/build.gradle`, `.github/workflows/android-build.yml`
- **Complexity:** Medium
- **Blocks submission:** Yes

### GP-04 — No secrets-management story for signing keys or API keys
- **Status: RESOLVED** — GitHub Actions encrypted secrets (8 total: keystore base64 + store password + key alias + key password, per app — see `docs/release-signing.md`). Injected only as environment variables at build time, decoded to a runner-temp file that's deleted immediately after the build (`if: always()` cleanup step), never written into the repo checkout or a build artifact. Local release builds use the same `keystore.properties` mechanism as GP-03, gitignored, with a `.template` file committed instead showing the expected format with placeholder values.
- **Severity:** High
- **Description:** There is currently no keystore, no signing password, and no mechanism (GitHub Actions secrets, etc.) wired up to inject them into a release build. This needs to exist before GP-03 can be completed safely.
- **Risk:** If done carelessly, a keystore or password could end up committed to the repo (which has no `.gitignore` protection specifically for keystores beyond the generic `*.jks`/`*.keystore` patterns already added — those patterns are present and correct, but only prevent accidental commits, they don't provide a place to *store* the secret for CI use).
- **Recommended fix:** Store the release keystore + passwords as GitHub Actions encrypted secrets (or a dedicated secrets manager), inject them into the CI signing step via environment variables, never write them to disk in a way that could be logged.
- **Affected files:** `.github/workflows/android-build.yml`, `.gitignore` (already has `*.jks`/`*.keystore` — correct, no change needed there)
- **Complexity:** Low–Medium
- **Blocks submission:** Yes (prerequisite for GP-03)

### GP-05 — No privacy policy exists anywhere
- **Status: RESOLVED** — real, always-reachable `/privacy` page added (`frontend/legal/privacy.html`, served via an explicit FastAPI route registered before the SPA catch-all, so it works even if the JS bundle fails to load). Covers every required element: what's collected (with an honest table — explicitly states photos and payments are *not* collected, matching actual app behavior), why, third parties (Hostinger SMTP, OpenStreetMap Nominatim, Cloudflare), retention, user rights, contact. Linked from the registration checkbox and the Settings screen. **Still needs your review** — I drafted accurate, honest content based on the real data inventory, but I'm not a lawyer and this hasn't been reviewed against Ecuador's LOPD by one; treat this as a solid first draft, not a final legal document.
- **Severity:** Critical
- **Description:** No privacy policy content exists in the codebase, on the live site, or in the app. `/privacy` silently falls through to the SPA landing page (Section 3).
- **Risk:** Google Play requires a privacy policy URL for every app that handles personal data (Lever collects email, phone, location, messages, vehicle info — see Section 5). Non-negotiable submission blocker.
- **Recommended fix:** Draft a Spanish-first privacy policy covering the required elements (Section 4 of the original requirements), publish it at a real, always-reachable, pre-login route (not a hash route that depends on the SPA loading — needs to work even if the JS bundle fails), link it from the app's settings/registration screens.
- **Affected files:** New: a real backend route or static page for `/privacy`; `frontend/index.html` (link from registration + settings); Terms/Privacy links need to be reachable without authentication and without depending on the SPA's JS executing correctly
- **Complexity:** Medium (content drafting is the bulk of the work; technical implementation is straightforward)
- **Blocks submission:** Yes
- **Needs owner/legal input:** Yes — see Section 10. I can draft the technical scaffolding and a reasonable first draft of the policy text, but the actual legal claims (what's retained, third-party processors, LOPD compliance specifics) need your review before publishing, per Section 22 rule 9 ("Do not make unsupported legal or compliance claims").

### GP-06 — No terms and conditions exist
- **Status: RESOLVED** — real, always-reachable `/terms` page added the same way as `/privacy`. Added `terms_accepted_version`/`terms_accepted_at` columns to `User` (migration `0002` — see the important note below), a required `accepted_terms` field on registration (rejected server-side if false or omitted — including a real Pydantic v2 bug I found and fixed where validators silently skip default values unless `validate_default=True` is set, which would have let acceptance be bypassed entirely by just omitting the field), and a required checkbox on the registration form linking to both documents. Verified end-to-end against a live server: omitting/falsifying acceptance is rejected with no DB row created, accepting succeeds and records version+timestamp correctly, and a provider job-detail request afterward is unaffected.
- **Important operational note:** this app relies on `Base.metadata.create_all()` at startup, which only creates missing tables — it will **not** add these new columns to the already-existing `users` table in production. The Alembic migration must actually run (`alembic upgrade head`) for this to take effect on the live database; simply redeploying the code is not sufficient. `deploy.sh` already calls this after every deploy, but I could not verify locally whether Alembic's version state matches what I assumed (`0001`) — please confirm this succeeds on the next deploy rather than assuming it worked.
- **Severity:** Critical
- **Description:** Same situation as GP-05 — `/terms` has no real content, and there is no acceptance-tracking mechanism (no `terms_accepted_at`/`terms_version` field anywhere in `models.py`).
- **Risk:** Submission blocker; also a real legal exposure gap for a marketplace facilitating real-world services between strangers (liability, dispute handling, prohibited services all currently undocumented).
- **Recommended fix:** Draft Terms & Conditions per the required contents (Section 4 of requirements). Add `terms_version` and `terms_accepted_at` (and same for privacy) columns to `User`, require acceptance at registration, block registration until accepted.
- **Affected files:** New Terms content/page; `models.py` (new columns + migration); `routes/auth.py` (`register` endpoint); `frontend/index.html` (registration form checkbox)
- **Complexity:** Medium
- **Blocks submission:** Yes
- **Needs owner/legal input:** Yes — same reasoning as GP-05

### GP-07 — No account deletion mechanism, in-app or on the web
- **Status: RESOLVED** — added `DELETE /api/auth/account` (requires re-entering the password, since a bearer token alone shouldn't be able to trigger an irreversible action). Per the owner's confirmed policy, it anonymizes rather than hard-deletes the `User` row: email/password/contact details/avatar/precise location are wiped, the row is deactivated (`is_active=False`, which `get_current_user` already checks — this instantly revokes every existing session with no separate token-blocklist needed), and `ClientProfile`/`MechanicProfile` names are replaced with "Usuario eliminado". Purely private data with no bearing on anyone else's history — `Vehicle`, `Notification`, `ProviderLocation` breadcrumbs — is hard-deleted outright. `Job`, `ServiceRequest`, `Message`, and `Review` rows are left untouched so the other party's job history and rating integrity survive intact, exactly as decided. Added a guard that blocks deletion with a 409 while the user has an open `ServiceRequest`/`Job` (anything not `completed`/`cancelled`), so no one can vanish mid-job and strand the other party. Built both required paths: an in-app `Settings > Danger Zone > Eliminar mi cuenta` flow (password-confirmation modal) and a public `/delete-account` page (`frontend/legal/delete-account.html`) for users without the app, which logs in and calls the same endpoint. Verified end-to-end against a live server and in-browser: wrong password rejected, active-job guard blocks both client- and provider-side deletion and lifts once the job is completed, deletion anonymizes the row correctly (confirmed by direct DB query), the token is immediately rejected afterward, and the other party's job/message/review data is confirmed intact and readable post-deletion. Also found and fixed a real bug during this verification: the standalone page's success message `<div>` was nested inside the `<form>` it hides on success, so the confirmation message never actually appeared — moved it outside the form.
- **Severity:** Critical
- **Description:** There is no `DELETE /api/auth/me` or equivalent endpoint, no "Delete Account" UI anywhere in `frontend/index.html`'s settings screen, and no `/delete-account` web page.
- **Evidence:** `grep` for delete-account/GDPR/LOPD/retention logic across the entire backend returned nothing.
- **Risk:** Google Play has required an accessible account-deletion path (in-app **and** a web fallback reachable without installing the app) for all apps that support account creation, since late 2023. Hard submission blocker.
- **Recommended fix:** Build both paths per Section 5 of the requirements: an in-app `Settings > Account > Delete Account` flow (explain what's deleted, require confirmation/re-auth, revoke the JWT, then either hard-delete or anonymize per-table per the retention decisions in Section 10) and a public `/delete-account` page for users who can't/won't install the app. Needs a clear policy decision on what gets anonymized vs. hard-deleted (e.g., can a `Message` row be deleted if the *other* party in the conversation still needs it? Can a `Review` be deleted without corrupting a provider's `avg_rating` history?).
- **Affected files:** New backend route(s), `models.py` (soft-delete/anonymization strategy), `frontend/index.html` (settings screen), new public `/delete-account` page
- **Complexity:** Medium–High (the technical deletion itself is straightforward; deciding the retention/anonymization rules per table, correctly, is the real work)
- **Blocks submission:** Yes
- **Needs owner input:** Yes — what legal/financial/fraud-prevention reason (if any) justifies retaining data post-deletion, e.g. for disputes already filed. See Section 10.

### GP-08 — Zero content moderation infrastructure
- **Status: RESOLVED** — added `Report` and `Block` tables (migration `0003`; both brand-new tables, so unlike `0002` this one would also self-heal via `create_all()` on a fresh boot, but should still run explicitly to keep Alembic's version state accurate). `POST /api/reports` accepts `entity_type` (`user`/`message`/`review`/`service_request`) + `entity_id`; who's actually being reported is always resolved server-side from the entity itself (message sender, review author, request owner) rather than trusted from the client, so a report can't be filed against the wrong person. Blocking (`routes/moderation.py`) is self-service and symmetric — either party having blocked the other hides them from each other in the job board, provider/request search, and the map, and blocks sending new chat messages (enforced in both the REST `POST /api/messages/job/{id}` path and the separate WebSocket `/ws/messages/{job_id}` path, which had its own independent send/persist logic that would otherwise have bypassed the block entirely — found this by checking whether the two chat code paths were actually consistent, not just the one I fixed first). Added a defense-in-depth block check directly on `POST /api/provider/board/{id}/accept` too, in case a blocked pair's request ID is guessed or replayed instead of reached via the (already-filtered) board. Admin moderation queue at `/api/admin/reports` (list/get/resolve, mirrors the existing disputes pattern) plus an "Reportes" page in the admin UI with a one-click "Deactivate Reported User" action reusing the existing user-deactivation endpoint. Report entry points wired into chat (report/block the other job participant), reviews received (report a specific review), and job detail pages (report/block the counterpart) for both client and provider roles. Verified end-to-end live: a review report resolves to the correct `reported_user_id` (the review's author, not the provider who filed it); the admin queue's open→reviewing→resolved flow works with notes; a blocked client's request disappears from the provider's board and a direct accept attempt on it 403s; messaging 403s in both directions after either party blocks the other; unblocking removes the restriction and the Settings "Usuarios Bloqueados" list updates correctly.
- **Severity:** Critical
- **Description:** No `Report`, `Block`, or moderation-related table exists in `models.py`. There is no way for a user to report another user, a message, a review, or a job posting. There is no admin moderation queue beyond the existing dispute-resolution screen (which handles job disputes, not content/conduct reports).
- **Risk:** Lever has open-ended free-text fields everywhere a stranger-to-stranger marketplace needs them most — job descriptions, chat messages, review comments, bios — with zero abuse-reporting path. This is both a Play Store policy requirement (apps with user-generated content/messaging need reporting and blocking) and a real user-safety gap given the app connects people for in-person services.
- **Recommended fix:** New `Report` table (reporter, reported entity type/id, category, description, status), new `Block` table (blocker/blocked user pair, enforced in message/job-visibility queries), admin moderation queue UI, and report entry points wired into chat, reviews, and profiles per Section 6 of the requirements.
- **Affected files:** `models.py` (new tables + migration), new `routes/moderation.py`, `routes/admin.py` (moderation queue), `frontend/index.html` (report/block UI throughout messaging, reviews, profiles)
- **Complexity:** High — this is the single largest implementation item in the whole audit
- **Blocks submission:** Yes

### GP-09 — No push notifications (confirmed gap from earlier audit, still open)
- **Severity:** Medium
- **Description:** No FCM integration, no device-token storage, no native push plugin installed. Notifications only work via in-app polling while the app is foregrounded.
- **Risk:** Not a hard Play Store blocker by itself, but materially weakens the product (users won't know about new job offers/messages when the app is closed) and was explicitly listed as a desired capability in Section 9 of the requirements.
- **Recommended fix:** `@capacitor/push-notifications` + Firebase project + a `device_tokens` table + backend logic to send on job/message events.
- **Affected files:** `apps/*/package.json`, both native projects, new backend table + routes, `frontend/index.html`
- **Complexity:** Medium–High
- **Blocks submission:** No, but strongly recommended before launch

### GP-10 — No payment processing at all, despite the marketing copy promising a fee
- **Status: RESOLVED** — owner decided to launch fee-free and correct the copy rather than build payments now. Removed the $0.05 fee notice from the new-request modal and provider-selection cards, and corrected the "How much does it cost?" FAQ answer to state the platform is free. Real payment processing (e.g. Stripe Connect) remains a clearly-scoped future phase.
- **Severity:** High
- **Description:** The landing page FAQ states a $0.05 scheduling fee, but `requirements.txt` has no payment SDK, and no payment-related model/route exists anywhere.
- **Risk:** Not a Play Store blocker on its own (an app can facilitate real-world service payments outside the app via cash/external processor without needing Play Billing — see Finding GP-11 for the one case where that's *not* true). But the current landing copy makes a claim the product doesn't back up, which is itself a store-listing accuracy problem (Section 16 explicitly prohibits inaccurate feature claims) and a business-readiness gap independent of Play compliance.
- **Recommended fix:** Either implement real payment processing (e.g., Stripe Connect for marketplace payouts) or remove/correct the fee claim from the landing page and app copy until it's real.
- **Affected files:** `frontend/index.html` (landing page FAQ), eventually new payment integration if implemented
- **Complexity:** Low to correct the copy; High to actually implement payments
- **Blocks submission:** No directly, but the listing/copy must not claim a feature that doesn't exist
- **Needs owner input:** Yes — is a $0.05 fee still the intended model, and should payment processing be built before launch or should the claim be removed for a v1 launch that facilitates the introduction only? See Section 10.

### GP-11 — Payment/billing model needs Google Play Billing review if any *digital* feature is monetized
- **Severity:** Informational (contingent — only applies if a specific plan exists)
- **Description:** The requirements correctly flag that while payment for the *physical* service itself can go through an external processor, any **digital-only** feature (e.g., a "featured listing" upsell for providers, a premium subscription tier) would need to go through Google Play's own in-app billing, not an external processor, per Play policy.
- **Risk:** None currently, since no such feature exists. Flagging so it isn't accidentally built the wrong way later.
- **Recommended fix:** No action needed now. If a "boost my listing"-style feature is ever planned, route it through Play Billing, not Stripe/external.
- **Blocks submission:** No

### GP-12 — In-memory rate limiter and dispatch timers (repeat of earlier audit finding, still relevant to Play readiness)
- **Severity:** Medium
- **Description:** `rate_limiter.py`'s sliding-window store and `dispatch.py`'s offer-rotation timers are process-local memory, not shared across workers/instances.
- **Risk:** Not a Play Store blocker, but relevant to Section 19 (observability/operational readiness) and Section 7 (brute-force/rate-limit protection) — if the app ever scales past a single worker, rate limiting silently stops being effective per-user, and in-flight dispatch offers could be lost on a process restart.
- **Recommended fix:** Move to Redis-backed rate limiting and dispatch state if/when scaling beyond one process.
- **Affected files:** `rate_limiter.py`, `dispatch.py`
- **Complexity:** Medium
- **Blocks submission:** No

### GP-13 — 24-hour JWTs with no revocation or refresh mechanism
- **Status: RESOLVED (revocation part)** — added `token_version` to `User` (migration `0004`), embedded as the `ver` claim on every issued JWT. `get_current_user` now rejects any token whose `ver` doesn't match the user's current `token_version`. New `POST /api/auth/logout-all` bumps it, instantly invalidating every outstanding token for that account in one call — no session table needed. Also wired into `reset-password-verify`: resetting your password now kills every other session too, since a password reset is exactly the "someone else might have had my password" scenario. Exposed in the UI as a "Cerrar sesión en todos los dispositivos" button in Settings, satisfying Section 12's "log out of all devices" requirement. Tokens issued before this deploy have no `ver` claim; they're treated as version 0 (matching every user's default), so this deploy does **not** force a mass logout — revocation only kicks in once something actually bumps the version. Verified live: calling `logout-all` immediately 401s the very token used to call it; a fresh login works normally; password reset independently kills the pre-reset token the same way.
  **Not done — deliberately out of scope for this pass:** I did not shorten the 24h access-token lifetime or add a refresh-token flow. The audit's own recommendation only asks to "consider" a refresh flow; building one (rotation, a token table, a `/refresh` endpoint, client-side retry-on-401 logic) is a materially larger, separate feature, and shortening the token lifetime without a refresh flow to back it up would force everyone to re-log-in far more often — a real UX regression I didn't want to introduce silently. Happy to build the full refresh-token flow as its own follow-up if you want shorter-lived access tokens.
- **Severity:** Medium
- **Description:** `config.py` sets `access_token_expire_minutes: int = 1440` (24h). There is no refresh-token flow and no server-side session table — a stolen token remains valid for a full day with no way to revoke it early, and there's no "log out of all devices" capability (required by Section 12).
- **Recommended fix:** Add a session/token table (or at minimum a `token_version`/`revoked_at` column on `User` checked on every request), implement "log out everywhere" by bumping that version, and consider shortening access-token lifetime with a refresh-token flow.
- **Affected files:** `auth.py`, `models.py`, `config.py`
- **Complexity:** Medium
- **Blocks submission:** No, but Section 12 explicitly requires "logout from all devices" and "session expiration" — worth resolving before submission for policy alignment, not strictly a Play Store rejection reason

### GP-14 — No MFA for administrators
- **Severity:** Medium
- **Description:** Admin login uses the same single-factor email+password flow as every other role.
- **Recommended fix:** Add TOTP-based MFA for the `admin` role specifically (least invasive: only gate the admin role, not all users).
- **Affected files:** `auth.py`, `routes/auth.py`, `models.py` (TOTP secret storage)
- **Complexity:** Medium
- **Blocks submission:** No

### GP-15 — No crash reporting, error monitoring, or analytics SDK
- **Severity:** Low–Medium
- **Description:** No Sentry, Firebase Crashlytics, or equivalent exists. The only production visibility is `docker logs` and the `/health` endpoint.
- **Risk:** Not a Play Store blocker, but makes Section 19 (observability) and post-launch debugging difficult, and the Data Safety form needs to accurately declare *any* such SDK if one is added later.
- **Recommended fix:** Add a lightweight crash/error reporting tool if desired. Not urgent for a first submission with a small user base.
- **Blocks submission:** No

### GP-16 — Verification/trust labeling doesn't exist yet
- **Status: RESOLVED** — owner decided to correct the copy rather than build verification now. All false "verified professional" claims removed from the landing page (trust section, "how it works" step 2, and the quality FAQ answer) and replaced with claims that are actually true today (email verification, direct messaging, review system). Real provider verification remains a future phase if desired.
- **Severity:** Low
- **Description:** `email_verified` exists and is enforced (users can't proceed past registration without it). There is no phone verification, no provider identity-verification workflow, and the UI doesn't display any "Email verified" / "Identity pending" badges.
- **Recommended fix:** At minimum, do not claim any verification the product doesn't perform (the landing page currently says "Cada proveedor pasa por un proceso de verificación antes de ofrecer servicios" — **this claim is not currently true**, since there is no provider verification workflow at all beyond registering with a profession). This is a direct instance of the "do not claim a background check that doesn't exist" rule in Section 7 of the requirements and needs correcting regardless of Play Store timing.
- **Affected files:** `frontend/index.html` (landing page trust-section copy), eventually a real verification workflow if one is built
- **Complexity:** Low to fix the copy; Medium–High to build real verification
- **Blocks submission:** No directly, but the false claim should be corrected regardless
- **Needs owner input:** Yes — is provider verification planned before launch, or should the landing page copy be softened to match reality for now?

### GP-17 — Confirmed: exact job coordinates are exposed to every online provider before any job is accepted
- **Status: RESOLVED** — added `ServiceRequestBoardOut` (no lat/lng) for `GET /api/provider/board`, and changed `ServiceRequestWithDistance` (used by `GET /api/search/requests`) to extend it too, keeping `distance_miles` as the privacy-appropriate signal instead of exact coordinates. `JobDetail`/`ServiceRequestOut` (used only after a provider has accepted a job) are unchanged — precise coordinates remain available exactly where they're legitimately needed. Also found and fixed the identical exposure in `GET /api/search/map/requests` (used by the map view, reachable by any authenticated client or provider, not just matched ones) by adding a stable per-request coordinate jitter (~300m) rather than plotting exact addresses. Verified end-to-end against a live local server: the board response now has zero `latitude`/`longitude` keys, while the job-detail response after accepting correctly retains them.
- **Severity:** High (upgraded from Medium after direct verification — this is confirmed, not hypothetical)
- **Description:** `GET /api/provider/board` — visible to *any* online provider browsing open work, not just one who's been matched or has accepted anything — returns `ServiceRequestOut`, which includes `latitude` and `longitude` directly (`schemas.py:313-314`), plus the free-text `location` field. This means exact GPS coordinates for every pending job are broadcast to the entire pool of online providers for that profession, before any relationship between client and provider exists. This directly contradicts the requirement to "share precise job location only when operationally necessary" — necessity only begins once a specific provider is actually engaged with that job.
- **Evidence:** `routes/provider.py:186` (`@router.get("/board", response_model=List[ServiceRequestOut])`), `schemas.py:298-316` (`ServiceRequestOut` includes `latitude`/`longitude` with no masking).
- **Risk:** Real user-safety exposure, not just a policy technicality — any registered provider (no verification currently exists, per GP-16) can see the exact location of every open request in their profession, whether or not they ever intend to accept it.
- **Recommended fix:** Return an approximate location (e.g., rounded coordinates or a neighborhood-level description) in the board listing, and only expose exact `latitude`/`longitude` in `routes/provider.py`'s job-detail response after a provider has accepted the request (i.e., keep precise coordinates in `ServiceRequestDetail`/job-scoped responses, remove them from the board's `ServiceRequestOut` listing).
- **Affected files:** `schemas.py` (split precise vs. approximate location into separate response models), `routes/provider.py` (board endpoint should use the approximate variant)
- **Complexity:** Low–Medium
- **Blocks submission:** No formally, but this should be fixed before submission given it's a concrete, verified privacy exposure, not a theoretical one

### GP-18 — No `docs/` folder or any of the required documentation exists yet
- **Severity:** Informational
- **Description:** None of the 10 documents requested in Section 21 of the requirements exist yet (this file is the first). Confirmed via `find` — no `docs/` directory existed before this audit.
- **Recommended fix:** Addressed by this document and the prioritized plan in Section 9 below; the remaining 9 documents should be produced incrementally alongside the actual implementation work they document (a runbook is only useful once the runbook's procedures actually exist).
- **Blocks submission:** No (informational)

### GP-19 — No environment separation (local vs. staging vs. production)
- **Severity:** Low
- **Description:** Section 20 requires separate local/test/staging/production environments. Currently there is only local dev (SQLite, `DEBUG=true`) and production (the VPS). There's no staging environment that mirrors production for pre-release testing.
- **Recommended fix:** Not urgent for a first submission given the small scale, but worth a lightweight staging setup (a second, smaller VPS or a Docker Compose profile pointed at a separate database) before doing anything riskier like a payment integration.
- **Blocks submission:** No

### GP-20 — Dead footer links found while wiring up GP-05/GP-06 (not in the original scan)
- **Status: RESOLVED**
- **Severity:** Low
- **Description:** The landing page footer's "Términos de Servicio" and "Política de Privacidad" links were `href="#"` — pure placeholders, going nowhere. Found while wiring the new `/terms` and `/privacy` pages into the app. "Centro de Ayuda" only scrolled to an in-page FAQ section rather than linking to a real reachable page.
- **Evidence:** `frontend/index.html`, landing page footer section.
- **Recommended fix:** Applied — all three now point to the real `/terms`, `/privacy`, `/support` pages.
- **Affected files:** `frontend/index.html`
- **Complexity:** Trivial
- **Blocks submission:** No, but exactly the kind of "broken button" the requirements explicitly call out — worth having fixed regardless.

---

## 5. Personal Data Inventory

| Data element | Collected? | Where (table/field) | Shared with third parties? | Encrypted in transit | Encrypted at rest | Notes |
|---|---|---|---|---|---|---|
| Email address | Yes | `users.email` | Sent to Hostinger SMTP for delivery of verification/reset emails | Yes (TLS to DB, TLS to SMTP) | No (plaintext column) | Primary identifier, unique |
| Password | Yes (as hash) | `users.password_hash` | No | Yes | Yes (bcrypt) | Never stored/transmitted in plaintext after hashing |
| Phone number | Yes (optional field) | `client_profiles.phone`, `mechanic_profiles.phone` | No | Yes | No | Not currently verified (no SMS/OTP flow) |
| Full name | Yes (optional) | `client_profiles.full_name`, `mechanic_profiles.full_name` | No | Yes | No | |
| Home/service address | Yes (free text) | `client_profiles.address` | Visible to matched providers (see GP-17 — exact exposure scope needs verification) | Yes | No | |
| Precise GPS coordinates (one-time, per request) | Yes | `service_requests.latitude/longitude` | Visible to matched/nearby providers via search | Yes | No | |
| Continuous GPS breadcrumbs (during active job) | Yes | `provider_locations` table | Visible to the client on that specific job only, and the provider themself | Yes | No | Auto-generated every few seconds while a job is `en_route`/active; no explicit stated retention/pruning policy found in code |
| Vehicle info (make/model/year/plate/VIN/mileage) | Yes (client-provided, optional) | `vehicles` table | Visible to the assigned provider on a job | Yes | No | VIN + plate are more sensitive than typical profile data |
| Chat messages | Yes | `messages` table | Visible to both job participants + admin (via dispute review) | Yes | No | No message-deletion/edit capability currently exists for users |
| Job descriptions | Yes | `service_requests.description` | Visible to all providers viewing the open board | Yes | No | |
| Reviews/ratings | Yes | `reviews` table | Publicly visible on provider profiles | Yes | No | |
| Dispute descriptions | Yes | `disputes.description` | Visible to admin only | Yes | No | |
| Profile photo (`avatar_url`) | Field exists, no upload mechanism wired up | `client_profiles.avatar_url`, `mechanic_profiles.avatar_url` | N/A — not actually populated by any current UI flow | N/A | N/A | Confirmed no photo-upload endpoint/UI exists despite the DB column |
| Notification content | Yes | `notifications` table | No | Yes | No | |
| IP address | Implicitly, via nginx/Cloudflare access logs and the in-memory rate limiter | Not persisted to the app DB | Passes through Cloudflare (see their own data processing) | Yes | N/A (not stored in app DB) | |
| Device/session tokens | JWT only, not persisted server-side | N/A (stateless JWT) | No | Yes | N/A | No revocation table exists (GP-13) |
| Payment information | **Not collected at all** | N/A | N/A | N/A | N/A | No payment processor integrated (GP-10) |
| Crash logs / analytics | Not collected | N/A | N/A | N/A | N/A | No SDK integrated (GP-15) |

**Retention:** No explicit retention or auto-deletion policy exists for any of the above. This needs an owner decision — see Section 6.

---

## 6. Android Permissions Inventory

| Permission | Currently declared? | Feature that needs it | Currently requested correctly? |
|---|---|---|---|
| `INTERNET` | Yes (both apps) | All network calls | Yes — implicit, no runtime prompt needed |
| `ACCESS_FINE_LOCATION` / `ACCESS_COARSE_LOCATION` | **No** | Live GPS tracking (client watching provider, provider broadcasting) | **Missing — GP-02, must be added and requested contextually, only when a tracking-enabled job screen opens** |
| Camera | Not declared | Not currently used by any wired-up feature (no photo upload exists) | N/A until photo upload is built |
| Photo/media access | Not declared | Same as above | N/A until built; when built, prefer the Android Photo Picker per the requirements, which needs no storage permission at all on Android 13+ |
| `POST_NOTIFICATIONS` (Android 13+) | Not declared | Not needed yet — no push notifications exist (GP-09) | N/A until push is built |
| Background location | Not declared, correctly | Not used — tracking only happens while a job screen is open in the foreground | Correct as-is; do not add this without a specific, justified need |
| Contacts / call log / SMS | Not declared, correctly | Not used | Correct as-is |

**Summary:** The app currently under-requests (missing the one permission it actually needs) rather than over-requests, which is a good starting position once GP-02 is fixed — there's no permission-bloat problem to clean up.

---

## 7. Third-Party SDK / Service Inventory

| Service | Purpose | Data it receives |
|---|---|---|
| Hostinger SMTP (`smtp.hostinger.com:465`) | Sends verification codes and password-reset emails | Recipient email address, email content (includes verification codes) |
| OpenStreetMap Nominatim (public API) | Free-text address → lat/lng geocoding | Address text entered by the user; no API key/account, OSM's own privacy policy applies |
| Cloudflare | DNS, reverse proxy, TLS termination, DDoS protection | All HTTP(S) traffic to the app passes through Cloudflare's edge; see Cloudflare's own data processing terms |
| GitHub / GitHub Actions | Source control, CI builds | Source code, build logs; not part of the running production data path |
| Leaflet.js (via CDN) | Map rendering in the frontend | Loads map tiles from `tile.openstreetmap.org` — no user data sent beyond the tile requests themselves (lat/lng of the visible map area) |

**Not present, but worth confirming stays accurate for the Data Safety form:** no analytics SDK, no advertising SDK, no crash-reporting SDK, no payment SDK, no push-notification SDK. If any of GP-09/GP-10/GP-15 are implemented later, this table and the eventual Data Safety form must be updated to match.

---

## 8. Security Findings Summary

(Full detail in each `GP-##` entry above; this is a consolidated view for quick scanning.)

| Finding | Severity |
|---|---|
| GP-02 — Missing location permission | Critical |
| GP-04 — No secrets management for release signing | High |
| GP-17 — Confirmed precise-location exposure on the open job board | High |
| GP-13 — 24h tokens, no revocation/refresh | Medium |
| GP-14 — No admin MFA | Medium |
| GP-12 — In-memory rate limiting/dispatch state | Medium |

**Already resolved, earlier in this engagement (not re-flagged here):** insecure config fallback defaults (`config.py` now refuses to boot with placeholder secrets when `DEBUG=false`), dead/duplicate `routes/mechanic.py` removed, deprecated `@app.on_event` migrated to `lifespan`, HTTPS/TLS via Cloudflare with a real trusted certificate, origin IP no longer directly reachable, SSH restricted to known sources with a documented VPN-based recovery path.

**Not assessed in this pass (recommend a dedicated follow-up):** SQL injection / XSS / IDOR testing was not performed as a formal penetration test in this audit — the codebase uses SQLAlchemy's ORM (which parameterizes queries by default, reducing but not eliminating SQL injection risk) and the frontend's `escapeHtml()` helper is used for user-controlled content in most places I've reviewed across this engagement, but a dedicated security review pass (Section 21's `docs/security-review.md`) should verify this systematically rather than relying on spot-checks accumulated across unrelated work.

---

## 9. Prioritized Implementation Plan

Ordered by what actually blocks submission first, then by risk.

### Must fix before any Play Store submission attempt
1. ✅ **GP-05 + GP-06** — RESOLVED. Privacy Policy + Terms & Conditions (content + real, always-reachable pages + acceptance tracking at registration). Still needs your review of the actual legal content before treating it as final.
2. ✅ **GP-07** — RESOLVED. Account deletion, in-app and web (anonymize policy).
3. ✅ **GP-08** — RESOLVED. Reporting + blocking + admin moderation queue.
4. ✅ **GP-02** — RESOLVED. Location permission fix.
5. ✅ **GP-01** — RESOLVED. Package ID decided and corrected.
6. ✅ **GP-03 + GP-04** — RESOLVED (code + CI workflow + docs). Release signing, `.aab` builds, secrets management. **You still need to do the one-time key generation yourself** — see `docs/release-signing.md` — and I was not able to actually run a Gradle build in this sandbox to verify the config end-to-end, so please test `bundleRelease` locally before your first real submission.

**All "must fix" items are now resolved or code-complete.** What's left before you can actually submit: your review of the legal content (GP-05/06), running the Alembic migrations against production (GP-06's operational note), generating the real release keystores and testing a signed build (GP-03/04 above), and working through the remaining Section 9/10/21 items below at your own pace.

### Should fix before submission (policy alignment / correctness, not hard blockers)
7. ✅ **GP-17** — RESOLVED. Exact job coordinates no longer exposed pre-acceptance.
8. ✅ **GP-16** — RESOLVED. False "providers are verified" claim corrected.
9. ✅ **GP-10** — RESOLVED. Payment-fee claim corrected; launching fee-free.
10. ✅ **GP-20** — RESOLVED (found during this pass). Dead footer links fixed.

### Recommended, not blocking
10. GP-09 (push notifications), GP-13 (token revocation), GP-14 (admin MFA), GP-12 (Redis-backed rate limiting), GP-15 (crash reporting), GP-19 (staging environment)

### Documentation (Section 21), produced alongside the corresponding work above rather than upfront
- `docs/privacy-data-inventory.md` — expand Section 5 above once GP-05 is underway
- `docs/android-permissions.md` — expand Section 6 above once GP-02 is fixed
- `docs/role-access-matrix.md` — needs a dedicated pass through every route's `Depends(require_*)` guard (not done in this audit)
- `docs/moderation-process.md` — write alongside GP-08
- `docs/account-deletion-process.md` — write alongside GP-07
- `docs/reviewer-instructions.md` + reviewer test accounts — last, once the above are functional
- `docs/release-checklist.md`, `docs/security-review.md`, `docs/production-runbook.md` — write once there's an actual release process and runbook procedures to document

---

## 10. Decisions Needed From the Lever Owner

These cannot be resolved by implementation alone — they need your judgment:

1. **Final Android package ID** (GP-01): keep `com.lever.app` for the client (matches what's already built) and update docs to match, or rename to `com.lever.client` and accept the one-time mechanical change? Either is fine technically; it just needs to be decided once and be permanent.
2. **Data retention on account deletion** (GP-07): for each data type in Section 5, should it be hard-deleted or anonymized on account deletion? In particular: messages where the *other* party still has an active job, reviews (deleting could corrupt a provider's rating history), and any data tied to an open dispute.
3. **Privacy Policy / Terms content** (GP-05, GP-06): I can draft technically-accurate first drafts once you confirm the business facts (what data is actually shared with whom, retention periods, your business contact/registered address for the policy, whether you want LOPD-specific language reviewed by an Ecuador-licensed lawyer before publishing — I'd recommend that step given real legal exposure).
4. **Provider verification claim** (GP-16): is real identity/background verification for providers planned before launch, or should the landing page copy be corrected to not claim it in the meantime?
5. **Payment model** (GP-10): is the $0.05 scheduling fee still the intended model? Should payment processing be built before launch, or should Lever launch v1 as a pure connection/matching service (no payment facilitation) with the copy corrected accordingly?
6. **Moderation staffing** (GP-08): once a reporting/moderation queue exists, who reviews it? This affects whether the admin UI needs a lightweight single-admin queue or a more structured multi-moderator workflow with role separation (Section 8 of the requirements mentions a `moderator`/`support agent` role distinct from full admin — worth deciding now rather than retrofitting).
7. **Launch timeline vs. scope**: several items above (push notifications, admin MFA, staging environment, real payments) are recommended but don't block submission. Given the current user base is 5 clients and 0 providers, is the goal a fast, narrower first submission (blockers only) with the "should fix" and "recommended" items following in updates, or a more complete v1 before ever submitting?

---

## What This Document Does Not Yet Cover

Per the phased approach requested, this is the Phase 1 audit only. Not yet produced: the remaining 9 documents from Section 21, the authorization matrix (Section 8 of the requirements — needs a dedicated route-by-route pass), reviewer test accounts (Section 15), and the store listing content (Section 16). These follow once the blocking items above are resolved, per the prioritized plan in Section 9.
