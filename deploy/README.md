# Lever — Production Deployment

All files needed to deploy Lever to a VPS (Hostinger, DigitalOcean, Linode, AWS, etc.)

## Directory Structure

```
deploy/
├── docker-compose.prod.yml    # Production Docker Compose (PostgreSQL + App + Nginx + Certbot)
├── .env.prod.template         # Environment variable template (copy to .env.prod, fill in values)
├── .gitignore                 # Prevents .env.prod and certbot certs from being committed
├── setup-vps.sh               # One-time VPS setup (users, Docker, firewall, SSH hardening)
├── deploy.sh                  # Application deployment (build, TLS, migrations, validation)
├── nginx/
│   ├── nginx.conf             # Main Nginx configuration
│   └── conf.d/
│       └── lever.conf       # Site configuration (replace YOUR_DOMAIN before deploy)
└── README.md                  # This file
```

## Quick Start

### 1. Set up the VPS (once)

```bash
# SSH into VPS as root
ssh root@YOUR_VPS_IP

# Upload and run the setup script
scp deploy/setup-vps.sh root@YOUR_VPS_IP:~
ssh root@YOUR_VPS_IP 'bash setup-vps.sh'

# TEST: Open a new terminal and verify SSH works as 'lever' user
ssh lever@YOUR_VPS_IP
```

### 2. Upload the project

```bash
# From your dev machine:
rsync -avz --exclude '.venv' --exclude '__pycache__' --exclude 'data/*.db' \
  . lever@YOUR_VPS_IP:/opt/lever/
```

### 3. Configure environment

```bash
ssh lever@YOUR_VPS_IP
cd /opt/lever/deploy

# Copy template and fill in real values
cp .env.prod.template .env.prod
nano .env.prod

# Generate secret key:
openssl rand -hex 32

# Generate DB password:
openssl rand -hex 32
```

### 4. Deploy

```bash
cd /opt/lever
bash deploy/deploy.sh --domain lever.yourdomain.com --email admin@yourdomain.com --seed
```

### 5. Verify

```bash
curl https://lever.yourdomain.com/health
```

## Updating

```bash
ssh lever@YOUR_VPS_IP
cd /opt/lever

# Pull latest code
git pull origin main

# Rebuild and restart
cd deploy
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build

# Run any new migrations
docker compose -f docker-compose.prod.yml exec app python -m alembic upgrade head
```

## Backup

```bash
# Database backup
docker compose -f docker-compose.prod.yml exec db pg_dump -U lever lever | gzip > backup_$(date +%Y%m%d).sql.gz

# Restore
gunzip < backup_20260327.sql.gz | docker compose -f docker-compose.prod.yml exec -T db psql -U lever lever
```

## Useful Commands

```bash
cd /opt/lever/deploy

# View logs
docker compose -f docker-compose.prod.yml logs -f app

# Restart app only
docker compose -f docker-compose.prod.yml restart app

# Stop everything
docker compose -f docker-compose.prod.yml down

# Stop and delete ALL data (careful!)
docker compose -f docker-compose.prod.yml down -v
```
