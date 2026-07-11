"""Lever — WebSocket connection manager for real-time messaging.

CIA Triad Alignment:
  Confidentiality: JWT token validation on WebSocket connect; messages scoped to job participants
  Integrity:       Messages persisted to DB before broadcast; connection tracking prevents ghost sends
  Availability:    Graceful disconnect handling; connection pool with cleanup

ISO 27001 Controls:
  A.9.4.2   Secure log-on procedures (JWT auth on WS handshake)
  A.13.1.1  Network controls (message routing scoped to authorized participants)
  A.12.4.1  Event logging
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Set

from fastapi import WebSocket

logger = logging.getLogger("lever.websocket")


class ConnectionManager:
    """Manages WebSocket connections grouped by job_id.

    Each job has a set of connected clients (user_ids).
    Messages are broadcast only to participants of the same job.
    """

    def __init__(self):
        # job_id -> {user_id: WebSocket}
        self._connections: Dict[int, Dict[int, WebSocket]] = defaultdict(dict)

    async def connect(self, websocket: WebSocket, job_id: int, user_id: int, already_accepted: bool = False):
        """Accept and register a WebSocket connection."""
        if not already_accepted:
            await websocket.accept()
        self._connections[job_id][user_id] = websocket
        logger.info(f"WS connected: user={user_id} job={job_id} (total={self._count_for_job(job_id)})")

    def disconnect(self, job_id: int, user_id: int):
        """Remove a WebSocket connection."""
        if job_id in self._connections:
            self._connections[job_id].pop(user_id, None)
            if not self._connections[job_id]:
                del self._connections[job_id]
        logger.info(f"WS disconnected: user={user_id} job={job_id}")

    async def broadcast_to_job(self, job_id: int, message: dict, exclude_user: int | None = None):
        """Send a message to all connected users in a job, except the sender."""
        if job_id not in self._connections:
            return

        disconnected = []
        for uid, ws in self._connections[job_id].items():
            if uid == exclude_user:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(uid)

        # Cleanup dead connections
        for uid in disconnected:
            self._connections[job_id].pop(uid, None)
            logger.info(f"WS cleaned dead connection: user={uid} job={job_id}")

    async def send_to_user(self, job_id: int, user_id: int, message: dict):
        """Send a message to a specific user in a job."""
        ws = self._connections.get(job_id, {}).get(user_id)
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self.disconnect(job_id, user_id)

    def is_connected(self, job_id: int, user_id: int) -> bool:
        """Check if a user is connected to a job."""
        return user_id in self._connections.get(job_id, {})

    def get_connected_users(self, job_id: int) -> Set[int]:
        """Get all connected user IDs for a job."""
        return set(self._connections.get(job_id, {}).keys())

    def _count_for_job(self, job_id: int) -> int:
        return len(self._connections.get(job_id, {}))


# Global singleton
manager = ConnectionManager()
