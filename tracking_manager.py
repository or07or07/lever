"""Lever — GPS Tracking WebSocket connection manager.

Manages real-time location streaming between providers and clients.
Separate from the messaging ConnectionManager to keep concerns clean.

Protocol:
  Provider sends:   {"type": "location", "latitude": ..., "longitude": ..., ...}
  Client receives:  {"type": "location_update", "latitude": ..., "longitude": ..., ...}
  Provider sends:   {"type": "tracking_stop"}
  Client receives:  {"type": "tracking_stopped"}

CIA Triad:
  Confidentiality: Only job participants can connect; JWT auth on handshake
  Integrity:       Server validates coords before broadcast; server-side timestamps
  Availability:    Dead connection cleanup; graceful disconnect handling
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, Optional, Set

from fastapi import WebSocket

logger = logging.getLogger("lever.tracking")


class TrackingManager:
    """Manages WebSocket connections for GPS live tracking per job.

    Structure:
        _connections[job_id] = {
            "provider": WebSocket | None,
            "clients": {user_id: WebSocket, ...}
        }
    """

    def __init__(self):
        self._connections: Dict[int, Dict] = {}

    def _ensure_job(self, job_id: int):
        if job_id not in self._connections:
            self._connections[job_id] = {"provider": None, "provider_id": None, "clients": {}}

    async def connect_provider(self, websocket: WebSocket, job_id: int, user_id: int, already_accepted: bool = False):
        """Register the provider's tracking WebSocket for a job."""
        if not already_accepted:
            await websocket.accept()
        self._ensure_job(job_id)
        self._connections[job_id]["provider"] = websocket
        self._connections[job_id]["provider_id"] = user_id
        logger.info(f"Tracking: provider {user_id} connected for job {job_id}")

        # Notify connected clients that tracking has started
        await self.broadcast_to_clients(job_id, {
            "type": "tracking_started",
            "provider_user_id": user_id,
        })

    async def connect_client(self, websocket: WebSocket, job_id: int, user_id: int, already_accepted: bool = False):
        """Register a client's WebSocket to receive location updates."""
        if not already_accepted:
            await websocket.accept()
        self._ensure_job(job_id)
        self._connections[job_id]["clients"][user_id] = websocket
        logger.info(f"Tracking: client {user_id} watching job {job_id}")

    def disconnect_provider(self, job_id: int, user_id: int):
        """Remove provider from tracking."""
        if job_id in self._connections:
            self._connections[job_id]["provider"] = None
            self._connections[job_id]["provider_id"] = None
            if not self._connections[job_id]["clients"]:
                del self._connections[job_id]
        logger.info(f"Tracking: provider {user_id} disconnected from job {job_id}")

    def disconnect_client(self, job_id: int, user_id: int):
        """Remove a client from tracking."""
        if job_id in self._connections:
            self._connections[job_id]["clients"].pop(user_id, None)
            if not self._connections[job_id]["clients"] and not self._connections[job_id]["provider"]:
                del self._connections[job_id]
        logger.info(f"Tracking: client {user_id} stopped watching job {job_id}")

    async def broadcast_to_clients(self, job_id: int, message: dict):
        """Send a message to all clients watching a job."""
        if job_id not in self._connections:
            return

        disconnected = []
        for uid, ws in self._connections[job_id]["clients"].items():
            try:
                await ws.send_json(message)
            except Exception:
                disconnected.append(uid)

        for uid in disconnected:
            self._connections[job_id]["clients"].pop(uid, None)
            logger.info(f"Tracking: cleaned dead client {uid} for job {job_id}")

    async def send_to_provider(self, job_id: int, message: dict):
        """Send a message to the provider (e.g., client acknowledged)."""
        if job_id not in self._connections:
            return
        ws = self._connections[job_id]["provider"]
        if ws:
            try:
                await ws.send_json(message)
            except Exception:
                self._connections[job_id]["provider"] = None

    def is_provider_tracking(self, job_id: int) -> bool:
        """Check if a provider is actively broadcasting for a job."""
        return (
            job_id in self._connections
            and self._connections[job_id]["provider"] is not None
        )

    def get_tracking_provider_id(self, job_id: int) -> Optional[int]:
        """Get the user_id of the provider tracking a job."""
        if job_id in self._connections:
            return self._connections[job_id].get("provider_id")
        return None

    def get_watching_clients(self, job_id: int) -> Set[int]:
        """Get user IDs of clients watching a job."""
        if job_id in self._connections:
            return set(self._connections[job_id]["clients"].keys())
        return set()

    def get_active_tracking_jobs(self) -> list[int]:
        """List all jobs with active provider tracking."""
        return [
            jid for jid, conn in self._connections.items()
            if conn["provider"] is not None
        ]


# Global singleton
tracking_manager = TrackingManager()
