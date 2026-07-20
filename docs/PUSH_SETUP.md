# Push notifications (FCM) — activation guide

The code ships **inert**: with no Firebase credentials, `send_push()` is a
no-op and the app behaves exactly as today (in-app notifications + polling).
Follow these steps once to make offers reach a **closed** provider app.

## What's already built (no action needed)

- `device_tokens` table + `POST /api/devices/register` / `unregister`
- `push.py` — FCM HTTP v1 sender (loads the service account, prunes dead tokens)
- Job **offers** already call `send_push` (dispatch.py `offer_to_provider`)
- The apps register their token on login (`registerPushForUser`, native-only,
  guarded so it no-ops until the Capacitor plugin is present)
- `google-auth` is in requirements.txt

## Backend (you)

1. In the [Firebase console](https://console.firebase.google.com/): create a
   project (or reuse one), then **Project settings → Service accounts →
   Generate new private key**. This downloads a JSON file.
2. Put that JSON on the VPS, readable only by the app user, e.g.
   `/opt/lever-new/secrets/fcm-service-account.json` (chmod 600).
3. Add to `deploy/.env.prod`:
   ```
   FCM_CREDENTIALS_PATH=/opt/lever-new/secrets/fcm-service-account.json
   ```
   and mount that path into the container (add to the app service in
   `docker-compose.prod.yml`):
   ```yaml
   volumes:
     - /opt/lever-new/secrets:/opt/lever-new/secrets:ro
   ```
4. Redeploy. On boot the log shows `Push: FCM credentials loaded for project …`.
   Nothing else changes if the file is absent or invalid — push just stays off.

## Android apps (you — one-time, in the Capacitor project)

1. In Firebase, add an **Android app** for each package: `com.lever.app`
   (client) and `com.lever.provider` (provider). Download each
   `google-services.json` into the respective Android project
   (`android/app/`).
2. Add the Capacitor push plugin and rebuild:
   ```
   npm install @capacitor/push-notifications
   npx cap sync android
   ```
   (Add the Google Services Gradle plugin per Capacitor's FCM guide.)
3. The web layer already calls `PushNotifications.register()` on login and
   `POST /api/devices/register` with the returned token — no JS changes needed.

## Verify

- Log into the provider app on a real device → a `device_tokens` row appears
  for that user.
- Close the app, create a matching client request → the offer arrives as a
  system notification. Tapping it deep-links to the board.

## After push is live

- Tighten `DISPATCH_OFFER_SECONDS` from 90 toward 30–45 (offers now reach
  closed apps, so the window no longer needs to cover "app happens to be open").
- Extend push to more events if desired (cancellations, extra-time approvals):
  add a `send_push(...)` call next to those `Notification(...)` sites — same
  pattern as `offer_to_provider`.
