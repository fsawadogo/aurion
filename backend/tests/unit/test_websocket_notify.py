"""#277 — the Stage 1 delivery push that advances the iOS processing
screen past 95%.

`notify_stage1_delivered` was dead code (zero callers); the transcription
route now calls it after STAGE1_DELIVERED. These tests lock:
  - a connected client actually receives the `stage1_delivered` frame,
  - a failing client cannot propagate an error out of the push (the note
    is already persisted; a WS hiccup must never fail the request),
  - no connected clients is a safe no-op.
"""

from __future__ import annotations

import json

import pytest

from app.api.v1.websocket import manager, notify_stage1_delivered
from app.core.types import Note


def _note() -> Note:
    return Note(
        session_id="00000000-0000-0000-0000-000000000000",
        stage=1,
        provider_used="anthropic",
        specialty="test_specialty",
        sections=[],
    )


class _FakeWebSocket:
    """Records messages sent to it. `connect()` calls accept() (async)."""

    def __init__(self, *, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    async def accept(self) -> None:  # noqa: D401 — protocol stub
        pass

    async def send_text(self, message: str) -> None:
        if self.fail:
            raise RuntimeError("socket closed")
        self.sent.append(json.loads(message))


@pytest.mark.asyncio
async def test_notify_stage1_delivered_reaches_connected_client():
    session_id = "11111111-1111-1111-1111-111111111111"
    ws = _FakeWebSocket()
    await manager.connect(session_id, ws)
    try:
        await notify_stage1_delivered(session_id, _note())
        assert len(ws.sent) == 1
        assert ws.sent[0]["event"] == "stage1_delivered"
        assert ws.sent[0]["session_id"] == session_id
        assert "note" in ws.sent[0]
    finally:
        manager.disconnect(session_id, ws)


@pytest.mark.asyncio
async def test_failing_client_is_swallowed():
    session_id = "22222222-2222-2222-2222-222222222222"
    bad = _FakeWebSocket(fail=True)
    await manager.connect(session_id, bad)
    # Must NOT raise — the note is already persisted; a WS failure is non-fatal.
    await notify_stage1_delivered(session_id, _note())
    # The broadcast removes stale clients.
    assert manager.get_connection_count(session_id) == 0


@pytest.mark.asyncio
async def test_no_clients_noop():
    session_id = "33333333-3333-3333-3333-333333333333"
    assert manager.get_connection_count(session_id) == 0
    # No subscribers → no-op, no raise.
    await notify_stage1_delivered(session_id, _note())
