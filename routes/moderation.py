"""Lever — Content moderation routes: reports and blocking (GP-08).

Any authenticated user can report a user, message, review, or service
request; admins review reports via routes/admin.py. Blocking is
self-service and enforced at the discovery/messaging layer (job board,
provider search, map, and sending new messages) — see the block-pair
checks in routes/provider.py, routes/search.py, and routes/messages.py.
"""
from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from auth import get_current_user
from database import get_db
from models import Block, ClientProfile, MechanicProfile, Message, Review, ServiceRequest, User
from schemas import BlockCreate, BlockOut, ReportCreate, ReportOut

router = APIRouter(tags=["moderation"])


def _display_name(db: Session, user_id: int) -> str:
    cp = db.query(ClientProfile).filter(ClientProfile.user_id == user_id).first()
    if cp and cp.full_name:
        return cp.full_name
    mp = db.query(MechanicProfile).filter(MechanicProfile.user_id == user_id).first()
    if mp and mp.full_name:
        return mp.full_name
    return ""


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------

@router.post("/api/reports", response_model=ReportOut, status_code=status.HTTP_201_CREATED)
def create_report(
    payload: ReportCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """File a report. Who is being reported is resolved server-side from
    the entity itself (never trusted from the client) for every type
    except a direct 'user' report, where entity_id is the target's id."""
    reported_user_id: int
    entity_id = payload.entity_id

    if payload.entity_type == "user":
        target = db.get(User, entity_id)
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        reported_user_id = target.id

    elif payload.entity_type == "message":
        msg = db.get(Message, entity_id)
        if not msg:
            raise HTTPException(status_code=404, detail="Message not found")
        from models import Job
        job = db.query(Job).filter(Job.id == msg.job_id).first()
        req = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first() if job else None
        is_participant = job and (
            current_user.id == job.mechanic_id or (req and current_user.id == req.client_id)
        )
        if not is_participant and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not authorised to report this message")
        reported_user_id = msg.sender_id

    elif payload.entity_type == "review":
        review = db.get(Review, entity_id)
        if not review:
            raise HTTPException(status_code=404, detail="Review not found")
        if current_user.id != review.mechanic_id and current_user.role != "admin":
            raise HTTPException(status_code=403, detail="Not authorised to report this review")
        reported_user_id = review.client_id

    elif payload.entity_type == "service_request":
        req = db.get(ServiceRequest, entity_id)
        if not req:
            raise HTTPException(status_code=404, detail="Service request not found")
        if current_user.role not in ("mechanic", "admin") or current_user.id == req.client_id:
            raise HTTPException(status_code=403, detail="Not authorised to report this request")
        reported_user_id = req.client_id

    else:  # pragma: no cover — caught by schema pattern validation already
        raise HTTPException(status_code=400, detail="Invalid entity_type")

    if reported_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot report yourself")

    from models import Report
    report = Report(
        reporter_id=current_user.id,
        reported_user_id=reported_user_id,
        entity_type=payload.entity_type,
        entity_id=entity_id,
        category=payload.category,
        description=payload.description,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


@router.get("/api/reports/mine", response_model=List[ReportOut])
def list_my_reports(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from models import Report
    return (
        db.query(Report)
        .filter(Report.reporter_id == current_user.id)
        .order_by(Report.created_at.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Blocking
# ---------------------------------------------------------------------------

@router.post("/api/blocks", response_model=BlockOut, status_code=status.HTTP_201_CREATED)
def block_user(
    payload: BlockCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if payload.blocked_user_id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot block yourself")

    target = db.get(User, payload.blocked_user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    existing = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.id, Block.blocked_id == payload.blocked_user_id)
        .first()
    )
    if existing:
        block = existing
    else:
        block = Block(blocker_id=current_user.id, blocked_id=payload.blocked_user_id)
        db.add(block)
        db.commit()
        db.refresh(block)

    return BlockOut(
        id=block.id,
        blocker_id=block.blocker_id,
        blocked_id=block.blocked_id,
        blocked_email=target.email,
        blocked_name=_display_name(db, target.id),
        created_at=block.created_at,
    )


@router.get("/api/blocks", response_model=List[BlockOut])
def list_my_blocks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    blocks = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.id)
        .order_by(Block.created_at.desc())
        .all()
    )
    out = []
    for b in blocks:
        target = db.get(User, b.blocked_id)
        out.append(BlockOut(
            id=b.id,
            blocker_id=b.blocker_id,
            blocked_id=b.blocked_id,
            blocked_email=target.email if target else None,
            blocked_name=_display_name(db, b.blocked_id),
            created_at=b.created_at,
        ))
    return out


@router.delete("/api/blocks/{blocked_user_id}", status_code=status.HTTP_204_NO_CONTENT)
def unblock_user(
    blocked_user_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    block = (
        db.query(Block)
        .filter(Block.blocker_id == current_user.id, Block.blocked_id == blocked_user_id)
        .first()
    )
    if not block:
        raise HTTPException(status_code=404, detail="Block not found")
    db.delete(block)
    db.commit()
    return None


def is_blocked_pair(db: Session, user_a_id: int, user_b_id: int) -> bool:
    """True if either user has blocked the other. Used by discovery
    (job board, search, map) and messaging to enforce blocks symmetrically —
    the block is directional to create, but it restricts both directions."""
    return db.query(Block).filter(
        or_(
            (Block.blocker_id == user_a_id) & (Block.blocked_id == user_b_id),
            (Block.blocker_id == user_b_id) & (Block.blocked_id == user_a_id),
        )
    ).first() is not None


def blocked_user_ids_involving(db: Session, user_id: int) -> set[int]:
    """All user ids that are blocked with respect to `user_id` in either
    direction — i.e. everyone who should be hidden from their discovery feeds."""
    rows = db.query(Block.blocker_id, Block.blocked_id).filter(
        or_(Block.blocker_id == user_id, Block.blocked_id == user_id)
    ).all()
    ids: set[int] = set()
    for blocker_id, blocked_id in rows:
        ids.add(blocker_id if blocker_id != user_id else blocked_id)
    return ids
