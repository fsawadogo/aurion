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

    Called from the transcription route after Stage 1 generation completes
    and the session transitions to AWAITING_REVIEW (#277 — this is the
    signal the iOS processing screen waits on to advance past 95%).

    Best-effort: a serialization or broadcast failure must NEVER propagate
    into the request that triggered it (the note is already persisted and
    the 200 has the same meaning regardless). Mirrors notify_stage2_progress.
    """
    try:
        payload = {
            "event": "stage1_delivered",
            "session_id": session_id,
            "note": note.model_dump(),
        }
        await manager.broadcast_to_session(session_id, payload)
        logger.info("Stage 1 delivery notification sent: session=%s", session_id)
    except Exception as exc:  # noqa: BLE001 — best-effort push, never fatal
        logger.error(
            "Stage 1 delivery notification failed (non-fatal): session=%s err=%s",
            session_id,
            type(exc).__name__,
        )


async def notify_stage2_delivered(session_id: str, note: Note) -> None:
    """Notify all connected clients that Stage 2 note is ready.

    Best-effort, same non-fatal contract as notify_stage1_delivered.
    """
    try:
        payload = {
            "event": "stage2_delivered",
            "session_id": session_id,
            "note": note.model_dump(),
        }
        await manager.broadcast_to_session(session_id, payload)
        logger.info("Stage 2 delivery notification sent: session=%s", session_id)
    except Exception as exc:  # noqa: BLE001 — best-effort push, never fatal
        logger.error(
            "Stage 2 delivery notification failed (non-fatal): session=%s err=%s",
            session_id,
            type(exc).__name__,
        )


async def notify_stage2_progress(
    session_id: str, frames_processed: int, frames_total: int
) -> None:
    """Notify clients about incremental Stage 2 progress.

    Emitted by the vision pipeline as frames are captioned. iOS keeps
    polling /notes/{id}/stage2-status for the same data (event is
    additive — backward compatible). Web subscribes to the WebSocket
    and renders a live progress bar.

    Best-effort: a broadcast failure does not abort the underlying
    vision pipeline. We log + swallow.
    """
    payload = {
        "event": "stage2_progress",
        "session_id": session_id,
        "frames_processed": frames_processed,
        "frames_total": frames_total,
    }
    try:
        await manager.broadcast_to_session(session_id, payload)
    except Exception as exc:
        logger.warning(
            "stage2_progress broadcast failed (non-fatal): session=%s error=%s",
            session_id, exc,
        )
