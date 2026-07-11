#!/bin/bash
# =============================================================================
# Lever — VPS Initial Setup Script (Ubuntu 22.04 / 24.04)
#
# Run as root on a fresh Hostinger VPS:
#   curl -sSL https://raw.githubusercontent.com/YOUR_ORG/lever/main/deploy/setup-vps.sh | bash
#   — OR —
#   scp setup-vps.sh root@YOUR_VPS_IP:~ && ssh root@YOUR_VPS_IP 'bash setup-vps.sh'
#
# What this script does:
#   1. Updates the system
#   2. Creates a dedicated 'lever' user
#   3. Installs Docker + Docker Compose
#   4. Configures UFW firewall (SSH + HTTP + HTTPS only)
#   5. Hardens SSH (disables root login, password auth)
#   6. Enables automatic security updates
#   7. Installs fail2ban
#
# After running this script, you'll SSH in as 'lever' and deploy the app.
# =============================================================================

set -euo pipefail

echo "============================================="
echo " Lever VPS Setup — Ubuntu $(lsb_release -rs)"
echo "============================================="

# ── 1. System update ──
echo "[1/7] Updating system packages..."
apt update && apt upgrade -y
apt install -y curl git ufw fail2ban unattended-upgrades apt-listchanges

# ── 2. Create lever user ──
echo "[2/7] Creating 'lever' user..."
if ! id "lever" &>/dev/null; then
    adduser --disabled-password --gecos "Lever App" lever
    usermod -aG sudo lever
    # Copy SSH keys from root to lever
    mkdir -p /home/lever/.ssh
    cp /root/.ssh/authorized_keys /home/lever/.ssh/authorized_keys 2>/dev/null || true
    chown -R lever:lever /home/lever/.ssh
    chmod 700 /home/lever/.ssh
    chmod 600 /home/lever/.ssh/authorized_keys 2>/dev/null || true
    echo "lever ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/lever
    echo "  → User 'lever' created with sudo access"
else
    echo "  → User 'lever' already exists"
fi

# ── 3. Install Docker ──
echo "[3/7] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | sh
    usermod -aG docker lever
    systemctl enable --now docker
    echo "  → Docker installed: $(docker --version)"
else
    echo "  → Docker already installed: $(docker --version)"
fi

# Verify Docker Compose is available
if docker compose version &>/dev/null; then
    echo "  → Docker Compose: $(docker compose version --short)"
else
    echo "  ERROR: Docker Compose plugin not found. Install it manually."
    exit 1
fi

# ── 4. Configure UFW Firewall ──
echo "[4/7] Configuring firewall (UFW)..."
ufw --force reset
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "HTTP"
ufw allow 443/tcp comment "HTTPS"
ufw --force enable
echo "  → Firewall active: SSH (22), HTTP (80), HTTPS (443) allowed"

# ── 5. Harden SSH ──
echo "[5/7] Hardening SSH..."
SSHD_CONFIG="/etc/ssh/sshd_config"
# Backup original
cp "$SSHD_CONFIG" "${SSHD_CONFIG}.backup.$(date +%Y%m%d)"

# Apply hardening (only if not already set)
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' "$SSHD_CONFIG"
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' "$SSHD_CONFIG"
sed -i 's/^#\?ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' "$SSHD_CONFIG"
sed -i 's/^#\?MaxAuthTries.*/MaxAuthTries 3/' "$SSHD_CONFIG"
sed -i 's/^#\?X11Forwarding.*/X11Forwarding no/' "$SSHD_CONFIG"

# Validate config before restarting
if sshd -t; then
    systemctl restart sshd
    echo "  → SSH hardened: root login disabled, password auth disabled"
else
    echo "  WARNING: SSH config validation failed. Restoring backup."
    cp "${SSHD_CONFIG}.backup.$(date +%Y%m%d)" "$SSHD_CONFIG"
fi

# ── 6. Automatic security updates ──
echo "[6/7] Enabling automatic security updates..."
cat > /etc/apt/apt.conf.d/20auto-upgrades << 'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
echo "  → Automatic security updates enabled"

# ── 7. Configure fail2ban ──
echo "[7/7] Configuring fail2ban..."
cat > /etc/fail2ban/jail.local << 'EOF'
[DEFAULT]
bantime = 3600
findtime = 600
maxretry = 5

[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 3
bantime = 7200
EOF
systemctl enable --now fail2ban
echo "  → fail2ban active: 3 SSH failures = 2-hour ban"

# ── Create app directory ──
mkdir -p /opt/lever
chown lever:lever /opt/lever

echo ""
echo "============================================="
echo " VPS Setup Complete!"
echo "============================================="
echo ""
echo " IMPORTANT — Before you lose SSH access:"
echo "   1. Open a NEW terminal window"
echo "   2. Test: ssh lever@$(curl -s ifconfig.me)"
echo "   3. Only close this terminal after step 2 works"
echo ""
echo " Next steps:"
echo "   1. SSH in as 'lever' (not root)"
echo "   2. Clone the repo to /opt/lever"
echo "   3. Run the deploy script"
echo ""
echo "============================================="
