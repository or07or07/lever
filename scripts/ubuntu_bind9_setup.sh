#!/usr/bin/env bash
# =============================================================================
#  ubuntu_bind9_setup.sh
#  Installs and configures BIND9 as a local LAN DNS server on Ubuntu
#
#  Zone:     mechfix.lab
#  Server:   10.0.23.25  (this machine — or07-ubuntu-srv-1)
#  Windows:  10.0.23.26  (win-dev)
#
#  Run as:   sudo bash ubuntu_bind9_setup.sh
# =============================================================================

set -euo pipefail

# ─── colours ────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}  $*"; }
info() { echo -e "${CYAN}[--]${NC}  $*"; }
warn() { echo -e "${YELLOW}[!!]${NC}  $*"; }
die()  { echo -e "${RED}[ERR]${NC} $*"; exit 1; }

# ─── config ─────────────────────────────────────────────────────────────────
ZONE="mechfix.lab"
SERVER_IP="10.0.23.25"
WINDOWS_IP="10.0.23.26"
REVERSE_NET="23.0.10"           # last-octet-reversed prefix for 10.0.23.x
SERIAL=$(date +%Y%m%d01)        # YYYYMMDDNN  — increment NN if updating same day

ZONE_DIR="/etc/bind"
ZONE_FILE="$ZONE_DIR/db.$ZONE"
REVERSE_FILE="$ZONE_DIR/db.$REVERSE_NET"

# ─── root check ─────────────────────────────────────────────────────────────
[[ $EUID -ne 0 ]] && die "Run with sudo: sudo bash $0"

echo
echo "═══════════════════════════════════════════════════════"
echo "  BIND9 Local DNS Setup — zone: $ZONE"
echo "═══════════════════════════════════════════════════════"
echo

# ─── 1. install ─────────────────────────────────────────────────────────────
info "Installing BIND9..."
apt-get update -qq
apt-get install -y bind9 bind9utils bind9-doc dnsutils > /dev/null
ok "BIND9 installed: $(named -v 2>&1 | head -1)"

# ─── 2. named.conf.options — forwarders + security ──────────────────────────
info "Writing named.conf.options..."
cat > "$ZONE_DIR/named.conf.options" <<EOF
options {
    directory "/var/cache/bind";

    // Forward external queries to public resolvers
    forwarders {
        8.8.8.8;        // Google
        8.8.4.4;
        1.1.1.1;        // Cloudflare
        1.0.0.1;
    };

    // Only accept recursive queries from the local LAN
    allow-recursion { 127.0.0.0/8; 10.0.23.0/24; };

    // Accept queries from LAN + loopback
    allow-query     { 127.0.0.0/8; 10.0.23.0/24; };

    // Allow zone transfers to nobody (single authoritative server)
    allow-transfer  { none; };

    dnssec-validation auto;

    listen-on       { any; };
    listen-on-v6    { any; };

    // Try forwarders first, fall back to full recursion if they fail
    forward first;
};
EOF
ok "named.conf.options written"

# ─── 3. named.conf.local — declare zones ────────────────────────────────────
info "Writing named.conf.local..."
cat > "$ZONE_DIR/named.conf.local" <<EOF
// ── Forward zone: $ZONE ──────────────────────────────────────────────────
zone "$ZONE" {
    type master;
    file "$ZONE_FILE";
};

// ── Reverse zone: 10.0.23.x ──────────────────────────────────────────────
zone "$REVERSE_NET.in-addr.arpa" {
    type master;
    file "$REVERSE_FILE";
};
EOF
ok "named.conf.local written"

# ─── 4. forward zone file ───────────────────────────────────────────────────
info "Writing forward zone file: $ZONE_FILE..."
cat > "$ZONE_FILE" <<EOF
\$ORIGIN $ZONE.
\$TTL 3600

; ── SOA ──────────────────────────────────────────────────────────────────────
@   IN  SOA   ns1.$ZONE. admin.$ZONE. (
                  $SERIAL   ; Serial   (YYYYMMDDNN)
                  3600       ; Refresh  (1 hour)
                  900        ; Retry    (15 min)
                  604800     ; Expire   (7 days)
                  300        ; Negative TTL (5 min)
              )

; ── Name servers ─────────────────────────────────────────────────────────────
@               IN  NS    ns1.$ZONE.

; ── A records ────────────────────────────────────────────────────────────────
ns1             IN  A     $SERVER_IP
ubuntu-srv-1    IN  A     $SERVER_IP
postgres        IN  A     $SERVER_IP      ; PostgreSQL alias
mechfix         IN  A     $SERVER_IP      ; app alias → same machine
win-dev         IN  A     $WINDOWS_IP

; ── CNAME aliases ────────────────────────────────────────────────────────────
db              IN  CNAME postgres.$ZONE.
EOF
ok "Forward zone written"

# ─── 5. reverse zone file ───────────────────────────────────────────────────
info "Writing reverse zone file: $REVERSE_FILE..."
cat > "$REVERSE_FILE" <<EOF
\$ORIGIN $REVERSE_NET.in-addr.arpa.
\$TTL 3600

; ── SOA ──────────────────────────────────────────────────────────────────────
@   IN  SOA   ns1.$ZONE. admin.$ZONE. (
                  $SERIAL
                  3600
                  900
                  604800
                  300
              )

; ── Name servers ─────────────────────────────────────────────────────────────
@               IN  NS    ns1.$ZONE.

; ── PTR records (last octet only) ────────────────────────────────────────────
25              IN  PTR   ubuntu-srv-1.$ZONE.
26              IN  PTR   win-dev.$ZONE.
EOF
ok "Reverse zone written"

# ─── 6. validate config ─────────────────────────────────────────────────────
info "Validating BIND config..."
named-checkconf "$ZONE_DIR/named.conf" && ok "named.conf syntax OK"
named-checkzone "$ZONE" "$ZONE_FILE"   && ok "Forward zone syntax OK"
named-checkzone "$REVERSE_NET.in-addr.arpa" "$REVERSE_FILE" && ok "Reverse zone syntax OK"

# ─── 7. UFW — open port 53 on LAN ───────────────────────────────────────────
if command -v ufw &>/dev/null; then
    info "Opening UFW port 53 (DNS) for LAN..."
    ufw allow from 10.0.23.0/24 to any port 53 proto tcp comment "BIND9 DNS TCP"
    ufw allow from 10.0.23.0/24 to any port 53 proto udp comment "BIND9 DNS UDP"
    ufw allow from 127.0.0.1    to any port 53 comment "BIND9 DNS loopback"
    ok "UFW rules added"
else
    warn "ufw not found — ensure port 53 TCP/UDP is open"
fi

# ─── 8. enable + restart BIND9 ──────────────────────────────────────────────
info "Enabling and starting BIND9..."
systemctl enable named --quiet
systemctl restart named
sleep 1

if systemctl is-active --quiet named; then
    ok "named is running"
else
    die "named failed to start — check: journalctl -u named -n 30"
fi

# ─── 9. local self-test ─────────────────────────────────────────────────────
echo
info "Running local resolution tests..."

test_dns() {
    local host="$1" expected="$2"
    local result
    result=$(dig @127.0.0.1 +short "$host" A 2>/dev/null | head -1)
    if [[ "$result" == "$expected" ]]; then
        ok "$host → $result"
    else
        warn "$host → got '$result', expected '$expected'"
    fi
}

test_dns "ubuntu-srv-1.$ZONE"  "$SERVER_IP"
test_dns "postgres.$ZONE"      "$SERVER_IP"
test_dns "mechfix.$ZONE"       "$SERVER_IP"
test_dns "win-dev.$ZONE"       "$WINDOWS_IP"

# PTR test
PTR_RESULT=$(dig @127.0.0.1 +short -x "$SERVER_IP" 2>/dev/null | head -1)
if [[ "$PTR_RESULT" == *"ubuntu-srv-1"* ]]; then
    ok "Reverse lookup $SERVER_IP → $PTR_RESULT"
else
    warn "Reverse lookup $SERVER_IP → got '$PTR_RESULT'"
fi

# External forwarding test
EXT=$(dig @127.0.0.1 +short google.com A 2>/dev/null | head -1)
if [[ -n "$EXT" ]]; then
    ok "External forwarding works: google.com → $EXT"
else
    warn "External forwarding may not be working"
fi

# ─── 10. summary ────────────────────────────────────────────────────────────
echo
echo "═══════════════════════════════════════════════════════"
echo -e "  ${GREEN}BIND9 DNS setup complete!${NC}"
echo "═══════════════════════════════════════════════════════"
echo
echo "  DNS server:  $SERVER_IP  (port 53)"
echo "  Zone:        $ZONE"
echo
echo "  Hosts registered:"
printf "    %-30s %s\n" "ubuntu-srv-1.$ZONE"  "$SERVER_IP"
printf "    %-30s %s\n" "postgres.$ZONE"      "$SERVER_IP"
printf "    %-30s %s\n" "mechfix.$ZONE"       "$SERVER_IP"
printf "    %-30s %s\n" "win-dev.$ZONE"       "$WINDOWS_IP"
echo
echo "  ┌─ To use this DNS on Windows ───────────────────────────────────────┐"
echo "  │  1. Open: Settings → Network → Ethernet → DNS server assignment   │"
echo "  │  2. Set Preferred DNS: $SERVER_IP                              │"
echo "  │  3. Alternate DNS:     8.8.8.8  (fallback)                        │"
echo "  │  OR run as Administrator:                                           │"
echo "  │     netsh interface ip set dns \"Ethernet\" static $SERVER_IP      │"
echo "  └────────────────────────────────────────────────────────────────────┘"
echo
echo "  Quick test from Windows:"
echo "    nslookup mechfix.mechfix.lab $SERVER_IP"
echo "    nslookup ubuntu-srv-1.mechfix.lab $SERVER_IP"
echo
