"""Lever — Enterprise: company sign-up + company-admin dashboard.

A company subscribes (enterprise tier) and sends its own employees to perform
jobs under the company's brand and rating. Owners/admins manage the roster and
see the dashboard here; employees do the actual jobs through the normal
provider flow, but their completed work rolls up to the COMPANY's reputation
(see active_company_id_for_user + the rollup in routes/client.py).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from age import MINIMUM_AGE_POLICY_VERSION, assert_minimum_age
from auth import create_access_token, hash_password, require_provider
from database import get_db
from email_service import create_and_send_verification
from models import Company, CompanyMember, Job, MechanicProfile, ServiceRequest, User
from schemas import MessageResponse, Token
from subscriptions import ensure_subscription, get_subscription, subscription_public

router = APIRouter(prefix="/api/company", tags=["company"])

CURRENT_TERMS_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Shared helper — the reputation rollup and (future) dispatch branding use this
# ---------------------------------------------------------------------------

def active_company_id_for_user(db: Session, user_id: int) -> Optional[int]:
    """The company a provider actively belongs to (any active membership), or
    None for an independent contractor. A person works for at most one company."""
    m = (
        db.query(CompanyMember)
        .filter(CompanyMember.user_id == user_id, CompanyMember.status == "active")
        .first()
    )
    return m.company_id if m else None


def _require_company_admin(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
) -> CompanyMember:
    m = (
        db.query(CompanyMember)
        .filter(
            CompanyMember.user_id == current_user.id,
            CompanyMember.role.in_(("owner", "admin")),
            CompanyMember.status == "active",
        )
        .first()
    )
    if not m:
        raise HTTPException(status_code=403, detail="NOT_A_COMPANY_ADMIN")
    return m


# ---------------------------------------------------------------------------
# Company sign-up (public)
# ---------------------------------------------------------------------------

class CompanyRegisterIn(BaseModel):
    company_name: str = Field(min_length=2, max_length=200)
    ruc: Optional[str] = Field(default="", max_length=20)
    contact_phone: Optional[str] = Field(default="", max_length=30)
    # Owner (a person — age-verified like any provider)
    email: str = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    accepted_terms: bool
    date_of_birth: date


@router.post("/register", response_model=Token, status_code=201)
def register_company(payload: CompanyRegisterIn, db: Session = Depends(get_db)):
    if not payload.accepted_terms:
        raise HTTPException(status_code=422, detail="You must accept the terms")
    # Age check first — same policy and ordering as individual registration, so
    # it can't leak whether an email already exists.
    assert_minimum_age(payload.date_of_birth)

    email = payload.email.strip().lower()
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(status_code=409, detail="Email already registered")

    # The owner is a provider-side user (role 'mechanic'); company-admin powers
    # come from CompanyMember, not the top-level role.
    owner = User(
        email=email,
        password_hash=hash_password(payload.password),
        role="mechanic",
        email_verified=False,
        terms_accepted_version=CURRENT_TERMS_VERSION,
        terms_accepted_at=datetime.now(timezone.utc),
        date_of_birth=payload.date_of_birth,
        age_verified_at=datetime.now(timezone.utc),
        minimum_age_policy_version=MINIMUM_AGE_POLICY_VERSION,
    )
    db.add(owner)
    db.flush()

    from professions import DEFAULT_PROFESSION
    db.add(MechanicProfile(user_id=owner.id, profession=DEFAULT_PROFESSION, full_name=payload.company_name))

    company = Company(
        name=payload.company_name.strip(),
        ruc=(payload.ruc or "").strip(),
        contact_email=email,
        contact_phone=(payload.contact_phone or "").strip(),
    )
    db.add(company)
    db.flush()
    db.add(CompanyMember(company_id=company.id, user_id=owner.id, role="owner", status="active"))
    # Enterprise subscription starts INACTIVE — billing isn't wired yet.
    ensure_subscription(db, "company", company.id, tier="enterprise", status="inactive")
    db.commit()
    db.refresh(owner)

    success, msg = create_and_send_verification(owner, db)  # non-blocking

    token = create_access_token(owner.id, owner.role, owner.token_version)
    return Token(access_token=token, role=owner.role, user_id=owner.id,
                 profession=DEFAULT_PROFESSION, email_verified=owner.email_verified)


# ---------------------------------------------------------------------------
# Company dashboard (owner / admin)
# ---------------------------------------------------------------------------

@router.get("/me")
def my_company(
    membership: CompanyMember = Depends(_require_company_admin),
    db: Session = Depends(get_db),
):
    company = db.query(Company).filter(Company.id == membership.company_id).first()
    if not company:
        raise HTTPException(status_code=404, detail="Company not found")
    member_count = (
        db.query(func.count(CompanyMember.id))
        .filter(CompanyMember.company_id == company.id, CompanyMember.status == "active")
        .scalar()
    )
    sub = get_subscription(db, "company", company.id)
    return {
        "id": company.id,
        "name": company.name,
        "ruc": company.ruc or "",
        "contact_email": company.contact_email or "",
        "contact_phone": company.contact_phone or "",
        "verification_status": company.verification_status,
        "avg_rating": round(company.avg_rating, 1) if company.total_jobs else None,
        "total_jobs": company.total_jobs or 0,
        "member_count": member_count,
        "my_role": membership.role,
        "subscription": subscription_public(sub),
    }


@router.get("/members")
def list_members(
    membership: CompanyMember = Depends(_require_company_admin),
    db: Session = Depends(get_db),
):
    rows = (
        db.query(CompanyMember)
        .filter(CompanyMember.company_id == membership.company_id,
                CompanyMember.status.in_(("active", "invited")))
        .all()
    )
    users = {u.id: u for u in db.query(User).filter(
        User.id.in_([r.user_id for r in rows] or [0])).all()}
    profs = {p.user_id: p for p in db.query(MechanicProfile).filter(
        MechanicProfile.user_id.in_([r.user_id for r in rows] or [0])).all()}
    out = []
    for r in rows:
        u = users.get(r.user_id)
        p = profs.get(r.user_id)
        out.append({
            "user_id": r.user_id,
            "email": u.email if u else "",
            "name": (p.full_name if p and p.full_name else (u.email if u else "")),
            "role": r.role,
            "status": r.status,
        })
    return out


class InviteIn(BaseModel):
    email: str = Field(max_length=255)


@router.post("/members/invite", response_model=MessageResponse)
def invite_member(
    payload: InviteIn,
    membership: CompanyMember = Depends(_require_company_admin),
    db: Session = Depends(get_db),
):
    email = payload.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == email, User.role == "mechanic").first()
    if not user:
        # Consent + simplicity: the person must already be a registered
        # professional. (Email-based invite-to-register is a later slice.)
        raise HTTPException(status_code=404, detail="PROFESSIONAL_NOT_FOUND")
    # One company per person.
    other = active_company_id_for_user(db, user.id)
    if other and other != membership.company_id:
        raise HTTPException(status_code=409, detail="ALREADY_IN_A_COMPANY")
    existing = db.query(CompanyMember).filter(
        CompanyMember.company_id == membership.company_id,
        CompanyMember.user_id == user.id,
    ).first()
    if existing:
        if existing.status == "active":
            raise HTTPException(status_code=409, detail="ALREADY_A_MEMBER")
        existing.status = "invited"
        existing.role = "employee"
    else:
        db.add(CompanyMember(company_id=membership.company_id, user_id=user.id,
                             role="employee", status="invited"))
    from models import Notification
    db.add(Notification(
        user_id=user.id, type="system", title="Invitación de empresa",
        message="Una empresa te invitó a unirte a su equipo en Lever. Revisa y acepta desde tu cuenta.",
        link="/company/invitations",
    ))
    db.commit()
    return MessageResponse(message="Invitation sent")


@router.delete("/members/{user_id}", response_model=MessageResponse)
def remove_member(
    user_id: int,
    membership: CompanyMember = Depends(_require_company_admin),
    db: Session = Depends(get_db),
):
    m = db.query(CompanyMember).filter(
        CompanyMember.company_id == membership.company_id,
        CompanyMember.user_id == user_id,
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Member not found")
    if m.role == "owner":
        raise HTTPException(status_code=400, detail="CANNOT_REMOVE_OWNER")
    m.status = "removed"
    db.commit()
    return MessageResponse(message="Member removed")


@router.get("/jobs")
def company_jobs(
    membership: CompanyMember = Depends(_require_company_admin),
    db: Session = Depends(get_db),
):
    member_ids = [r[0] for r in db.query(CompanyMember.user_id).filter(
        CompanyMember.company_id == membership.company_id,
        CompanyMember.status == "active").all()]
    if not member_ids:
        return []
    jobs = (
        db.query(Job).filter(Job.mechanic_id.in_(member_ids))
        .order_by(Job.created_at.desc()).limit(100).all()
    )
    reqs = {r.id: r for r in db.query(ServiceRequest).filter(
        ServiceRequest.id.in_([j.request_id for j in jobs] or [0])).all()}
    return [{
        "job_id": j.id, "mechanic_id": j.mechanic_id, "status": j.status,
        "final_price": j.final_price,
        "title": (reqs.get(j.request_id).title if reqs.get(j.request_id) else None),
        "created_at": j.created_at.isoformat() if j.created_at else None,
    } for j in jobs]


# ---------------------------------------------------------------------------
# Employee side — see + accept invitations
# ---------------------------------------------------------------------------

@router.get("/invitations")
def my_invitations(
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    rows = db.query(CompanyMember).filter(
        CompanyMember.user_id == current_user.id, CompanyMember.status == "invited").all()
    companies = {c.id: c for c in db.query(Company).filter(
        Company.id.in_([r.company_id for r in rows] or [0])).all()}
    return [{
        "company_id": r.company_id,
        "company_name": companies.get(r.company_id).name if companies.get(r.company_id) else "",
    } for r in rows]


@router.post("/invitations/{company_id}/accept", response_model=MessageResponse)
def accept_invitation(
    company_id: int,
    current_user: User = Depends(require_provider),
    db: Session = Depends(get_db),
):
    m = db.query(CompanyMember).filter(
        CompanyMember.company_id == company_id,
        CompanyMember.user_id == current_user.id,
        CompanyMember.status == "invited",
    ).first()
    if not m:
        raise HTTPException(status_code=404, detail="Invitation not found")
    other = active_company_id_for_user(db, current_user.id)
    if other and other != company_id:
        raise HTTPException(status_code=409, detail="ALREADY_IN_A_COMPANY")
    m.status = "active"
    db.commit()
    return MessageResponse(message="Joined the company")
