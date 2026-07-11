#!/usr/bin/env bash
# =============================================================================
# MechFix - Ubuntu PostgreSQL Setup Script
# =============================================================================
# Run this on your Ubuntu server (10.0.23.25) as a user with sudo privileges.
#
# Usage:
#   chmod +x ubuntu_postgres_setup.sh
#   sudo ./ubuntu_postgres_setup.sh
#
# What this does:
#   1. Installs PostgreSQL 15
#   2. Creates the mechfix database and user
#   3. Configures PostgreSQL to accept remote connections from your Windows host
#   4. Opens UFW firewall port 5432 (restricted to Windows host IP only)
#   5. Verifies the setup and prints a summary
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration - Edit these if your network setup differs
# ---------------------------------------------------------------------------
DB_NAME="mechfix"
DB_USER="mechfix"
DB_PASSWORD="mechfix_Secure2024!"        # Change this in production
WINDOWS_HOST_IP="10.0.23.26"            # IP of your Windows machine running MechFix
POSTGRES_VERSION="15"

# ---------------------------------------------------------------------------
# Colors for output
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

log()     { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# ---------------------------------------------------------------------------
# Step 0: Verify running as root or with sudo
# ---------------------------------------------------------------------------
if [[ $EUID -ne 0 ]]; then
    error "This script must be run as root or with sudo. Try: sudo ./ubuntu_postgres_setup.sh"
fi

echo ""
echo "============================================================"
echo "  MechFix PostgreSQL Setup - Ubuntu Server"
echo "============================================================"
echo ""

# ---------------------------------------------------------------------------
# Step 1: System update and PostgreSQL install
# ---------------------------------------------------------------------------
log "Updating package lists..."
apt-get update -qq

log "Installing PostgreSQL ${POSTGRES_VERSION} and contrib packages..."
apt-get install -y postgresql postgresql-contrib

# Ensure the service is started and enabled
systemctl enable postgresql
systemctl start postgresql

success "PostgreSQL installed and running."

# ---------------------------------------------------------------------------
# Step 2: Create database user and database
# ---------------------------------------------------------------------------
log "Creating PostgreSQL user '${DB_USER}'..."

# Check if user already exists
USER_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='${DB_USER}'" 2>/dev/null || echo "0")

if [[ "$USER_EXISTS" == "1" ]]; then
    warn "User '${DB_USER}' already exists. Updating password..."
    sudo -u postgres psql -c "ALTER USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';"
else
    sudo -u postgres psql -c "CREATE USER ${DB_USER} WITH PASSWORD '${DB_PASSWORD}';"
    success "User '${DB_USER}' created."
fi

log "Creating database '${DB_NAME}'..."

# Check if database already exists
DB_EXISTS=$(sudo -u postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" 2>/dev/null || echo "0")

if [[ "$DB_EXISTS" == "1" ]]; then
    warn "Database '${DB_NAME}' already exists. Skipping creation."
else
    sudo -u postgres psql -c "CREATE DATABASE ${DB_NAME} OWNER ${DB_USER};"
    success "Database '${DB_NAME}' created."
fi

# Grant full privileges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE ${DB_NAME} TO ${DB_USER};"
sudo -u postgres psql -d ${DB_NAME} -c "GRANT ALL ON SCHEMA public TO ${DB_USER};"

success "Privileges granted."

# ---------------------------------------------------------------------------
# Step 3: Configure postgresql.conf - listen on all interfaces
# ---------------------------------------------------------------------------
PG_CONF=$(sudo -u postgres psql -tAc "SHOW config_file;")
log "Updating ${PG_CONF}..."

# Backup original
cp "${PG_CONF}" "${PG_CONF}.bak.$(date +%Y%m%d_%H%M%S)"

# Set listen_addresses to * (bind all interfaces)
if grep -q "^#listen_addresses\|^listen_addresses" "${PG_CONF}"; then
    sed -i "s|^#*listen_addresses.*|listen_addresses = '*'|" "${PG_CONF}"
else
    echo "listen_addresses = '*'" >> "${PG_CONF}"
fi

success "postgresql.conf: listen_addresses set to '*'"

# ---------------------------------------------------------------------------
# Step 4: Configure pg_hba.conf - allow mechfix user from Windows host only
# ---------------------------------------------------------------------------
PG_HBA=$(sudo -u postgres psql -tAc "SHOW hba_file;")
log "Updating ${PG_HBA}..."

# Backup original
cp "${PG_HBA}" "${PG_HBA}.bak.$(date +%Y%m%d_%H%M%S)"

# Check if rule already exists
HBA_RULE="host    ${DB_NAME}    ${DB_USER}    ${WINDOWS_HOST_IP}/32    scram-sha-256"
if grep -qF "${WINDOWS_HOST_IP}" "${PG_HBA}"; then
    warn "pg_hba.conf already contains a rule for ${WINDOWS_HOST_IP}. Skipping."
else
    # Add rule before the local-only default rules
    echo "" >> "${PG_HBA}"
    echo "# MechFix app server (Windows host - added by setup script)" >> "${PG_HBA}"
    echo "${HBA_RULE}" >> "${PG_HBA}"
    success "pg_hba.conf: remote access rule added for ${WINDOWS_HOST_IP}"
fi

# ---------------------------------------------------------------------------
# Step 5: Reload PostgreSQL to apply config changes
# ---------------------------------------------------------------------------
log "Reloading PostgreSQL configuration..."
systemctl reload postgresql
sleep 2
success "PostgreSQL reloaded."

# ---------------------------------------------------------------------------
# Step 6: Configure UFW firewall
# ---------------------------------------------------------------------------
log "Checking UFW status..."
UFW_STATUS=$(ufw status | head -1)

if echo "${UFW_STATUS}" | grep -q "active"; then
    log "UFW is active. Adding rule for PostgreSQL (port 5432) from ${WINDOWS_HOST_IP} only..."
    ufw allow from "${WINDOWS_HOST_IP}" to any port 5432 proto tcp comment "MechFix app server"
    success "UFW rule added: port 5432 open for ${WINDOWS_HOST_IP}"
else
    warn "UFW is not active. Skipping firewall rule."
    warn "If you enable UFW later, run:"
    warn "  sudo ufw allow from ${WINDOWS_HOST_IP} to any port 5432 proto tcp"
fi

# ---------------------------------------------------------------------------
# Step 7: Install optional monitoring tools
# ---------------------------------------------------------------------------
log "Installing pg_activity for monitoring (optional)..."
apt-get install -y pg-activity 2>/dev/null || warn "pg-activity not available on this Ubuntu version — skipping."

# ---------------------------------------------------------------------------
# Step 8: Verify connection works
# ---------------------------------------------------------------------------
log "Testing local connection as '${DB_USER}'..."
PG_TEST=$(PGPASSWORD="${DB_PASSWORD}" psql -h 127.0.0.1 -U "${DB_USER}" -d "${DB_NAME}" -c "SELECT version();" 2>&1)

if echo "${PG_TEST}" | grep -q "PostgreSQL"; then
    success "Local connection test PASSED."
else
    warn "Local connection test returned unexpected output. Check credentials."
    echo "${PG_TEST}"
fi

# ---------------------------------------------------------------------------
# Step 9: Print summary
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  Setup Complete"
echo "============================================================"
echo ""
echo "  PostgreSQL connection details:"
echo "  ----------------------------------------"
echo "  Host:     $(hostname -I | awk '{print $1}') (or 10.0.23.25)"
echo "  Port:     5432"
echo "  Database: ${DB_NAME}"
echo "  User:     ${DB_USER}"
echo "  Password: ${DB_PASSWORD}"
echo "  ----------------------------------------"
echo ""
echo "  DATABASE_URL for MechFix .env:"
echo "  postgresql://${DB_USER}:${DB_PASSWORD}@10.0.23.25/${DB_NAME}"
echo ""
echo "  To verify PostgreSQL is listening on port 5432:"
echo "    ss -tlnp | grep 5432"
echo ""
echo "  To monitor queries in real-time:"
echo "    sudo pg_activity -U postgres"
echo ""
echo "  To manually connect from this server:"
echo "    psql -h 127.0.0.1 -U ${DB_USER} -d ${DB_NAME}"
echo ""
echo "  From your Windows machine (test connectivity):"
echo "    Test-NetConnection -ComputerName 10.0.23.25 -Port 5432"
echo ""
echo "  Next step: Update MechFix .env on your Windows machine and"
echo "  run: alembic upgrade head"
echo "============================================================"
