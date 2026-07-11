"""Lever — WebSocket endpoint for real-time job messaging.

Clients connect to /ws/messages/{job_id}?token={jwt_token}
Messages are persisted to DB and broadcast to job participants.

CIA Triad:
  Confidentiality: JWT auth required; only job participants can connect
  Integrity:       Messages saved to DB before broadcast
  Availability:    Graceful disconnect; dead connection cleanup
"""
from __future__ import annotations

import json
from typing import Optional
import logging
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from auth import decode_token
from database import SessionLocal
from models import Job, Message, ServiceRequest, User, Notification
from websocket_manager import manager

logger = logging.getLogger("lever.ws")

router = APIRouter()


def _get_job_participants(db: Session, job_id: int) -> set[int]:
    """Return the set of user IDs authorized to message in this job."""
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        return set()
    request = db.query(ServiceRequest).filter(ServiceRequest.id == job.request_id).first()
    if not request:
        return set()
    return {request.client_id, job.mechanic_id}



async def _authenticate_ws(websocket, token):
    """Authenticate via token param OR first message."""
    if token:
        try:
            payload = decode_token(token)
            return int(payload.get("sub"))
        except Exception:
            await websocket.close(code=4001, reason="Invalid token")
            return None
    try:
        data = await websocket.receive_text()
        msg = json.loads(data)
        if msg.get("type") != "auth" or not msg.get("token"):
            await websocket.close(code=4001, reason="First message must be auth")
            return None
        payload = decode_token(msg["token"])
        return int(payload.get("sub"))
    except Exception:
        await websocket.close(code=4001, reason="Authentication failed")
        return None

@router.websocket("/ws/messages/{job_id}")
async def websocket_messages(
    websocket: WebSocket,
    job_id: int,
    token: Optional[str] = Query(None),
):
    """WebSocket endpoint for real-time job messaging.

    Protocol:
      Connect:  ws://host/ws/messages/{job_id}?token={jwt}
      Send:     {"content": "message text"}
      Receive:  {"type": "message", "id": int, "sender_id": int, "content": str, "created_at": str}
      Receive:  {"type": "read_receipt", "message_ids": [int]}
    """
    # Accept connection first, then authenticate
    await websocket.accept()

    user_id = await _authenticate_ws(websocket, token)
    if user_id is None:
        return

    # Verify user exists and is active
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id, User.is_active == True).first()
        if not user:
            await websocket.close(code=4001, reason="User not found")
            return

        # Verify user is a participant of this job
        participants = _get_job_participants(db, job_id)
        if user_id not in participants:
            await websocket.close(code=4003, reason="Not a participant of this job")
            return
    finally:
        db.close()

    # Accept connection
    await manager.connect(websocket, job_id, user_id, already_accepted=True)

    try:
        while True:
            data = await websocket.receive_text()
            try:
                msg_data = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            content = msg_data.get("content", "").strip()
            if not content:
                await websocket.send_json({"type": "error", "message": "Empty message"})
                continue

            if len(content) > 4000:
                await websocket.send_json({"type": "error", "message": "Message too long (max 4000 chars)"})
                continue

            # Persist message to database
            db = SessionLocal()
            try:
                message = Message(
                    job_id=job_id,
                    sender_id=user_id,
                    content=content,
                )
                db.add(message)
                db.flush()

                # Create notification for the other participant
                other_participants = participants - {user_id}
                for other_id in other_participants:
                    if not manager.is_connected(job_id, other_id):
                        # Only create notification if recipient is not connected
                        notif = Notification(
                            user_id=other_id,
                            type="message",
                            title="New Message",
                            message=f"New message in job #{job_id}",
                            link=f"/job/{job_id}",
                        )
                        db.add(notif)

                db.commit()
                db.refresh(message)

                broadcast_msg = {
                    "type": "message",
                    "id": message.id,
                    "sender_id": user_id,
                    "content": content,
                    "created_at": message.created_at.isoformat(),
                }
            finally:
                db.close()

            # Broadcast to all participants in this job
            await manager.broadcast_to_job(job_id, broadcast_msg)

    except WebSocketDisconnect:
        manager.disconnect(job_id, user_id)
    except Exception as e:
        logger.error(f"WS error: user={user_id} job={job_id}: {e}")
        manager.disconnect(job_id, user_id)
