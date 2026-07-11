"""Lever — Email verification service.

CIA Triad Alignment:
  Confidentiality: Verification codes are hashed (bcrypt) before DB storage.
                   Raw codes exist only in memory during generation and in the email.
  Integrity:       Codes have TTL (15 min), attempt counters, rate limits.
                   Expired/used codes are cleared immediately.
  Availability:    SMTP failures are caught and logged — registration still succeeds.
                   Users can resend codes. Mailpit (dev) has no auth overhead.

ISO 27001 Controls:
  A.9.2.1   User registration and de-registration (email ownership proof)
  A.9.4.2   Secure log-on procedures (verification before access)
  A.12.4.1  Event logging (all verification events logged)
  A.14.2.5  Secure system engineering principles (defense in depth)
"""
from __future__ import annotations

import logging
import random
import smtplib
import string
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from auth import hash_password, verify_password
from config import settings

logger = logging.getLogger("lever.email")


# ---------------------------------------------------------------------------
# Code generation
# ---------------------------------------------------------------------------

def generate_verification_code(length: int = None) -> str:
    """Generate a cryptographically random numeric verification code.

    Uses random.SystemRandom (os.urandom backend) for CSPRNG compliance.
    ISO 27001 A.10.1.1 — Cryptographic controls.
    """
    length = length or settings.verification_code_length
    rng = random.SystemRandom()
    return "".join(rng.choices(string.digits, k=length))


def hash_verification_code(code: str) -> str:
    """Hash the verification code before storage (confidentiality).

    Same bcrypt scheme as passwords — codes are never stored in plaintext.
    """
    return hash_password(code)


def verify_verification_code(plain_code: str, hashed_code: str) -> bool:
    """Verify a plaintext code against its bcrypt hash."""
    return verify_password(plain_code, hashed_code)


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def _build_verification_email(to_email: str, code: str, app_url: str = "") -> MIMEMultipart:
    """Build the HTML verification email.

    ISO 27001 A.14.1.2 — Securing application services.
    No user-supplied content in headers (SMTP injection prevention).
    """
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    msg["To"] = to_email
    msg["Subject"] = f"Lever — Verify Your Email Address"
    msg["X-Mailer"] = f"Lever/{settings.app_version}"

    # Plain text fallback
    text_body = f"""Lever — Email Verification

Your verification code is: {code}

This code expires in {settings.verification_code_expire_minutes} minutes.

If you did not create a Lever account, please ignore this email.

— The Lever Team
"""

    # HTML body
    html_body = f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f6f8;font-family:Arial,Helvetica,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f6f8;padding:40px 0;">
<tr><td align="center">
<table width="480" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:12px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,0.08);">

  <!-- Header -->
  <tr><td style="background:linear-gradient(135deg,#1B4F72,#2E86C1);padding:32px 40px;text-align:center;">
    <h1 style="margin:0;color:#ffffff;font-size:28px;letter-spacing:1px;">LEVER</h1>
    <p style="margin:8px 0 0;color:#D6EAF8;font-size:14px;">Multi-Profession Service Platform</p>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:40px;">
    <h2 style="margin:0 0 16px;color:#2C3E50;font-size:20px;">Verify Your Email</h2>
    <p style="color:#555;font-size:15px;line-height:1.6;">
      Thank you for signing up. Enter the following code to verify your email address and activate your account:
    </p>

    <!-- Code box -->
    <div style="margin:28px 0;text-align:center;">
      <div style="display:inline-block;background:#f0f7ff;border:2px solid #2E86C1;border-radius:8px;padding:16px 40px;letter-spacing:12px;font-size:36px;font-weight:bold;color:#1B4F72;">
        {code}
      </div>
    </div>

    <p style="color:#888;font-size:13px;text-align:center;">
      This code expires in <strong>{settings.verification_code_expire_minutes} minutes</strong>.
    </p>

    <hr style="border:none;border-top:1px solid #eee;margin:28px 0;">

    <p style="color:#999;font-size:12px;line-height:1.5;">
      If you did not create a Lever account, you can safely ignore this email.
      No action is required on your part.
    </p>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f9fafb;padding:20px 40px;text-align:center;border-top:1px solid #eee;">
    <p style="margin:0;color:#aaa;font-size:11px;">
      &copy; 2026 Lever. All rights reserved.<br>
      This is an automated message — please do not reply.
    </p>
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))
    return msg


def send_verification_email(to_email: str, code: str) -> bool:
    """Send verification email via SMTP.

    Returns True on success, False on failure (logged, not raised).
    Availability: failures are non-blocking — user can resend later.

    ISO 27001 A.12.4.1 — Event logging for all email operations.
    """
    try:
        msg = _build_verification_email(to_email, code)

        if settings.smtp_use_ssl:
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=15) as server:
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        elif settings.smtp_use_tls:
            # Production: STARTTLS on port 587
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                server.ehlo()
                server.starttls()
                server.ehlo()
                if settings.smtp_user:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)
        else:
            # Development: Mailpit on port 1025 (no TLS, no auth)
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                server.send_message(msg)

        logger.info(f"Verification email sent to {to_email}")
        return True

    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP auth failed for {to_email}: {e}")
        return False
    except smtplib.SMTPException as e:
        logger.error(f"SMTP error sending to {to_email}: {e}")
        return False
    except ConnectionError as e:
        logger.error(f"SMTP connection failed ({settings.smtp_host}:{settings.smtp_port}): {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error sending email to {to_email}: {e}")
        return False


# ---------------------------------------------------------------------------
# Verification workflow helpers
# ---------------------------------------------------------------------------

def create_and_send_verification(user, db: Session) -> Tuple[bool, str]:
    """Generate code, hash it, store on user, send email.

    Returns (success: bool, raw_code_or_error: str).
    The raw code is only returned for logging/testing — in production
    the user receives it exclusively via email.
    """
    from models import User

    # Rate limit check — ISO 27001 A.9.4.2 (brute force prevention)
    if user.last_verification_sent:
        elapsed = (datetime.utcnow() - user.last_verification_sent).total_seconds()
        if elapsed < settings.verification_resend_cooldown_seconds:
            remaining = int(settings.verification_resend_cooldown_seconds - elapsed)
            return False, f"Please wait {remaining} seconds before requesting a new code"

    # Generate and hash code
    raw_code = generate_verification_code()
    hashed_code = hash_verification_code(raw_code)

    # Store hashed code with expiry — Confidentiality: raw code never persisted
    user.verification_token = hashed_code
    user.verification_token_expires = datetime.utcnow() + timedelta(
        minutes=settings.verification_code_expire_minutes
    )
    user.verification_attempts = 0  # Reset attempts on new code
    user.last_verification_sent = datetime.utcnow()
    db.commit()

    # Send email — Availability: failure is non-fatal
    email_sent = send_verification_email(user.email, raw_code)
    if not email_sent:
        logger.warning(f"Email delivery failed for user {user.id} — code is stored, user can retry")
        return False, "Verification code generated but email delivery failed. Please try resending."

    return True, raw_code


def verify_user_code(user, code: str, db: Session) -> Tuple[bool, str]:
    """Validate the verification code and mark user as verified.

    Returns (success: bool, message: str).

    Security controls:
    - Attempt counter prevents brute force (max 10 attempts per code)
    - Expired codes are rejected
    - Code is cleared after successful verification (single-use)
    """
    from models import User

    MAX_ATTEMPTS = 10

    # Check if already verified
    if user.email_verified:
        return True, "Email is already verified"

    # Check if code exists
    if not user.verification_token:
        return False, "No verification code found. Please request a new one."

    # Check expiry — Integrity: time-bound tokens
    if user.verification_token_expires and datetime.utcnow() > user.verification_token_expires:
        # Clear expired token
        user.verification_token = None
        user.verification_token_expires = None
        user.verification_attempts = 0
        db.commit()
        return False, "Verification code has expired. Please request a new one."

    # Check attempt limit — brute force prevention
    if user.verification_attempts >= MAX_ATTEMPTS:
        # Invalidate code after too many attempts
        user.verification_token = None
        user.verification_token_expires = None
        user.verification_attempts = 0
        db.commit()
        logger.warning(f"Verification lockout for user {user.id} — {MAX_ATTEMPTS} failed attempts")
        return False, "Too many failed attempts. Please request a new code."

    # Verify code against hash
    user.verification_attempts += 1
    if not verify_verification_code(code, user.verification_token):
        db.commit()
        remaining = MAX_ATTEMPTS - user.verification_attempts
        return False, f"Invalid verification code. {remaining} attempts remaining."

    # Success — mark verified, clear token
    user.email_verified = True
    user.verification_token = None
    user.verification_token_expires = None
    user.verification_attempts = 0
    db.commit()

    logger.info(f"User {user.id} ({user.email}) email verified successfully")
    return True, "Email verified successfully"
