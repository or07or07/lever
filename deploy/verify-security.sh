#!/bin/bash
# =============================================================================
# Lever — Post-Deploy Security Verification
#
# Checks all security headers, TLS config, and hardening measures.
# Run after deployment to verify everything is properly configured.
#
# Usage:
#   bash deploy/verify-security.sh lever.yourdomain.com
# =============================================================================

set -euo pipefail

DOMAIN="${1:-}"
if [[ -z "$DOMAIN" ]]; then
    echo "Usage: verify-security.sh YOUR_DOMAIN"
    echo "Example: verify-security.sh lever.test-test-now.com"
    exit 1
fi

PASS=0
WARN=0
FAIL=0

pass() { echo -e "\033[0;32m  ✓ PASS\033[0m  $1"; ((PASS++)); }
warn() { echo -e "\033[1;33m  ⚠ WARN\033[0m  $1"; ((WARN++)); }
fail() { echo -e "\033[0;31m  ✗ FAIL\033[0m  $1"; ((FAIL++)); }

echo ""
echo "============================================="
echo " Lever Security Audit: $DOMAIN"
echo "============================================="
echo ""

# ── 1. HTTPS Connectivity ──
echo "─── TLS / HTTPS ───"

HTTPS_CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://$DOMAIN/health" 2>/dev/null || echo "000")
if [[ "$HTTPS_CODE" == "200" ]]; then
    pass "HTTPS responds: 200 OK"
else
    fail "HTTPS health check: $HTTPS_CODE"
fi

# ── 2. HTTP → HTTPS Redirect ──
HTTP_CODE=$(curl -s -o /dev/null -w '%{http_code}' -L --max-redirs 0 "http://$DOMAIN/" 2>/dev/null || echo "000")
if [[ "$HTTP_CODE" == "301" ]]; then
    pass "HTTP → HTTPS redirect: 301 Moved Permanently"
elif [[ "$HTTP_CODE" == "302" ]]; then
    warn "HTTP → HTTPS redirect: 302 (should be 301 for permanent)"
else
    fail "HTTP → HTTPS redirect not working: $HTTP_CODE"
fi

# ── 3. TLS Version ──
TLS_VERSION=$(curl -sk -o /dev/null -w '%{ssl_version}' "https://$DOMAIN/" 2>/dev/null || echo "")
if [[ "$TLS_VERSION" == "TLSv1.3" ]]; then
    pass "TLS version: $TLS_VERSION (best)"
elif [[ "$TLS_VERSION" == "TLSv1.2" ]]; then
    pass "TLS version: $TLS_VERSION (acceptable)"
else
    fail "TLS version: $TLS_VERSION (expected 1.2 or 1.3)"
fi

# ── 4. Certificate expiry ──
CERT_EXPIRY=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || echo "")
if [[ -n "$CERT_EXPIRY" ]]; then
    EXPIRY_EPOCH=$(date -d "$CERT_EXPIRY" +%s 2>/dev/null || date -jf "%b %d %T %Y %Z" "$CERT_EXPIRY" +%s 2>/dev/null || echo "0")
    NOW_EPOCH=$(date +%s)
    DAYS_LEFT=$(( (EXPIRY_EPOCH - NOW_EPOCH) / 86400 ))
    if [[ $DAYS_LEFT -gt 30 ]]; then
        pass "Certificate expires in $DAYS_LEFT days ($CERT_EXPIRY)"
    elif [[ $DAYS_LEFT -gt 7 ]]; then
        warn "Certificate expires in $DAYS_LEFT days — renewal needed soon"
    else
        fail "Certificate expires in $DAYS_LEFT days — CRITICAL"
    fi
else
    fail "Could not check certificate expiry"
fi

# ── 5. Security Headers ──
echo ""
echo "─── Security Headers ───"

HEADERS=$(curl -sk -I "https://$DOMAIN/" 2>/dev/null || echo "")

check_header() {
    local name="$1"
    local expected="$2"
    if echo "$HEADERS" | grep -qi "$name"; then
        local value=$(echo "$HEADERS" | grep -i "$name" | head -1 | cut -d: -f2- | xargs)
        if [[ -n "$expected" ]] && ! echo "$value" | grep -qi "$expected"; then
            warn "$name present but unexpected value"
        else
            pass "$name: $value"
        fi
    else
        fail "$name: MISSING"
    fi
}

check_header "Strict-Transport-Security" "max-age="
check_header "X-Frame-Options" "DENY"
check_header "X-Content-Type-Options" "nosniff"
check_header "Content-Security-Policy" "default-src"
check_header "Referrer-Policy" ""
check_header "Permissions-Policy" "geolocation"
check_header "Cross-Origin-Opener-Policy" ""
check_header "X-Request-ID" ""

# Check server header is NOT leaking version
if echo "$HEADERS" | grep -qi "^server:.*nginx/"; then
    fail "Server header leaks nginx version"
elif echo "$HEADERS" | grep -qi "^server:.*uvicorn"; then
    fail "Server header leaks uvicorn"
else
    pass "Server version not leaked"
fi

# ── 6. WebSocket endpoints ──
echo ""
echo "─── WebSocket Support ───"

# Check that WS upgrade path exists (won't actually upgrade without proper auth)
WS_CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://$DOMAIN/ws/" 2>/dev/null || echo "000")
if [[ "$WS_CODE" != "000" ]]; then
    pass "WebSocket path /ws/ reachable (code: $WS_CODE)"
else
    warn "WebSocket path /ws/ not reachable"
fi

# ── 7. Common attack paths blocked ──
echo ""
echo "─── Attack Surface ───"

for path in "/.env" "/wp-admin/" "/phpmyadmin" "/.git/HEAD" "/xmlrpc.php"; do
    CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://$DOMAIN$path" 2>/dev/null || echo "000")
    if [[ "$CODE" == "404" || "$CODE" == "403" ]]; then
        pass "Blocked: $path ($CODE)"
    elif [[ "$CODE" == "200" ]]; then
        fail "EXPOSED: $path returns 200"
    else
        pass "Protected: $path ($CODE)"
    fi
done

# ── 8. API docs exposure ──
echo ""
echo "─── API Docs ───"

DOCS_CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://$DOMAIN/docs" 2>/dev/null || echo "000")
if [[ "$DOCS_CODE" == "200" ]]; then
    warn "Swagger docs accessible at /docs (consider blocking in production)"
elif [[ "$DOCS_CODE" == "404" ]]; then
    pass "Swagger docs blocked in production"
else
    pass "Swagger docs: $DOCS_CODE"
fi

REDOC_CODE=$(curl -sk -o /dev/null -w '%{http_code}' "https://$DOMAIN/redoc" 2>/dev/null || echo "000")
if [[ "$REDOC_CODE" == "200" ]]; then
    warn "ReDoc accessible at /redoc (consider blocking in production)"
elif [[ "$REDOC_CODE" == "404" ]]; then
    pass "ReDoc blocked in production"
else
    pass "ReDoc: $REDOC_CODE"
fi

# ── Results ──
echo ""
echo "============================================="
TOTAL=$((PASS + WARN + FAIL))
echo -e " Results: \033[0;32m$PASS passed\033[0m, \033[1;33m$WARN warnings\033[0m, \033[0;31m$FAIL failed\033[0m (out of $TOTAL checks)"

if [[ $FAIL -eq 0 && $WARN -eq 0 ]]; then
    echo -e " \033[0;32mAll security checks passed.\033[0m"
elif [[ $FAIL -eq 0 ]]; then
    echo -e " \033[1;33mNo critical failures. Review warnings above.\033[0m"
else
    echo -e " \033[0;31mCritical security issues found. Fix before going live.\033[0m"
fi
echo "============================================="
echo ""
