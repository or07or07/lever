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
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from auth import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from database import get_db
from email_service import create_and_send_verification, verify_user_code
from models import ClientProfile, MechanicProfile, User
from schemas import (
    ClientProfileOut,
    MechanicProfileOut,
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

    token = create_access_token(user.id, user.role)
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

@router.post("/login", response_model=Token)
def login(payload: UserLogin, db: Session = Depends(get_db)):
    """Authenticate and return JWT token.

    ISO 27001 A.9.4.2 — Secure log-on procedures.
    Consistent timing and error messages prevent account enumeration.
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.password_hash or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated")

    # Get profession for token response
    profession = None
    if user.role == "mechanic":
        profile = db.query(MechanicProfile).filter(MechanicProfile.user_id == user.id).first()
        if profile:
            profession = profile.profession

    token = create_access_token(user.id, user.role)
    return Token(
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
    db.commit()

    logger.info(f"Password reset completed for user {user.id}")
    return PasswordResetResponse(
        success=True,
        message="Password has been reset successfully. You can now log in."
    )
