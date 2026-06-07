"""Unit tests for the cleanup service (#338 — windowed media retention).

Covers the pieces this PR added / fixed:
  * the frame-prefix bug fix (`frames/{sid}/` now matches; the old flat
    `{sid}/` matched nothing) — a regression guard that would fail on the
    pre-PR code,
  * `_purge_evidence_under_prefix(bucket=...)` honoring the bucket
    override (the generalization that lets the audio purge reuse it),
  * `purge_audio_for_session` listing `audio/{sid}/` against AUDIO_BUCKET
    and emitting AUDIO_PURGED with an `audio_count` (not an `s3_key`),
  * `purge_session_media` orchestrating all five legs non-fatally.

The S3 client + audit log are mocked, so these run with no LocalStack /
DynamoDB. The boto3 paginator shape (`get_paginator(...).paginate(...)`)
is mirrored so the prefix/bucket arguments can be asserted.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit_events import AuditEventType
from app.core.s3 import AUDIO_BUCKET, FRAMES_BUCKET
from app.modules.cleanup import service as cleanup


def _client_with_objects(keys: list[str]) -> MagicMock:
    """A MagicMock S3 client whose paginator yields one page containing
    ``keys``. Captures paginate/delete_objects call args for assertions."""
    client = MagicMock()
    page = {"Contents": [{"Key": k} for k in keys]} if keys else {}
    paginator = MagicMock()
    paginator.paginate.return_value = [page]
    client.get_paginator.return_value = paginator
    client.delete_objects.return_value = {"Deleted": [{"Key": k} for k in keys]}
    return client


def _mock_audit() -> AsyncMock:
    audit = AsyncMock()
    audit.write_event = AsyncMock(return_value={})
    return audit


# ── Frame-prefix bug fix (regression guard) ────────────────────────────────


def test_frame_prefix_is_namespaced_now() -> None:
    """REGRESSION (#338): the frame prefix must be `frames/{sid}/`. The
    pre-PR template was a flat `{sid}/` which matched NOTHING under the
    real `frames/{sid}/{ts}.jpg` layout — this assertion fails on the old
    code."""
    sid = "11111111-1111-1111-1111-111111111111"
    assert cleanup._evidence_prefix("frame", sid) == f"frames/{sid}/"


def test_clip_and_screen_prefixes() -> None:
    sid = "22222222-2222-2222-2222-222222222222"
    assert cleanup._evidence_prefix("clip", sid) == f"clips/{sid}/"
    assert cleanup._evidence_prefix("screen", sid) == f"screen_frames/{sid}/"


@pytest.mark.asyncio
async def test_purge_frames_lists_namespaced_prefix() -> None:
    """Behavioral proof of the fix: purge_frames now paginates the
    `frames/{sid}/` prefix (would have listed `{sid}/` before)."""
    sid = str(uuid.uuid4())
    client = _client_with_objects([f"frames/{sid}/14500.jpg"])
    audit = _mock_audit()
    with (
        patch.object(cleanup, "get_s3_client", return_value=client),
        patch.object(cleanup, "get_audit_log_service", return_value=audit),
    ):
        await cleanup.purge_frames(sid)

    _, paginate_kwargs = client.get_paginator.return_value.paginate.call_args
    assert paginate_kwargs["Bucket"] == FRAMES_BUCKET
    assert paginate_kwargs["Prefix"] == f"frames/{sid}/"


# ── _purge_evidence_under_prefix bucket override ───────────────────────────


@pytest.mark.asyncio
async def test_purge_evidence_under_prefix_default_bucket_is_frames() -> None:
    sid = str(uuid.uuid4())
    client = _client_with_objects([f"frames/{sid}/1.jpg"])
    with patch.object(cleanup, "get_s3_client", return_value=client):
        deleted, failed = await cleanup._purge_evidence_under_prefix(
            session_id=sid,
            prefix=f"frames/{sid}/",
            operation_label="s3_delete_frames",
        )

    assert deleted == [f"frames/{sid}/1.jpg"]
    assert failed == []
    _, paginate_kwargs = client.get_paginator.return_value.paginate.call_args
    assert paginate_kwargs["Bucket"] == FRAMES_BUCKET
    # delete_objects also targeted the frames bucket.
    _, delete_kwargs = client.delete_objects.call_args
    assert delete_kwargs["Bucket"] == FRAMES_BUCKET


@pytest.mark.asyncio
async def test_purge_evidence_under_prefix_honors_bucket_override() -> None:
    """The bucket override flows to BOTH paginate and delete_objects so
    the audio purge can reuse this helper against AUDIO_BUCKET."""
    sid = str(uuid.uuid4())
    client = _client_with_objects([f"audio/{sid}/a.wav"])
    with patch.object(cleanup, "get_s3_client", return_value=client):
        deleted, failed = await cleanup._purge_evidence_under_prefix(
            session_id=sid,
            prefix=f"audio/{sid}/",
            operation_label="s3_delete_audio",
            bucket=AUDIO_BUCKET,
        )

    assert deleted == [f"audio/{sid}/a.wav"]
    assert failed == []
    _, paginate_kwargs = client.get_paginator.return_value.paginate.call_args
    assert paginate_kwargs["Bucket"] == AUDIO_BUCKET
    _, delete_kwargs = client.delete_objects.call_args
    assert delete_kwargs["Bucket"] == AUDIO_BUCKET


# ── purge_audio_for_session ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_audio_for_session_lists_audio_prefix_and_audits_count() -> None:
    sid = str(uuid.uuid4())
    client = _client_with_objects(
        [f"audio/{sid}/one.wav", f"audio/{sid}/two.wav"]
    )
    audit = _mock_audit()
    with (
        patch.object(cleanup, "get_s3_client", return_value=client),
        patch.object(cleanup, "get_audit_log_service", return_value=audit),
    ):
        await cleanup.purge_audio_for_session(sid)

    # Listed audio/{sid}/ in the AUDIO bucket.
    _, paginate_kwargs = client.get_paginator.return_value.paginate.call_args
    assert paginate_kwargs["Bucket"] == AUDIO_BUCKET
    assert paginate_kwargs["Prefix"] == f"audio/{sid}/"

    # Emitted AUDIO_PURGED with a count, NOT a per-object s3_key.
    audit.write_event.assert_awaited()
    purged = [
        c
        for c in audit.write_event.await_args_list
        if c.kwargs.get("event_type") == AuditEventType.AUDIO_PURGED
    ]
    assert len(purged) == 1
    kwargs = purged[0].kwargs
    assert kwargs["bucket"] == AUDIO_BUCKET
    assert kwargs["audio_count"] == 2
    assert "s3_key" not in kwargs


@pytest.mark.asyncio
async def test_purge_audio_for_session_zero_objects_audits_zero_count() -> None:
    """No audio object (already purged / never uploaded) still emits a
    0-count AUDIO_PURGED row — the purge attempt belongs in the trail."""
    sid = str(uuid.uuid4())
    client = _client_with_objects([])
    audit = _mock_audit()
    with (
        patch.object(cleanup, "get_s3_client", return_value=client),
        patch.object(cleanup, "get_audit_log_service", return_value=audit),
    ):
        await cleanup.purge_audio_for_session(sid)

    purged = [
        c
        for c in audit.write_event.await_args_list
        if c.kwargs.get("event_type") == AuditEventType.AUDIO_PURGED
    ]
    assert len(purged) == 1
    assert purged[0].kwargs["audio_count"] == 0


# ── purge_session_media orchestration ──────────────────────────────────────


@pytest.mark.asyncio
async def test_purge_session_media_runs_all_five_legs() -> None:
    sid = str(uuid.uuid4())
    with (
        patch.object(cleanup, "migrate_eval_frames", new=AsyncMock()) as m_frames,
        patch.object(cleanup, "migrate_eval_clips", new=AsyncMock()) as m_clips,
        patch.object(cleanup, "purge_frames", new=AsyncMock()) as p_frames,
        patch.object(cleanup, "purge_clips", new=AsyncMock()) as p_clips,
        patch.object(
            cleanup, "purge_audio_for_session", new=AsyncMock()
        ) as p_audio,
    ):
        await cleanup.purge_session_media(sid)

    for mock in (m_frames, m_clips, p_frames, p_clips, p_audio):
        mock.assert_awaited_once_with(sid)


@pytest.mark.asyncio
async def test_purge_session_media_is_non_fatal_per_leg() -> None:
    """A failing leg is logged and swallowed; the remaining legs still
    run and the orchestrator never raises (S3 TTL is the backstop)."""
    sid = str(uuid.uuid4())
    with (
        patch.object(
            cleanup,
            "migrate_eval_frames",
            new=AsyncMock(side_effect=RuntimeError("boom")),
        ),
        patch.object(cleanup, "migrate_eval_clips", new=AsyncMock()),
        patch.object(cleanup, "purge_frames", new=AsyncMock()),
        patch.object(cleanup, "purge_clips", new=AsyncMock()),
        patch.object(
            cleanup, "purge_audio_for_session", new=AsyncMock()
        ) as p_audio,
    ):
        # Must not raise even though the first leg blew up.
        await cleanup.purge_session_media(sid)

    # The audio purge (last leg) still ran.
    p_audio.assert_awaited_once_with(sid)
