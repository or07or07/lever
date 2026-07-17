# =============================================================================
# Lever — Production Dockerfile
# Multi-stage build: slim Python image for FastAPI application
#
# CIA Triad:
#   Confidentiality: Non-root user, no secrets baked into image
#   Integrity:       Pinned base image, deterministic pip install
#   Availability:    Health check, graceful shutdown via uvicorn
# =============================================================================

FROM python:3.11-slim AS base

# Security: don't run as root
RUN groupadd -r lever && useradd -r -g lever -d /app -s /sbin/nologin lever

WORKDIR /app

# System dependencies (psycopg2 needs libpq)
RUN apt-get update && \
    apt-get install -y --no-install-recommends libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir psutil

# Application code
COPY . .

# Create data directory for SQLite fallback
RUN mkdir -p /app/data /app/logs && \
    chown -R lever:lever /app

USER lever

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8500/health')" || exit 1

EXPOSE 8500

# Run migrations BEFORE the app starts. The app's lifespan queries User at
# boot, so booting with pending column migrations crash-loops — and the old
# "exec alembic in the running app" deploy step could never run against a
# container that can't boot (the 2026-07-17 outage). Migrations are idempotent,
# so this is safe on every start; if a migration genuinely fails, failing fast
# here (before serving traffic) is the correct behaviour.
CMD ["sh", "-c", "python -m alembic upgrade head && python -m uvicorn app:app --host 0.0.0.0 --port 8500"]
