"""Lever — Push notifications via Firebase Cloud Messaging (HTTP v1).

Design: push is ADDITIVE and always SAFE. Without a configured service
account (settings.fcm_credentials_path) — or without the google-auth library
installed — send_push() is a no-op that returns 0. The app keeps working
exactly as before (in-app notifications + polling); once the user drops in
the Firebase credentials, the same call starts reaching closed apps.

Firebase setup steps live in docs/PUSH_SETUP.md.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from config import settings
from models import DeviceToken

logger = logging.getLogger("lever.push")

_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"
_FCM_ENDPOINT = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"

# Cached google-auth credentials + resolved project id (lazy, thread-safe).
_lock = threading.Lock()
_creds = None
_project_id: Optional[str] = None
_disabled_logged = False


def push_enabled() -> bool:
    return bool(settings.fcm_credentials_path)


def _load_credentials():
    """Return (credentials, project_id) or (None, None) if push can't run.
    Never raises — a misconfiguration degrades to no-op, it doesn't crash."""
    global _creds, _project_id, _disabled_logged
    if not settings.fcm_credentials_path:
        return None, None
    if _creds is not None:
        return _creds, _project_id
    with _lock:
        if _creds is not None:
            return _creds, _project_id
        try:
            from google.oauth2 import service_account  # type: ignore
        except Exception:
            if not _disabled_logged:
                logger.warning(
                    "Push: fcm_credentials_path is set but google-auth is not "
                    "installed — add 'google-auth' to requirements. Push disabled."
                )
                _disabled_logged = True
            return None, None
        try:
            with open(settings.fcm_credentials_path, "r", encoding="utf-8") as f:
                info = json.load(f)
            _project_id = info.get("project_id")
            _creds = service_account.Credentials.from_service_account_info(
                info, scopes=[_FCM_SCOPE]
            )
            logger.info(f"Push: FCM credentials loaded for project {_project_id}")
        except Exception as e:
            logger.error(f"Push: failed to load FCM credentials — disabled: {e}")
            _creds, _project_id = None, None
        return _creds, _project_id


def _access_token() -> Optional[str]:
    creds, _ = _load_credentials()
    if creds is None:
        return None
    try:
        from google.auth.transport.requests import Request  # type: ignore
        if not creds.valid:
            creds.refresh(Request())
        return creds.token
    except Exception as e:
        logger.error(f"Push: could not mint FCM access token: {e}")
        return None


def send_push(
    db: Session,
    user_id: int,
    title: str,
    body: str,
    link: Optional[str] = None,
    data: Optional[dict] = None,
) -> int:
    """Best-effort push to every device the user registered. Returns the
    number of devices delivered to (0 when push is disabled or the user has
    no devices). Prunes tokens FCM reports as permanently invalid.

    Fully swallow errors: a push failure must never break the request that
    triggered it — the in-app Notification is the source of truth."""
    if not push_enabled():
        return 0
    token = _access_token()
    project_id = _project_id
    if not token or not project_id:
        return 0

    rows = db.query(DeviceToken).filter(DeviceToken.user_id == user_id).all()
    if not rows:
        return 0

    url = _FCM_ENDPOINT.format(project_id=project_id)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload_data = {k: str(v) for k, v in (data or {}).items()}
    if link:
        payload_data["link"] = link

    delivered = 0
    dead: list[int] = []
    for row in rows:
        message = {
            "message": {
                "token": row.token,
                "notification": {"title": title, "body": body},
                "data": payload_data,
                "android": {"priority": "high", "notification": {"sound": "default"}},
            }
        }
        try:
            resp = httpx.post(url, headers=headers, json=message, timeout=8.0)
            if resp.status_code == 200:
                delivered += 1
            elif resp.status_code in (400, 403, 404):
                # UNREGISTERED / invalid token — stop sending to this device.
                dead.append(row.id)
                logger.info(f"Push: pruning dead token {row.id} (HTTP {resp.status_code})")
            else:
                logger.warning(f"Push: FCM {resp.status_code} for token {row.id}: {resp.text[:160]}")
        except Exception as e:
            logger.warning(f"Push: send error for token {row.id}: {e}")

    if dead:
        try:
            db.query(DeviceToken).filter(DeviceToken.id.in_(dead)).delete(synchronize_session=False)
            db.commit()
        except Exception:
            db.rollback()

    if delivered:
        logger.info(f"Push: delivered '{title}' to {delivered} device(s) for user {user_id}")
    return delivered
