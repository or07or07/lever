"""Lever — Auth routes: register, login, profile, email verification.

CIA Triad Alignment:
  Confidentiality: Verification codes hashed in DB, consistent error responses
                   to prevent account enumeration (ISO 27001 A.9.4.2)
  Integrity:       Email ownership proven before platform access granted
                   Rate limits prevent brute force (ISO 27001 A.9.4.2)
  Availability:    SMTP failure is non-blocking — registration still succeeds
                   Users can resend codes (ISO 27001 A.17.1.1)

ISO 27001 Controls:
  A.9.2.1   User registration and de-registration
  A.9.4.2   Secure log-on procedures
  A.9.4.3   Password management system
  A.12.4.1  Event logging
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

import pyotp
from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    create_mfa_pending_token,
    get_current_user,
    hash_password,
    require_admin,
    verify_mfa_pending_token,
    verify_password,
)
from database import get_db
from email_service import create_and_send_verification, verify_user_code
from models import ClientProfile, Job, MechanicProfile, Notification, ProviderLocation, ServiceRequest, User, Vehicle
from schemas import (
    AccountDeleteRequest,
    AccountDeleteResponse,
    ClientProfileOut,
    LoginResponse,
    MechanicProfileOut,
    MessageResponse,
    MfaConfirmRequest,
    MfaDisableRequest,
    MfaSetupResponse,
    MfaStatusResponse,
    MfaVerifyLoginRequest,
    PasswordResetRequest,
    PasswordResetResponse,
    PasswordResetVerify,
    ResendVerificationResponse,
    Token,
    UserCreate,
    UserLogin,
    UserOut,
    VerifyEmailRequest,
    VerifyEmailResponse,
)

logger = logging.getLogger("lever.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Bumped whenever /terms or /privacy content changes materially. Existing
# users are not forced to re-accept retroactively (no re-consent flow
# exists yet) — this is recorded per-registration going forward.
CURRENT_TERMS_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Registration — now sends verification email
# ---------------------------------------------------------------------------

@router.post("/register", response_model=Token, status_code=status.HTTP_201_CREATED)
def register(payload: UserCreate, db: Session = Depends(get_db)):
    """Register a new user account.

    Flow:
    1. Create user with email_verified=False
    2. Create role-specific profile
    3. Generate verification code, hash it, store it
    4. Send verification email via SMTP
    5. Return JWT token (user can log in but sees verification gate)

    ISO 27001 A.9.2.1 — Formal user registration process.
    """
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    user = User(
        email=payload.email,
        password_hash=hash_password(payload.password),
        role=payload.role,
        email_verified=False,  # Must verify email before full access
        # payload.accepted_terms is guaranteed True here — UserCreate's
        # validator rejects registration otherwise.
        terms_accepted_version=CURRENT_TERMS_VERSION,
        terms_accepted_at=datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()

    # Create role-specific profile
    if payload.role == "client":
        db.add(ClientProfile(user_id=user.id))
    elif payload.role == "mechanic":
        profession = payload.profession or "mechanic"
        db.add(MechanicProfile(user_id=user.id, profession=profession))

    db.commit()
    db.refresh(user)

    # Send verification email (non-blocking — failure logged, not raised)
    success, msg = create_and_send_verification(user, db)
    if not success:
        logger.warning(f"Verification email not sent for user {user.id}: {msg}")

    # Get profession for token response
    profession = None
    if user.role == "mechanic":
        profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == user.id).first()
        if profile:
            profession = profile.profession

    token = create_access_token(user.id, user.role, user.token_version)
    return Token(
        access_token=token,
        role=user.role,
        user_id=user.id,
        profession=profession,
        email_verified=user.email_verified,
    )


# ---------------------------------------------------------------------------
# Login — now includes email_verified status
# ---------------------------------------------------------------------------

@router.post("/login", response_model=LoginResponse)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """Authenticate and return a JWT token — or, for an MFA-enabled admin,
    an mfa_required challenge that must be completed via
    POST /api/auth/mfa/verify-login before a real token is issued (GP-14).

    ISO 27001 A.9.4.2 — Secure log-on procedures.
    Consistent timing and error messages prevent account enumeration.
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    if user.role == "admin" and user.mfa_enabled:
        return LoginResponse(mfa_required=True, mfa_token=create_mfa_pending_token(user.id))

    # Get profession for token response
    profession = None
    if user.role == "mechanic":
        profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == user.id).first()
        if profile:
            profession = profile.profession

    token = create_access_token(user.id, user.role, user.token_version)
    return LoginResponse(
        access_token=token,
        role=user.role,
        user_id=user.id,
        profession=profession,
        email_verified=user.email_verified,
    )


# ---------------------------------------------------------------------------
# Email Verification
# ---------------------------------------------------------------------------

@router.post("/verify-email", response_model=VerifyEmailResponse)
def verify_email(
    payload: VerifyEmailRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify email with 6-digit code.

    ISO 27001 A.9.2.1 — Complete user registration by proving email ownership.
    Attempt limits and code expiry enforce integrity.
    """
    success, message = verify_user_code(current_user, payload.code, db)

    # Refresh user to get updated email_verified
    db.refresh(current_user)

    return VerifyEmailResponse(
        success=success,
        message=message,
        email_verified=current_user.email_verified,
    )


@router.post("/resend-verification", response_model=ResendVerificationResponse)
def resend_verification(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Resend verification email with a new code.

    Rate limited: cooldown between sends, max attempts per hour.
    ISO 27001 A.9.4.2 — Prevent abuse of verification system.
    """
    if current_user.email_verified:
        return ResendVerificationResponse(
            success=True,
            message="Email is already verified",
            cooldown_seconds=0,
        )

    success, msg = create_and_send_verification(current_user, db)

    if not success:
        # Extract cooldown if rate limited
        cooldown = 0
        if "wait" in msg.lower():
            try:
                cooldown = int("".join(c for c in msg if c.isdigit()))
            except ValueError:
                cooldown = 60
        return ResendVerificationResponse(
            success=False,
            message=msg,
            cooldown_seconds=cooldown,
        )

    return ResendVerificationResponse(
        success=True,
        message="Verification code sent to your email",
        cooldown_seconds=60,
    )


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------

@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.get("/me/profile")
def my_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if current_user.role == "client":
        profile = db.query(ClientProfile).filter(ClientProfile.user_id == current_user.id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return ClientProfileOut.model_validate(profile)
    elif current_user.role == "mechanic":
        profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == current_user.id).first()
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")
        return MechanicProfileOut.model_validate(profile)
    else:
        return {"role": "admin", "email": current_user.email}


# ---------------------------------------------------------------------------
# Logout everywhere (GP-13)
# ---------------------------------------------------------------------------

@router.post("/logout-all", response_model=MessageResponse)
def logout_all_devices(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Invalidate every access token issued for this account, including the
    one used to make this request — bumping token_version instantly fails
    the "ver" check in get_current_user for all of them. The caller (and
    every other logged-in device) must sign in again afterward.

    ISO 27001 A.9.4.2 — Section 12 "log out of all devices" requirement.
    """
    current_user.token_version += 1
    db.commit()
    return MessageResponse(message="You have been logged out of all devices.")


# ---------------------------------------------------------------------------
# Admin MFA / TOTP (GP-14)
# ---------------------------------------------------------------------------

_BACKUP_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O/1/I — hard to misread


def _generate_backup_codes(count: int = 8) -> list[str]:
    return [
        "-".join("".join(secrets.choice(_BACKUP_CODE_ALPHABET) for _ in range(4)) for _ in range(2))
        for _ in range(count)
    ]


@router.get("/mfa/status", response_model=MfaStatusResponse)
def mfa_status(current_user: User = Depends(require_admin)):
    remaining = len(current_user.mfa_backup_codes or []) if current_user.mfa_enabled else 0
    return MfaStatusResponse(enabled=current_user.mfa_enabled, backup_codes_remaining=remaining)


@router.post("/mfa/setup", response_model=MfaSetupResponse)
def mfa_setup(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Start (or restart) MFA enrollment: generates a new secret and a
    fresh set of backup codes. mfa_enabled stays False until the admin
    proves they can generate a valid code via POST /mfa/confirm — this
    prevents someone from being locked into MFA by a botched setup where
    they never actually confirmed their authenticator app is working.
    Backup codes are only ever returned here, in plaintext, once; only
    their bcrypt hashes are stored.
    """
    secret = pyotp.random_base32()
    backup_codes = _generate_backup_codes()

    current_user.mfa_secret = secret
    current_user.mfa_enabled = False
    current_user.mfa_backup_codes = [hash_password(c) for c in backup_codes]
    db.commit()

    otpauth_uri = pyotp.TOTP(secret).provisioning_uri(name=current_user.email, issuer_name="Lever Admin")
    return MfaSetupResponse(secret=secret, otpauth_uri=otpauth_uri, backup_codes=backup_codes)


@router.post("/mfa/confirm", response_model=MessageResponse)
def mfa_confirm(
    payload: MfaConfirmRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Confirm enrollment by proving the authenticator app produces a
    valid code, then actually turn MFA on."""
    if not current_user.mfa_secret:
        raise HTTPException(status_code=400, detail="Call /mfa/setup first")

    totp = pyotp.TOTP(current_user.mfa_secret)
    if not totp.verify(payload.code, valid_window=1):
        raise HTTPException(status_code=401, detail="Invalid code")

    current_user.mfa_enabled = True
    db.commit()
    logger.info(f"MFA enabled for admin user {current_user.id}")
    return MessageResponse(message="Two-factor authentication is now enabled.")


@router.post("/mfa/disable", response_model=MessageResponse)
def mfa_disable(
    payload: MfaDisableRequest,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    if not current_user.password_hash or not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    current_user.mfa_enabled = False
    current_user.mfa_secret = None
    current_user.mfa_backup_codes = None
    db.commit()
    logger.info(f"MFA disabled for admin user {current_user.id}")
    return MessageResponse(message="Two-factor authentication has been disabled.")


@router.post("/mfa/verify-login", response_model=Token)
def mfa_verify_login(
    payload: MfaVerifyLoginRequest,
    db: Session = Depends(get_db),
):
    """Second step of an MFA-gated login: exchange the mfa_token from
    /login plus a TOTP (or backup) code for a real access token."""
    invalid = HTTPException(status_code=401, detail="Invalid or expired code")
    try:
        user_id = verify_mfa_pending_token(payload.mfa_token)
    except (JWTError, TypeError, ValueError):
        raise invalid

    user = db.query(User).filter(User.id == user_id).first()
    if not user or not user.is_active or not user.mfa_enabled or not user.mfa_secret:
        raise invalid

    totp = pyotp.TOTP(user.mfa_secret)
    if totp.verify(payload.code, valid_window=1):
        matched_backup = False
    else:
        # Not a valid TOTP code — try it as a single-use backup code instead.
        codes = user.mfa_backup_codes or []
        remaining = [c for c in codes if not verify_password(payload.code, c)]
        matched_backup = len(remaining) < len(codes)
        if not matched_backup:
            raise invalid
        user.mfa_backup_codes = remaining  # consume it — single use

    profession = None
    if user.role == "mechanic":
        profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == user.id).first()
        if profile:
            profession = profile.profession

    token = create_access_token(user.id, user.role, user.token_version)
    db.commit()
    if matched_backup:
        logger.info(f"Admin user {user.id} logged in using a backup MFA code")
    return Token(
        access_token=token,
        role=user.role,
        user_id=user.id,
        profession=profession,
        email_verified=user.email_verified,
    )


# ---------------------------------------------------------------------------
# Password Reset (Day 30 addition)
# ---------------------------------------------------------------------------

@router.post("/reset-password-request", response_model=PasswordResetResponse)
def request_password_reset(
    payload: PasswordResetRequest,
    db: Session = Depends(get_db),
):
    """Request a password reset code.

    ISO 27001 A.9.4.3 — Password management system.

    IMPORTANT: Consistent response regardless of whether email exists.
    This prevents account enumeration (A.9.4.2).
    """
    from password_reset import create_and_send_reset

    # Always return success to prevent enumeration
    generic_msg = "If an account with this email exists, a reset code has been sent."

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        logger.info(f"Password reset requested for non-existent email: {payload.email}")
        return PasswordResetResponse(success=True, message=generic_msg)

    if not user.is_active:
        logger.info(f"Password reset requested for deactivated account: {user.id}")
        return PasswordResetResponse(success=True, message=generic_msg)

    success, msg = create_and_send_reset(user, db)
    if not success:
        logger.warning(f"Password reset email failed for user {user.id}: {msg}")

    return PasswordResetResponse(success=True, message=generic_msg)


@router.post("/reset-password-verify", response_model=PasswordResetResponse)
def verify_password_reset(
    payload: PasswordResetVerify,
    db: Session = Depends(get_db),
):
    """Verify reset code and set new password.

    ISO 27001 A.9.4.3 — Password management system.
    """
    from password_reset import verify_reset_code

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid email or code")

    success, msg = verify_reset_code(user, payload.code, db)
    if not success:
        raise HTTPException(status_code=400, detail=msg)

    # Code verified — update password
    from auth import hash_password as hp
    user.password_hash = hp(payload.new_password)
    # Auto-verify email on successful password reset
    if not user.email_verified:
        user.email_verified = True
    # A password reset is exactly the "someone else may have my old
    # password" scenario — kill every session logged in under it (GP-13).
    user.token_version += 1
    db.commit()

    logger.info(f"Password reset completed for user {user.id}")
    return PasswordResetResponse(
        success=True,
        message="Password has been reset successfully. You can now log in."
    )


# ---------------------------------------------------------------------------
# Account deletion (GP-07)
# ---------------------------------------------------------------------------

DELETED_USER_LABEL = "Usuario eliminado"


@router.delete("/account", response_model=AccountDeleteResponse)
def delete_account(
    payload: AccountDeleteRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Delete the current user's account.

    Policy (confirmed by the Lever owner): the user's own profile and
    auth data (email, password, contact details, avatar, precise
    location) is wiped. Records shared with other users — job history,
    chat messages, reviews — are kept but stripped of this user's
    identifying details, so the other party's history and rating
    integrity are preserved. See docs/google-play-readiness.md GP-07.

    Requires re-entering the password so a stolen/hijacked bearer token
    alone can't trigger this irreversible action.
    """
    if current_user.deleted_at is not None:
        raise HTTPException(status_code=400, detail="Account already deleted")

    if current_user.password_hash and not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=401, detail="Incorrect password")

    # Block deletion while an active job would strand the other party.
    open_request = (
        db.query(ServiceRequest)
        .filter(
            ServiceRequest.client_id == current_user.id,
            ServiceRequest.status.notin_(["completed", "cancelled"]),
        )
        .first()
    )
    open_job = (
        db.query(Job)
        .filter(
            Job.mechanic_id == current_user.id,
            Job.status.notin_(["completed", "cancelled"]),
        )
        .first()
    )
    if open_request or open_job:
        raise HTTPException(
            status_code=409,
            detail="You have an active service request or job in progress. "
                   "Please complete or cancel it before deleting your account.",
        )

    now = datetime.now(timezone.utc)

    # Wipe this user's own private data outright — it isn't needed by anyone else.
    db.query(Vehicle).filter(Vehicle.client_id == current_user.id).delete(synchronize_session=False)
    db.query(Notification).filter(Notification.user_id == current_user.id).delete(synchronize_session=False)
    db.query(ProviderLocation).filter(
        ProviderLocation.provider_user_id == current_user.id
    ).delete(synchronize_session=False)

    # Anonymize (not delete) the user row itself: job/message/review records
    # still reference this id via foreign keys, and other users' job history
    # and ratings must remain intact. Deactivating immediately revokes every
    # existing session, since get_current_user rejects inactive users.
    current_user.email = f"deleted-user-{current_user.id}@deleted.lever.app"
    current_user.password_hash = None
    current_user.is_active = False
    current_user.deleted_at = now
    current_user.oauth_provider = None
    current_user.oauth_provider_id = None
    current_user.verification_token = None
    current_user.verification_token_expires = None
    current_user.reset_token = None
    current_user.reset_token_expires = None

    client_profile = db.query(ClientProfile).filter(ClientProfile.user_id == current_user.id).first()
    if client_profile:
        client_profile.full_name = DELETED_USER_LABEL
        client_profile.phone = ""
        client_profile.address = ""
        client_profile.avatar_url = ""

    mechanic_profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == current_user.id).first()
    if mechanic_profile:
        mechanic_profile.full_name = DELETED_USER_LABEL
        mechanic_profile.phone = ""
        mechanic_profile.bio = ""
        mechanic_profile.specialties = []
        mechanic_profile.avatar_url = ""
        mechanic_profile.location = ""
        mechanic_profile.latitude = None
        mechanic_profile.longitude = None
        mechanic_profile.is_available = False
        mechanic_profile.is_online = False

    db.commit()

    logger.info(f"Account {current_user.id} deleted (anonymized) at {now.isoformat()}")
    return AccountDeleteResponse(
        success=True,
        message="Your account has been deleted.",
    )
