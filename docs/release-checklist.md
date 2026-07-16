# Lever — Release checklist (how a change reaches each surface)

Lever is **one codebase** ([frontend/index.html](../frontend/index.html)) packaged four ways.
This doc keeps the release tracks cleanly separated so a change goes only where you
intend it to.

```
             edit code ─► commit ─► push to main (GitHub)
                                   │
   ┌──────────────┬────────────────┼─────────────────┬──────────────────┐
   ▼              ▼                ▼                 ▼                  ▼
 BACKEND        WEB APP        TEST APK          CLIENT APP         PROVIDER APP
 (API)          (browser/PWA)  (debug, phone)    (Play prod)        (Play prod)
 deploy VPS     deploy VPS     auto: GitHub      rebuild + Play     rebuild + Play
 → all          → instant*     Release           review             review
 surfaces                       (test-latest)
```

\* Web: instant for new visitors; returning PWA users are one reload behind because
of the service worker's stale-while-revalidate cache (bump `CACHE_NAME` in
[sw.js](../frontend/sw.js) to force-refresh everyone).

---

## Track 0 — Backend / API change

Affects every surface at once (all shells call the same API). No app rebuild.

```bash
cd /opt/lever-new && sudo git pull origin main
cd deploy && sudo docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build app
```
- [ ] Migrations run if models changed: the deploy runs `alembic upgrade head` (confirm it succeeded — `create_all()` does **not** add columns to existing tables).
- [ ] `curl -s -o /dev/null -w "%{http_code}\n" https://lever-ec.com/health` → 200.

## Track 1 — Web app (browser + installed PWA)

Same VPS deploy as Track 0 (frontend is served by the app container).
- [ ] After deploy, hard-reload `lever-ec.com` on a phone and desktop.
- [ ] If a change **must** reach existing PWA users immediately, bump `CACHE_NAME`
      in [sw.js](../frontend/sw.js) (`lever-shell-v1` → `-v2`) before deploying.

## Track 2 — Test APK (debug build for on-device testing) ⭐ the fast test loop

Automatic. Every push to `main` rebuilds both **debug** APKs and publishes them to
the rolling **`test-latest`** GitHub pre-release (workflow:
[android-build.yml](../.github/workflows/android-build.yml)).

**Stable download links (bookmark on your phone):**
- Client: `https://github.com/or07or07/lever/releases/download/test-latest/lever-client-debug.apk`
- Provider: `https://github.com/or07or07/lever/releases/download/test-latest/lever-provider-debug.apk`

Install on the phone:
1. Open the link in the phone browser → download the `.apk`.
2. First time only: allow the browser to "install unknown apps" when prompted.
3. Tap the downloaded file → install. Later builds install **over** the old one
   (same debug signing key), so you keep your login — no uninstall needed.

Notes:
- These are **debug** builds — no Play review, not for real users.
- They talk to the **production** backend (`https://lever-ec.com`), so test actions
  write real data. (A separate staging backend is the open GP-19 item.)
- If Ecuador-only geo-blocking is enabled, test from an Ecuador connection.
- If you ever see "App not installed" on update, the CI signing cache was evicted —
  uninstall once and reinstall; future updates are seamless again.

## Track 3 — Client app to Play (`com.lever.app`) — production

- [ ] `cd apps/client && npx cap copy android` (bundle current frontend).
- [ ] Bump `versionCode` (+ `versionName`) in
      [apps/client/android/app/build.gradle](../apps/client/android/app/build.gradle) — Play rejects a reused `versionCode`.
- [ ] Build the **signed** `.aab`: run [android-release.yml](../.github/workflows/android-release.yml)
      (or `./gradlew bundleRelease`). **Requires the release keystore** (see
      [release-signing.md](release-signing.md)) — the one open prerequisite.
- [ ] Upload `.aab` to the Play Console (client listing) → review → staged rollout.
- [ ] Data Safety / permissions accurate for anything new (e.g. location, camera).

## Track 4 — Provider app to Play (`com.lever.provider`) — production

Same as Track 3, but a **separate** project, **separate** keystore, **separate**
Play listing, and its own `versionCode`. The release workflow builds both apps, so
they usually ship together.

---

## Which track does my change need?

| Change | Backend | Web | Test APK | Play (both apps) |
|---|---|---|---|---|
| API / model / route only | ✅ deploy | — (already covered) | — | — |
| Frontend (UI, copy, flow) | — | ✅ deploy | ✅ auto | ✅ next release |
| Native (permission, plugin, app config) | — | — | ✅ auto | ✅ next release |

Rule of thumb: **deploy the VPS** and your website + API are current for everyone;
the **installed apps** only change when you cut a new build (test APK automatically,
Play release deliberately).

---

## One-time prerequisites still open
- [ ] Generate the two **release** keystores (client + provider) — blocks Track 3/4.
      See [release-signing.md](release-signing.md).
- [ ] First run of [android-build.yml](../.github/workflows/android-build.yml) after
      this change — confirm it builds green and the `test-latest` release appears.
