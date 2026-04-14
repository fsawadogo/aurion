"""WebSocket endpoint for real-time note delivery.

Provides ws://host/ws/notes/{session_id} for Stage 1 and Stage 2
note delivery to connected clients. The note_gen service calls
notify_stage1_delivered() to push notes to all clients subscribed
to a session.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.types import Note

logger = logging.getLogger("aurion.websocket")

router = APIRouter(tags=["websocket"])


# ── Connection Manager ───────────────────────────────────────────────────


class ConnectionManager:
    """Tracks active WebSocket connections per session_id.

    Thread-safe for single-process async usage (FastAPI with uvicorn).
    """

    def __init__(self) -> None:
        # session_id -> list of active WebSocket connections
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, session_id: str, websocket: WebSocket) -> None:
        """Accept and register a WebSocket connection for a session."""
        await websocket.accept()
        if session_id not in self._connections:
            self._connections[session_id] = []
        self._connections[session_id].append(websocket)
        logger.info(
            "WebSocket connected: session=%s total_connections=%d",
            session_id,
            len(self._connections[session_id]),
        )

    def disconnect(self, session_id: str, websocket: WebSocket) -> None:
        """Unregister a WebSocket connection for a session."""
        conns = self._connections.get(session_id, [])
        if websocket in conns:
            conns.remove(websocket)
        if not conns:
            self._connections.pop(session_id, None)
        logger.info(
            "WebSocket disconnected: session=%s remaining=%d",
            session_id,
            len(self._connections.get(session_id, [])),
        )

    async def broadcast_to_session(self, session_id: str, data: dict[str, Any]) -> None:
        """Send JSON data to all connected clients for a session.

        Silently removes connections that have been closed.
        """
        conns = self._connections.get(session_id, [])
        if not conns:
            logger.debug(
                "No WebSocket clients connected for session=%s, skipping broadcast",
                session_id,
            )
            return

        message = json.dumps(data, default=str)
        stale: list[WebSocket] = []

        for ws in conns:
            try:
                await ws.send_text(message)
            except Exception:
                stale.append(ws)

        # Clean up stale connections
        for ws in stale:
            self.disconnect(session_id, ws)

        logger.info(
            "Broadcast to session=%s: %d clients reached, %d stale removed",
            session_id,
            len(conns) - len(stale),
            len(stale),
        )

    def get_connection_count(self, session_id: str) -> int:
        """Return the number of active connections for a session."""
        return len(self._connections.get(session_id, []))


# Module-level singleton
manager = ConnectionManager()


# ── WebSocket Route ──────────────────────────────────────────────────────


@router.websocket("/ws/notes/{session_id}")
async def notes_websocket(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for real-time note delivery.

    Clients connect to receive Stage 1 and Stage 2 note updates
    as they are generated. The connection stays open until the
    client disconnects.

    Messages from the client are accepted but not processed --
    this is a server-push channel.
    """
    await manager.connect(session_id, websocket)
    try:
        # Keep the connection alive by reading client messages.
        # We don't process them -- this is a push-only channel.
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(session_id, websocket)


# ── Public API for Other Modules ─────────────────────────────────────────


async def notify_stage1_delivered(session_id: str, note: Note) -> None:
    """Notify all connected clients that Stage 1 note is ready.

    Called by the note_gen service after Stage 1 generation completes.
    """
    payload = {
        "event": "stage1_delivered",
        "session_id": session_id,
        "note": note.model_dump(),
    }
    await manager.broadcast_to_session(session_id, payload)
    logger.info("Stage 1 delivery notification sent: session=%s", session_id)


async def notify_stage2_delivered(session_id: str, note: Note) -> None:
    """Notify all connected clients that Stage 2 note is ready.

    Called after Stage 2 visual enrichment completes.
    """
    payload = {
        "event": "stage2_delivered",
        "session_id": session_id,
        "note": note.model_dump(),
    }
    await manager.broadcast_to_session(session_id, payload)
    logger.info("Stage 2 delivery notification sent: session=%s", session_id)
