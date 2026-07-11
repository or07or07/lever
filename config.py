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

BASE_DIR = Path(__file__).parent


class Settings(BaseSettings):
    app_name: str = "Lever"
    app_version: str = "2.3.0"
    debug: bool = False

    # Database
    database_url: str = f"sqlite:///{BASE_DIR}/data/lever.db"

    # JWT – ISO 27001 A.10.1.1 (Cryptographic controls)
    secret_key: str = "CHANGE-ME-IN-PRODUCTION-use-openssl-rand-hex-32"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 1440  # 24 hours

    # Server
    host: str = "0.0.0.0"
    port: int = 8500

    # Admin bootstrap (created on first startup)
    admin_email: str = "admin@lever.app"
    admin_password: str = "Admin123!"

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

    # Rate limiting
    login_rate_limit: int = 10        # attempts per window
    login_rate_window_minutes: int = 15
    register_rate_limit: int = 5
    register_rate_window_minutes: int = 15

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
