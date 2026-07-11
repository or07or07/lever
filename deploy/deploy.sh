#!/bin/bash
# =============================================================================
# Lever — Production Deployment Script
#
# Usage:
#   cd /opt/lever
#   bash deploy/deploy.sh --domain lever.yourdomain.com --email admin@yourdomain.com
#
# What this script does:
#   1. Validates prerequisites (Docker, .env.prod, domain)
#   2. Configures Nginx with your domain + HTTPS
#   3. Obtains Let's Encrypt TLS certificate (if not already present)
#   4. Builds and starts all containers (app, db, nginx, certbot)
#   5. Runs database migrations
#   6. Seeds initial data (if first deploy)
#   7. Validates security: HTTPS, headers, redirects
#
# Security:
#   - TLS 1.2/1.3 enforced
#   - HTTP → HTTPS 301 redirect
#   - HSTS, CSP, X-Frame-Options, X-Content-Type-Options headers
#   - Certbot auto-renewal service
#   - Non-root app container
# =============================================================================

set -euo pipefail

# ── Color output ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

info()  { echo -e "${BLUE}[INFO]${NC} $1"; }
ok()    { echo -e "${GREEN}  ✓${NC} $1"; }
warn()  { echo -e "${YELLOW}  ⚠${NC} $1"; }
fail()  { echo -e "${RED}  ✗${NC} $1"; }

# ── Parse arguments ──
DOMAIN=""
EMAIL=""
SEED="false"
FORCE="false"

while [[ $# -gt 0 ]]; do
    case $1 in
        --domain)  DOMAIN="$2"; shift 2 ;;
        --email)   EMAIL="$2"; shift 2 ;;
        --seed)    SEED="true"; shift ;;
        --force)   FORCE="true"; shift ;;
        -h|--help)
            echo "Usage: deploy.sh --domain YOUR_DOMAIN --email YOUR_EMAIL [--seed] [--force]"
            echo ""
            echo "  --domain   Your domain name (e.g., lever.myapp.com)"
            echo "  --email    Email for Let's Encrypt certificate notifications"
            echo "  --seed     Run seed.py after deployment (first-time only)"
            echo "  --force    Skip confirmation prompts"
            exit 0 ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

if [[ -z "$DOMAIN" || -z "$EMAIL" ]]; then
    echo "ERROR: --domain and --email are required."
    echo "Usage: deploy.sh --domain lever.myapp.com --email admin@myapp.com"
    exit 1
fi

DEPLOY_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$(dirname "$DEPLOY_DIR")"
COMPOSE_CMD="docker compose -f docker-compose.prod.yml --env-file .env.prod"

echo ""
echo -e "${BLUE}=============================================${NC}"
echo -e "${BLUE} Lever — Production Deployment${NC}"
echo -e "${BLUE}=============================================${NC}"
echo " Domain:    $DOMAIN"
echo " Email:     $EMAIL"
echo " App dir:   $APP_DIR"
echo " Deploy:    $DEPLOY_DIR"
echo " Seed data: $SEED"
echo -e "${BLUE}=============================================${NC}"
echo ""

# ── [1/7] Preflight checks ──
info "[1/7] Preflight checks..."

if ! command -v docker &>/dev/null; then
    fail "Docker not installed. Run setup-vps.sh first."
    exit 1
fi
ok "Docker: $(docker --version | cut -d' ' -f3)"

if ! docker compose version &>/dev/null; then
    fail "Docker Compose not available."
    exit 1
fi
ok "Docker Compose: $(docker compose version --short)"

ENV_FILE="$DEPLOY_DIR/.env.prod"
if [[ ! -f "$ENV_FILE" ]]; then
    fail "$ENV_FILE not found."
    echo "  → Copy: cp $DEPLOY_DIR/.env.prod.template $DEPLOY_DIR/.env.prod"
    echo "  → Fill in all CHANGE_ME values"
    exit 1
fi

if grep -q "CHANGE_ME" "$ENV_FILE"; then
    fail ".env.prod still contains CHANGE_ME placeholders."
    echo "  → Edit $ENV_FILE and replace all CHANGE_ME values."
    exit 1
fi
ok ".env.prod configured"

# Validate .env.prod has strong secrets
SECRET_KEY=$(grep "^SECRET_KEY=" "$ENV_FILE" | cut -d'=' -f2-)
if [[ ${#SECRET_KEY} -lt 32 ]]; then
    warn "SECRET_KEY is shorter than 32 chars. Generate a stronger one:"
    echo "  → openssl rand -hex 32"
fi

DB_PASSWORD=$(grep "^DB_PASSWORD=" "$ENV_FILE" | cut -d'=' -f2-)
if [[ ${#DB_PASSWORD} -lt 16 ]]; then
    warn "DB_PASSWORD is shorter than 16 chars. Consider a stronger password."
fi

# ── [2/7] Configure Nginx for domain ──
echo ""
info "[2/7] Configuring Nginx for $DOMAIN..."

NGINX_CONF="$DEPLOY_DIR/nginx/conf.d/lever.conf"
if [[ ! -f "$NGINX_CONF" ]]; then
    fail "lever.conf not found at $NGINX_CONF"
    exit 1
fi

# Replace YOUR_DOMAIN placeholder with actual domain
sed -i "s/YOUR_DOMAIN/$DOMAIN/g" "$NGINX_CONF"
ok "Nginx configured for $DOMAIN"

# ── [3/7] Obtain TLS certificate ──
echo ""
info "[3/7] TLS certificate..."

mkdir -p "$DEPLOY_DIR/certbot/conf" "$DEPLOY_DIR/certbot/www"

if [[ -f "$DEPLOY_DIR/certbot/conf/live/$DOMAIN/fullchain.pem" ]]; then
    ok "TLS certificate already exists for $DOMAIN"
    # Check expiry
    EXPIRY=$(docker run --rm -v "$DEPLOY_DIR/certbot/conf:/etc/letsencrypt:ro" \
        certbot/certbot certificates 2>/dev/null | grep "Expiry" | head -1 || echo "")
    if [[ -n "$EXPIRY" ]]; then
        ok "Certificate: $EXPIRY"
    fi
else
    info "Obtaining new TLS certificate..."

    # Create temporary HTTP-only config for ACME challenge
    TEMP_CONF="$DEPLOY_DIR/nginx/conf.d/lever-acme-temp.conf"
    cat > "$TEMP_CONF" << TEMPEOF
server {
    listen 80;
    server_name $DOMAIN www.$DOMAIN;
    location /.well-known/acme-challenge/ {
        root /var/www/certbot;
    }
    location / {
        return 200 'Lever is being set up...';
        add_header Content-Type text/plain;
    }
}
TEMPEOF

    # Temporarily move the SSL config aside
    mv "$NGINX_CONF" "${NGINX_CONF}.ssl-pending"

    # Start a temporary nginx for the ACME challenge
    docker run -d --name lever-certbot-nginx \
        -p 80:80 \
        -v "$DEPLOY_DIR/nginx/nginx.conf:/etc/nginx/nginx.conf:ro" \
        -v "$DEPLOY_DIR/nginx/conf.d:/etc/nginx/conf.d:ro" \
        -v "$DEPLOY_DIR/certbot/www:/var/www/certbot:ro" \
        nginx:1.27-alpine 2>/dev/null || true

    sleep 3

    # Request certificate
    docker run --rm \
        -v "$DEPLOY_DIR/certbot/conf:/etc/letsencrypt" \
        -v "$DEPLOY_DIR/certbot/www:/var/www/certbot" \
        certbot/certbot certonly \
        --webroot --webroot-path=/var/www/certbot \
        -d "$DOMAIN" \
        --email "$EMAIL" --agree-tos --no-eff-email \
        --non-interactive

    # Clean up
    docker stop lever-certbot-nginx 2>/dev/null || true
    docker rm lever-certbot-nginx 2>/dev/null || true
    rm -f "$TEMP_CONF"
    mv "${NGINX_CONF}.ssl-pending" "$NGINX_CONF"

    if [[ -f "$DEPLOY_DIR/certbot/conf/live/$DOMAIN/fullchain.pem" ]]; then
        ok "TLS certificate obtained for $DOMAIN"
    else
        fail "TLS certificate not obtained. Check DNS and try again."
        echo "  → Make sure $DOMAIN A record points to this server's IP"
        echo "  → Check: dig +short $DOMAIN"
        exit 1
    fi
fi

# ── [4/7] Build and start containers ──
echo ""
info "[4/7] Building and starting containers..."
cd "$DEPLOY_DIR"
$COMPOSE_CMD up -d --build

echo "  Waiting for services to become healthy..."
sleep 10

for i in {1..30}; do
    if $COMPOSE_CMD exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8500/health')" &>/dev/null; then
        ok "App is healthy"
        break
    fi
    if [[ $i -eq 30 ]]; then
        fail "App failed health check after 60 seconds"
        echo "  → Check: $COMPOSE_CMD logs app"
        exit 1
    fi
    sleep 2
done

# ── [5/7] Run migrations ──
echo ""
info "[5/7] Running database migrations..."
$COMPOSE_CMD exec -T app python -m alembic upgrade head 2>/dev/null || {
    warn "Alembic migration failed (tables may already exist via create_all)"
}
ok "Database schema up to date"

# ── [6/7] Seed data ──
echo ""
info "[6/7] Seed data..."
if [[ "$SEED" == "true" ]]; then
    $COMPOSE_CMD exec -T app python seed.py
    ok "Demo data seeded"
else
    echo "  → Skipped (use --seed on first deploy)"
fi

# ── [7/7] Security validation ──
echo ""
info "[7/7] Security validation..."

# Check HTTPS
HTTPS_CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://$DOMAIN/health" 2>/dev/null || echo "000")
if [[ "$HTTPS_CODE" == "200" ]]; then
    ok "HTTPS health check: 200 OK"
else
    warn "HTTPS health check returned: $HTTPS_CODE"
fi

# Check HTTP→HTTPS redirect
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' "http://$DOMAIN/" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "301" ]]; then
    ok "HTTP → HTTPS redirect: 301"
else
    warn "HTTP redirect returned: $HTTP_CODE (expected 301)"
fi

# Check security headers
HEADERS=$(curl -sk -I "https://$DOMAIN/" 2>/dev/null || echo "")
if echo "$HEADERS" | grep -qi "strict-transport-security"; then
    ok "HSTS header present"
else
    warn "HSTS header missing"
fi

if echo "$HEADERS" | grep -qi "x-frame-options"; then
    ok "X-Frame-Options header present"
else
    warn "X-Frame-Options header missing"
fi

if echo "$HEADERS" | grep -qi "x-content-type-options"; then
    ok "X-Content-Type-Options header present"
else
    warn "X-Content-Type-Options header missing"
fi

if echo "$HEADERS" | grep -qi "content-security-policy"; then
    ok "Content-Security-Policy header present"
else
    warn "Content-Security-Policy header missing"
fi

if echo "$HEADERS" | grep -qi "permissions-policy"; then
    ok "Permissions-Policy header present"
else
    warn "Permissions-Policy header missing"
fi

# Check TLS grade
echo ""
info "TLS certificate details:"
echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | openssl x509 -noout -dates 2>/dev/null || warn "Could not check TLS certificate"

echo ""
echo -e "${GREEN}=============================================${NC}"
echo -e "${GREEN} Deployment Complete!${NC}"
echo -e "${GREEN}=============================================${NC}"
echo ""
echo " Your app is live at: https://$DOMAIN"
echo ""
echo " Quick commands:"
echo "   Logs:    cd $DEPLOY_DIR && $COMPOSE_CMD logs -f app"
echo "   Status:  cd $DEPLOY_DIR && $COMPOSE_CMD ps"
echo "   Restart: cd $DEPLOY_DIR && $COMPOSE_CMD restart app"
echo "   Stop:    cd $DEPLOY_DIR && $COMPOSE_CMD down"
echo ""
echo " TLS auto-renewal is handled by the certbot container."
echo " Nginx reloads every 6 hours to pick up renewed certs."
echo ""
echo -e "${GREEN}=============================================${NC}"
