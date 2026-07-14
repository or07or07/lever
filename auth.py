"""Lever — Authentication & authorization helpers."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from config import settings
from database import get_db

# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def create_access_token(
    user_id: int,
    role: str,
    token_version: int = 0,
    expires_delta: Optional[timedelta] = None,
) -> str:
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.access_token_expire_minutes))
    # "ver" ties this token to the user's current token_version (GP-13) —
    # bumping that column instantly invalidates every token issued before
    # the bump, without needing a server-side session/blocklist table.
    payload = {"sub": str(user_id), "role": role, "ver": token_version, "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


# ---------------------------------------------------------------------------
# Admin MFA — short-lived "pending" token issued between password and TOTP
# verification (GP-14). Deliberately a distinct token shape (a "purpose"
# claim instead of "role"/"ver") so it can't be mistaken for, or used as,
# a real access token even if leaked or replayed against another endpoint.
# ---------------------------------------------------------------------------
def create_mfa_pending_token(user_id: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {"sub": str(user_id), "purpose": "mfa_pending", "exp": expire}
    return jwt.encode(payload, settings.secret_key, algorithm=settings.algorithm)


def verify_mfa_pending_token(token: str) -> int:
    """Returns the pending user_id, or raises JWTError/ValueError if the
    token is invalid, expired, or not actually an MFA-pending token."""
    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
    if payload.get("purpose") != "mfa_pending":
        raise JWTError("Not an MFA-pending token")
    return int(payload.get("sub"))


# ---------------------------------------------------------------------------
# Dependency: current user
# ---------------------------------------------------------------------------
def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired token",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(token)
        user_id = int(payload.get("sub"))
        token_ver = payload.get("ver", 0)
        # Only create_access_token sets "role" (GP-14's short-lived
        # mfa_pending token deliberately never does) — without this check,
        # an mfa_pending token would pass every check below as long as the
        # target user's token_version was still its default 0, letting it
        # be used as a real access token and skip the TOTP step entirely.
        if not payload.get("role"):
            raise credentials_exc
    except (JWTError, TypeError, ValueError):
        raise credentials_exc

    from models import User
    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active:
        raise credentials_exc
    # Tokens issued before this claim existed carry no "ver" and are
    # treated as version 0, matching every user's default token_version —
    # so this check only starts rejecting tokens once something actually
    # bumps the version (logout-everywhere, password reset).
    if token_ver != user.token_version:
        raise credentials_exc
    return user


# ---------------------------------------------------------------------------
# Role guards
# ---------------------------------------------------------------------------
def require_role(*roles):
    """Factory that returns a dependency requiring the user to have one of the given roles."""
    def _guard(current_user=Depends(get_current_user)):
        if current_user.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient permissions")
        return current_user
    return _guard


require_client = require_role("client")
require_provider = require_role("mechanic")        # Preferred — maps to DB role "mechanic"
require_admin = require_role("admin")
require_client_or_mechanic = require_role("client", "mechanic")
require_client_or_provider = require_role("client", "mechanic")  # Preferred alias
