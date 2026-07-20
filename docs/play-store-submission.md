# Lever — Play Store submission guide

Signing infra is done ([release-signing.md](release-signing.md)) and both
apps build signed `.aab`s via [android-release.yml](../.github/workflows/android-release.yml).
This doc covers the **submission** itself: reviewer access, listing copy, and
the data-safety answers. Do it once per app (client `com.lever.app`,
provider `com.lever.provider`).

## ⚠️ Reviewer access — the #1 thing that will fail a review

Lever is **geo-restricted to Ecuador** (Cloudflare WAF rule — see the
Ecuador-geo-restriction note). Google reviews from outside Ecuador, so with
the rule on **the app looks broken to the reviewer** (blank/blocked) and gets
rejected.

- [ ] **Turn the Cloudflare EC-only WAF rule OFF before submitting**, and
      leave it off until the app is approved. Re-enable after approval if you
      still want the geo-gate (note: re-enabling can break future update
      reviews the same way — consider allowlisting Google's review egress or
      keeping it off for launch).
- [ ] In the Play Console, set **country availability to Ecuador** (and any
      neighbors you serve) rather than relying on the network block for geo.

## Pre-submit checklist

- [ ] Cloudflare EC restriction OFF (above).
- [ ] `versionCode` bumped in both `build.gradle`s (Play rejects a reused code).
- [ ] `cd apps/<app> && npx cap copy android` so the shipped bundle is current.
- [ ] Signed `.aab` built (run the release workflow with the keystore secrets).
- [ ] Privacy Policy + Terms URLs reachable (in-app + web — GP-05/06).
- [ ] Account deletion path works and is documented (GP-07) — Play requires an
      in-app **and** a web deletion route.
- [ ] If shipping push (FCM): `google-services.json` added per app and the
      push permission is declared (see [PUSH_SETUP.md](PUSH_SETUP.md)).
- [ ] Test account credentials provided in the review notes (a client login
      and, for the provider app, a provider login) so the reviewer can get past
      the sign-in gate.

## Data safety form (answer truthfully for each app)

Collected / linked to the user:
- **Personal**: name, email, phone.
- **Location**: approximate + precise (GPS live tracking during a job;
  provider location while online). Purpose: app functionality (matching,
  tracking). Not for ads.
- **App activity**: service requests, ratings/reviews.
- **Photos** (only if the service flow captures them).

Declare: data **encrypted in transit** (HTTPS/TLS), users can **request
deletion** (in-app + web). No data sold. No third-party ad SDKs.

## Store listing copy (draft — Spanish-first, Guayaquil)

**App title (≤30 chars)**
- Client: `Lever — Servicios a domicilio`
- Provider: `Lever Pro — Gana con tu oficio`

**Short description (≤80 chars)**
- Client: `Encuentra profesionales verificados en Guayaquil. Tú eliges por precio y reseñas.`
- Provider: `Recibe trabajos cerca de ti. Fija tu tarifa por hora. Sin comisiones.`

**Full description (client)**
```
Lever te conecta con profesionales de confianza en Guayaquil: plomería,
electricidad, limpieza, jardinería, mudanzas y más.

• Elige tú mismo — compara profesionales por su tarifa por hora, su
  calificación y sus trabajos verificados.
• Precio transparente — cada profesional fija su tarifa; el cobro se calcula
  por el tiempo trabajado y se mantiene dentro del rango acordado. Lever no
  cobra comisión.
• Seguridad — perfiles verificados, seguimiento en tiempo real del trabajo y
  reseñas después de cada servicio.
• Rápido — pide en segundos: elige el servicio, pon tu dirección y listo.

Disponible en Guayaquil, Ecuador.
```

**Full description (provider)**
```
Con Lever Pro recibes solicitudes de clientes cerca de ti y decides cuáles
tomar según cuánto vas a ganar.

• Tú fijas tu tarifa por hora — y recibes el 100%. Lever no cobra comisión.
• Trabajos claros — ves el pago estimado, la zona y la duración antes de
  aceptar.
• Tu reputación trabaja por ti — mientras más trabajos verificados y mejores
  reseñas, más oportunidades.
• Cobro por tiempo real — el trabajo se cronometra en la app; si se extiende,
  pides tiempo adicional y el cliente lo aprueba.

Para profesionales en Guayaquil, Ecuador.
```

> Honesty check: the copy above says each professional sets their price and
> Lever takes no commission — consistent with the worker-set pricing model
> (do **not** revert to "Lever fija el precio" language anywhere).

## After approval
- [ ] Re-decide the Cloudflare geo-gate (see reviewer-access note).
- [ ] Replace the placeholder landing testimonials with real ones (they are
      currently illustrative — fine pre-launch, but swap for genuine reviews).
- [ ] Staged rollout (e.g. 10% → 50% → 100%) to catch crashes early.
