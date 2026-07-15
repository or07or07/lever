# Cloudflare Origin Certificate → "Full (strict)" mode

This replaces the self-signed origin cert (the temporary fix from the July 2026
outage) with a **Cloudflare Origin Certificate**: a 15-year cert that Cloudflare
issues for the origin, with **no renewal** and no dependency on Let's Encrypt /
certbot (whose renewals were failing because outbound 443 is blocked by
DOCKER-USER). Once installed you switch Cloudflare to **Full (strict)**, which
verifies the origin cert instead of accepting any cert.

Background: Cloudflare terminates real public TLS with its own edge certificate.
The origin cert is only presented on the Cloudflare→origin hop. An Origin Cert is
trusted by Cloudflare specifically, so "Full (strict)" works; it is **not** a
publicly trusted CA cert and must never be the public-facing certificate.

---

## Part A — Generate the cert (Cloudflare dashboard)

1. Cloudflare dashboard → select the **lever-ec.com** zone.
2. **SSL/TLS → Origin Server → Create Certificate**.
3. Leave "Generate private key and CSR with Cloudflare" selected. Key type **RSA (2048)**.
4. Hostnames: `lever-ec.com` and `*.lever-ec.com` (Cloudflare pre-fills these).
5. Certificate Validity: **15 years**.
6. **Create**. You now see two text boxes:
   - **Origin Certificate** (PEM, starts `-----BEGIN CERTIFICATE-----`)
   - **Private Key** (PEM, starts `-----BEGIN PRIVATE KEY-----`)

⚠️ The **Private Key is shown only once.** Keep this browser tab open until Part B
is done and verified.

---

## Part B — Install on the VPS

The nginx container mounts `deploy/certbot/conf` → `/etc/letsencrypt` (read-only),
and `deploy/certbot/` is gitignored, so the key never enters version control.

```bash
cd /opt/lever-new/deploy
sudo mkdir -p certbot/conf/cloudflare-origin
```

Create the certificate file — paste the **Origin Certificate** box, then Ctrl-D:

```bash
sudo tee certbot/conf/cloudflare-origin/origin.pem > /dev/null
# paste the Origin Certificate PEM, then press Enter, then Ctrl-D
```

Create the key file — paste the **Private Key** box, then Ctrl-D:

```bash
sudo tee certbot/conf/cloudflare-origin/origin.key > /dev/null
# paste the Private Key PEM, then press Enter, then Ctrl-D
```

Lock down the private key:

```bash
sudo chmod 600 certbot/conf/cloudflare-origin/origin.key
sudo chmod 644 certbot/conf/cloudflare-origin/origin.pem
```

Sanity-check the two files are valid and match (same modulus hash):

```bash
sudo openssl x509 -in certbot/conf/cloudflare-origin/origin.pem -noout -subject -enddate
sudo openssl x509 -in certbot/conf/cloudflare-origin/origin.pem -noout -modulus | openssl md5
sudo openssl rsa  -in certbot/conf/cloudflare-origin/origin.key -noout -modulus | openssl md5
# the two md5 lines must be identical
```

---

## Part C — Point nginx at the Origin Cert (local edit first)

Do this as a **local edit on the server**, not via a repo pull. The repo stays on
the working self-signed cert until you have verified the Origin Cert live — that
way a `git pull` can never point nginx at a cert that isn't on disk yet (the
failure mode behind the July 2026 outage). Once verified, the repo is updated to
match (see Part F).

Point the two `ssl_certificate*` lines at the Origin Cert (in-container paths —
`certbot/conf` is mounted at `/etc/letsencrypt`):

```bash
cd /opt/lever-new
sudo sed -i \
  -e 's#ssl_certificate .*#ssl_certificate     /etc/letsencrypt/cloudflare-origin/origin.pem;#' \
  -e 's#ssl_certificate_key .*#ssl_certificate_key /etc/letsencrypt/cloudflare-origin/origin.key;#' \
  deploy/nginx/conf.d/lever.conf
cd deploy
docker compose -f docker-compose.prod.yml --env-file .env.prod exec nginx nginx -t   # validate BEFORE restart
docker compose -f docker-compose.prod.yml --env-file .env.prod restart nginx
```

**Do not restart if `nginx -t` fails** — that means the cert path or permissions
are wrong. Fix it first; the running nginx keeps serving on the old cert until a
successful restart. The self-signed cert is still on disk, so to revert just run
the same `sed` with the `live/selfsigned/*.pem` paths and restart.

---

## Part D — Switch Cloudflare to Full (strict)

Only after Part C verifies (site returns 200):

1. Cloudflare dashboard → **lever-ec.com → SSL/TLS → Overview**.
2. Change encryption mode from **Full** to **Full (strict)**.

---

## Part E — Verify

```bash
curl -sI https://lever-ec.com/health | head -1        # HTTP/2 200
```

Load the site in a browser — still green padlock (that's Cloudflare's edge cert,
unchanged). In **SSL/TLS → Overview** the mode reads **Full (strict)** with no
errors.

---

## Part F — Make it durable in the repo (after verifying)

Only once Parts C–E are confirmed working, update the repo so the committed
config matches the server and future pulls stay clean. Tell me it's verified and
I'll commit the two-line change; then on the server:

```bash
cd /opt/lever-new
sudo git stash        # set aside the local sed edit
sudo git pull origin main
sudo git stash drop   # the pulled version already has the origin paths
```

## Rollback

If anything breaks, revert the two `ssl_certificate*` lines to the self-signed
paths and `restart nginx`, and set Cloudflare back to **Full**:

```bash
cd /opt/lever-new
sudo sed -i \
  -e 's#ssl_certificate .*#ssl_certificate     /etc/letsencrypt/live/selfsigned/fullchain.pem;#' \
  -e 's#ssl_certificate_key .*#ssl_certificate_key /etc/letsencrypt/live/selfsigned/privkey.pem;#' \
  deploy/nginx/conf.d/lever.conf
cd deploy && docker compose -f docker-compose.prod.yml --env-file .env.prod restart nginx
```

## Renewal

None for 15 years. Set a calendar reminder a month before expiry (Cloudflare also
emails the account owner). No certbot, no cron, no outbound-443 dependency.
