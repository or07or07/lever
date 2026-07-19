"""Lever – Application configuration.

CIA Triad Alignment:
  Confidentiality: Secrets loaded from env vars / .env (not hardcoded in prod)
  Integrity:       HMAC-signed JWT tokens, bcrypt password hashing
  Availability:    Configurable timeouts, rate limits, graceful degradation

ISO 27001 Controls Referenced:
  A.9.4.2  Secure log-on procedures
  A.10.1.1 Cryptographic controls policy
  A.14.1.2 Securing application services on public networks
"""
import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import model_validator

BASE_DIR = Path(__file__).parent

INSECURE_DEFAULT_SECRET_KEY = "CHANGE-ME-IN-PRODUCTION-use-openssl-rand-hex-32"
INSECURE_DEFAULT_ADMIN_PASSWORD = "Admin123!"


class Settings(BaseSettings):
    app_name: str = "Lever"
    app_version: str = "2.3.0"
    debug: bool = False

    # Seconds a professional has to accept a job offer before it rotates to
    # the next candidate. 90s while offers only reach an OPEN app (no push
    # notifications yet); tighten toward 30-45s once FCM ships.
    dispatch_offer_seconds: int = 90

    # Database
    database_url: str = f"sqlite:///{BASE_DIR}/data/lever.db"

    # JWT – ISO 27001 A.10.1.1 (Cryptographic controls)
    secret_key: str = INSECURE_DEFAULT_SECRET_KEY
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # Server
    host: str = "0.0.0.0"
    port: int = 8500

    # Admin bootstrap (created on first startup)
    admin_email: str = "admin@lever.app"
    admin_password: str = INSECURE_DEFAULT_ADMIN_PASSWORD

    @model_validator(mode="after")
    def _refuse_insecure_defaults_outside_debug(self):
        if not self.debug:
            if self.secret_key == INSECURE_DEFAULT_SECRET_KEY:
                raise ValueError(
                    "SECRET_KEY is unset (using the insecure placeholder default) while DEBUG=false. "
                    "Set a real SECRET_KEY (openssl rand -hex 32) before running in production."
                )
            if self.admin_password == INSECURE_DEFAULT_ADMIN_PASSWORD:
                raise ValueError(
                    "ADMIN_PASSWORD is unset (using the insecure placeholder default) while DEBUG=false. "
                    "Set a real ADMIN_PASSWORD before running in production."
                )
        return self

    # ── SMTP / Email Verification ──
    # ISO 27001 A.9.4.2 (Secure log-on – email ownership proof)
    smtp_host: str = "10.0.23.25"
    smtp_port: int = 1025             # Mailpit dev default; 587 for prod Postfix
    smtp_use_tls: bool = False        # True for STARTTLS on port 587
    smtp_use_ssl: bool = False        # True for SMTP_SSL on port 465 (e.g., Hostinger)
    smtp_user: str = ""               # Empty for Mailpit; set for prod relay
    smtp_password: str = ""           # Empty for Mailpit; set for prod relay
    smtp_from_email: str = "noreply@lever.local"
    smtp_from_name: str = "Lever"

    # Verification settings
    verification_code_length: int = 6
    verification_code_expire_minutes: int = 15
    verification_max_resends_per_hour: int = 5
    verification_resend_cooldown_seconds: int = 60

    # Worker-set pricing (Phase 1): professionals choose their own hourly
    # rate inside these bounds. The floor sits above Ecuador's SBU-derived
    # $3.01/h (see pricing.py) — honesty-first means nobody undercuts a
    # dignified wage; the ceiling is a sanity cap against typos.
    provider_min_hourly_rate: float = 4.0
    provider_max_hourly_rate: float = 60.0

    # Provider presence: being ONLINE is a lease renewed by the app's 60s
    # heartbeat. Miss heartbeats for this many minutes (app closed, phone
    # off, connection lost) and the server flips the provider offline —
    # ghost-online providers would otherwise soak up offer windows.
    provider_offline_after_minutes: int = 5

    # Rate limiting
    login_rate_limit: int = 10        # attempts per window
    login_rate_window_minutes: int = 15
    register_rate_limit: int = 5
    register_rate_window_minutes: int = 15
    # GP-12: when set, rate limiting is backed by Redis (shared across all
    # app instances, survives restarts) instead of per-process memory.
    # Empty string (the default) keeps the original in-memory behavior —
    # nothing changes for local dev or single-instance deployments unless
    # this is explicitly configured.
    redis_url: str = ""

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
