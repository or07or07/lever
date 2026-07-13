# Release Signing — Lever Client & Provider Android Apps

Covers GP-03 (release keystores) and GP-04 (secrets management) from
[google-play-readiness.md](google-play-readiness.md). Two separate apps,
two separate keystores — `com.lever.app` (client) and `com.lever.provider`
are distinct Play Console listings and each needs its own upload key.

## Why this matters — read before generating anything

Google Play uses **Play App Signing**: you upload an `.aab` signed with
your own *upload key*, and Google re-signs it with an app signing key it
manages for you before distributing to devices. You still need the upload
key for every future release.

**If you lose the upload key and its password, you cannot publish updates
to that app listing anymore** without going through Google's account
recovery process, which takes days and isn't guaranteed. There is no
"forgot password" for this. Back the keystore file and its passwords up
somewhere durable (a password manager and a second physical/cloud backup)
the moment you generate it — not after.

## 1. Generate the two keystores (once, locally)

Requires a JDK (`keytool` ships with it). Run from anywhere safe — not
inside the git repo, so there's no risk of accidentally `git add`-ing it:

```bash
keytool -genkeypair -v -storetype PKCS12 \
  -keystore release-client.jks -alias lever-client \
  -keyalg RSA -keysize 2048 -validity 10000

keytool -genkeypair -v -storetype PKCS12 \
  -keystore release-provider.jks -alias lever-provider \
  -keyalg RSA -keysize 2048 -validity 10000
```

Each prompts for a store password, a key password, and identity details
(org name, etc. — these end up in the certificate, not user-facing
anywhere). Use a **different, strong, generated password** for each of
the four password prompts total. Save all of it in your password manager
immediately: which file goes with which alias, both passwords for each.

## 2. Local release builds (optional — for building `.aab`s on your own machine)

Copy the template next to itself and fill in real values — both are
gitignored, so this never risks a commit:

```bash
cp apps/client/android/keystore.properties.template   apps/client/android/keystore.properties
cp apps/provider/android/keystore.properties.template apps/provider/android/keystore.properties
```

Edit each `keystore.properties` to point `storeFile` at wherever you
actually put the `.jks` (an absolute path is simplest), and fill in the
real passwords/alias. Then:

```bash
cd apps/client/android   && ./gradlew bundleRelease
cd apps/provider/android && ./gradlew bundleRelease
```

Output lands at `app/build/outputs/bundle/release/app-release.aab`.

## 3. CI release builds (GitHub Actions)

`.github/workflows/android-release.yml` is manually triggered (Actions
tab → "Android Release" → "Run workflow") and builds+signs both apps'
`.aab`s without ever committing the keystores to the repo. It needs eight
repository secrets (Settings → Secrets and variables → Actions):

| Secret | Value |
|---|---|
| `ANDROID_CLIENT_KEYSTORE_BASE64` | `base64 -w0 release-client.jks` (see below) |
| `ANDROID_CLIENT_STORE_PASSWORD` | the client keystore's store password |
| `ANDROID_CLIENT_KEY_ALIAS` | `lever-client` (or whatever alias you used) |
| `ANDROID_CLIENT_KEY_PASSWORD` | the client keystore's key password |
| `ANDROID_PROVIDER_KEYSTORE_BASE64` | `base64 -w0 release-provider.jks` |
| `ANDROID_PROVIDER_STORE_PASSWORD` | the provider keystore's store password |
| `ANDROID_PROVIDER_KEY_ALIAS` | `lever-provider` (or whatever alias you used) |
| `ANDROID_PROVIDER_KEY_PASSWORD` | the provider keystore's key password |

To get the base64 value:

```bash
base64 -w0 release-client.jks   # macOS: base64 -i release-client.jks
```

Paste the output directly as the secret value — GitHub Actions secrets
are single opaque strings, this is the standard way to smuggle a binary
file through them. The workflow decodes it back to a file at build time,
in the runner's temp directory, and deletes it again once the build
finishes (`if: always()` cleanup step) — it's never written into the repo
checkout or the build artifact.

If any of the four secrets for an app are missing, that app's job fails
immediately with a clear error instead of silently producing an unsigned
(and therefore Play-Console-unusable) `.aab`.

## 4. What NOT to do

- Never commit a `.jks`/`.keystore` file or a filled-in `keystore.properties`
  — both are gitignored specifically to make this hard to do by accident,
  but double-check `git status` before pushing regardless.
- Never put the raw keystore passwords in `build.gradle`, workflow YAML, or
  any tracked file — they only ever exist as local `keystore.properties`
  (gitignored) or GitHub Actions secrets.
- Don't reuse the client app's keystore for the provider app or vice
  versa — Play Console will reject an upload signed with the wrong app's
  key anyway, but keeping them separate from the start avoids ever having
  to explain to Play support why they're tangled together.
