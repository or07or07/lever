"""
Password reset - uses separate reset_* fields.
"""
import logging
import os
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from email_service import (
    generate_verification_code,
    hash_verification_code,
    verify_verification_code,
)

logger = logging.getLogger(__name__)

RESET_CODE_EXPIRE_MINUTES = 30
RESET_MAX_ATTEMPTS = 5
RESET_RATE_LIMIT_SECONDS = 60

def _build_reset_email(to_email: str, code: str):
    smtp_from = os.getenv("SMTP_FROM_EMAIL", "noreply@example.com")
    app_name = os.getenv("APP_NAME", "Lever")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{app_name} - Password Reset Code"
    msg["From"] = smtp_from
    msg["To"] = to_email
    html = f"""<html><body>
<h2>{app_name} - Password Reset</h2>
<p>Your password reset code is:</p>
<h1 style="letter-spacing:8px;color:#2563eb;">{code}</h1>
<p>This code expires in {RESET_CODE_EXPIRE_MINUTES} minutes.</p>
</body></html>"""
    msg.attach(MIMEText(html, "html"))
    return msg

def send_reset_email(to_email: str, code: str) -> bool:
    smtp_host = os.getenv("SMTP_HOST", "localhost")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USERNAME", "")
    smtp_pass = os.getenv("SMTP_PASSWORD", "")
    use_ssl = os.getenv("SMTP_USE_SSL", "").lower()
    use_tls = os.getenv("SMTP_USE_TLS", "").lower()
    msg = _build_reset_email(to_email, code)
    try:
        if use_ssl in ("true", "1", "yes"):
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30)
        elif use_tls in ("true", "1", "yes"):
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
            server.starttls()
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=30)
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        logger.info(f"Reset email sent to {to_email}")
        return True
    except Exception as exc:
        logger.error(f"Failed to send reset email: {exc}")
        return False

def create_and_send_reset(user, db) -> bool:
    now = datetime.utcnow()
    if user.last_reset_sent:
        elapsed = (now - user.last_reset_sent).total_seconds()
        if elapsed < RESET_RATE_LIMIT_SECONDS:
            logger.warning("Reset rate limit for user %s", user.id)
            return True
    code = generate_verification_code()
    user.reset_token = hash_verification_code(code)
    user.reset_token_expires = now + timedelta(minutes=RESET_CODE_EXPIRE_MINUTES)
    user.reset_attempts = 0
    user.last_reset_sent = now
    db.commit()
    ok = send_reset_email(user.email, code)
    if ok:
        return True, "Password reset email sent"
    return False, "Failed to send reset email"

def verify_reset_code(user, code: str, db) -> bool:
    now = datetime.utcnow()
    if not user.reset_token:
        logger.warning("No reset token for user %s", user.id)
        return False
    if user.reset_token_expires and user.reset_token_expires < now:
        logger.warning("Reset token expired for user %s", user.id)
        return False
    if user.reset_attempts >= RESET_MAX_ATTEMPTS:
        logger.warning("Max reset attempts for user %s", user.id)
        return False
    user.reset_attempts = (user.reset_attempts or 0) + 1
    db.commit()
    ok = verify_verification_code(code, user.reset_token)
    if ok:
        user.reset_token = None
        user.reset_token_expires = None
        user.reset_attempts = 0
        db.commit()
    if ok:
        return True, "Code verified"
    return False, "Invalid code"
