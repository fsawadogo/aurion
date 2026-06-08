"""#324 — clip cadence floor: per-clip anchoring + silent-exam Stage 2.

Today Stage-2 clip processing short-circuits when there are no SPOKEN
triggers, so a silent physical exam yields no clip captions. And clip S3
keys carried no timestamp, so every clip was mis-anchored to
``trigger_segments[0]``. The cadence-floor change:

  * embeds ``timestamp_ms`` in the clip S3 key
    (``clips/{sid}/{ts:09d}_{clip_id}.mp4``);
  * ``retrieve_clips_for_triggers`` parses that real per-clip timestamp;
  * ``caption_visual_evidence`` anchors each clip against the FULL
    transcript (nearest segment by timestamp), synthesizing a silent
    empty-text anchor when the transcript is truly empty rather than
    dropping the clip;
  * the ``run_stage2_vision`` no-trigger short-circuit is relaxed so
    CLIPS_ONLY / HYBRID PROCEED with zero spoken triggers.

This suite locks each of those behaviors.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.v1 import vision as vision_api
from app.core.audit_events import AuditEventType
from app.core.types import (
    ClipMaskingMetadata,
    FrameCaption,
    MaskedClip,
    Note,
    NoteSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.config.schema import AppConfigSchema, VisualEvidenceMode
from app.modules.vision import service as vision_service

SESSION_ID = "00000000-0000-0000-0000-000000000042"


# ── Fixtures / helpers ──────────────────────────────────────────────────────


def _clip(s3_key: str, *, timestamp_ms: int = 0) -> MaskedClip:
    return MaskedClip(
        s3_key=s3_key,
        timestamp_ms=timestamp_ms,
        duration_ms=7000,
        trigger_segment_id="seg_001",
        masking_metadata=ClipMaskingMetadata(
            frames_total=210, frames_with_faces=210, faces_blurred=210
        ),
    )


def _caption(
    *,
    confidence: str = "high",
    confidence_reason: str = "clear",
    provider: str = "gemini",
    frame_id: str = "clip_cap",
    anchor_id: str = "seg_001",
) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id,
        session_id=SESSION_ID,
        timestamp_ms=14500,
        audio_anchor_id=anchor_id,
        provider_used=provider,
        visual_description="Patient demonstrated shoulder abduction.",
        confidence=confidence,
        confidence_reason=confidence_reason,
        integration_status="ENRICHES",
        evidence_kind="clip",
        duration_ms=7000,
    )


# ── retrieve_clips_for_triggers — per-clip timestamp parse ───────────────────


async def test_retrieve_clips_parses_embedded_timestamp(monkeypatch) -> None:
    """Each clip's timestamp_ms comes from its key prefix, NOT
    trigger_segments[0].start_ms."""
    keys = [
        f"clips/{SESSION_ID}/000014500_aabbccdd.mp4",
        f"clips/{SESSION_ID}/000030000_eeff0011.mp4",
    ]
    s3 = MagicMock()
    s3.list_objects_v2 = MagicMock(
        return_value={"Contents": [{"Key": k} for k in keys]}
    )
    monkeypatch.setattr(vision_service, "get_s3_client", lambda: s3)
    monkeypatch.setattr(vision_service, "get_config", AppConfigSchema)

    # A single trigger at 99000 — proves clips do NOT inherit its ts.
    trigger = TranscriptSegment(
        id="seg_trig", start_ms=99000, end_ms=99500, text="abduct",
        is_visual_trigger=True, trigger_type="motion",
    )
    clips = await vision_service.retrieve_clips_for_triggers(
        SESSION_ID, [trigger]
    )

    by_key = {c.s3_key: c.timestamp_ms for c in clips}
    assert by_key[keys[0]] == 14500
    assert by_key[keys[1]] == 30000


async def test_retrieve_clips_legacy_key_falls_back(monkeypatch) -> None:
    """A legacy key with no embedded timestamp falls back to the first
    trigger's start_ms (pre-#324 behavior preserved)."""
    legacy_key = f"clips/{SESSION_ID}/aabbccddeeff00112233445566778899.mp4"
    s3 = MagicMock()
    s3.list_objects_v2 = MagicMock(
        return_value={"Contents": [{"Key": legacy_key}]}
    )
    monkeypatch.setattr(vision_service, "get_s3_client", lambda: s3)
    monkeypatch.setattr(vision_service, "get_config", AppConfigSchema)

    trigger = TranscriptSegment(
        id="seg_trig", start_ms=99000, end_ms=99500, text="abduct",
        is_visual_trigger=True, trigger_type="motion",
    )
    clips = await vision_service.retrieve_clips_for_triggers(
        SESSION_ID, [trigger]
    )
    assert clips[0].timestamp_ms == 99000


# ── caption_visual_evidence — per-clip anchoring against full transcript ─────


async def test_clips_anchor_to_nearest_full_transcript_segment() -> None:
    """Each clip anchors to its NEAREST transcript segment by timestamp —
    including non-trigger (incidental-speech) segments — not segment[0]."""
    seg_early = TranscriptSegment(
        id="seg_early", start_ms=1000, end_ms=2000, text="okay let's begin"
    )
    seg_late = TranscriptSegment(
        id="seg_late", start_ms=29000, end_ms=30000, text="and now the knee"
    )
    clip_a = _clip(f"clips/{SESSION_ID}/000001200_a.mp4", timestamp_ms=1200)
    clip_b = _clip(f"clips/{SESSION_ID}/000029500_b.mp4", timestamp_ms=29500)

    provider = MagicMock()
    provider.caption_clip = AsyncMock(return_value=_caption())
    registry = MagicMock()
    registry.get_vision_provider_for_kind_with_fallback = MagicMock(
        return_value=provider
    )

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=AsyncMock()),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
    ):
        await vision_service.caption_visual_evidence(
            evidence=[clip_a, clip_b],
            trigger_segments=[],  # zero spoken triggers (silent exam)
            anchor_segments=[seg_early, seg_late],
        )

    # Map each clip's s3_key → the anchor segment id it was captioned with.
    anchored = {
        call.args[0].s3_key: call.args[1].id
        for call in provider.caption_clip.await_args_list
    }
    assert anchored[clip_a.s3_key] == "seg_early"
    assert anchored[clip_b.s3_key] == "seg_late"


async def test_empty_transcript_synthesizes_silent_anchor() -> None:
    """A clip with a truly silent transcript (zero segments) is captioned
    against a synthesized empty-text anchor — NOT dropped."""
    clip = _clip(f"clips/{SESSION_ID}/000005000_x.mp4", timestamp_ms=5000)

    provider = MagicMock()
    provider.caption_clip = AsyncMock(return_value=_caption(anchor_id="clip_silent_5000"))
    registry = MagicMock()
    registry.get_vision_provider_for_kind_with_fallback = MagicMock(
        return_value=provider
    )

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=AsyncMock()),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
    ):
        captions = await vision_service.caption_visual_evidence(
            evidence=[clip],
            trigger_segments=[],
            anchor_segments=[],  # truly silent
        )

    # Clip was captioned (not dropped).
    assert len(captions) == 1
    provider.caption_clip.assert_awaited_once()
    # The synthetic anchor carries empty text at the clip's own timestamp
    # — no fabricated audio context.
    anchor_arg = provider.caption_clip.await_args.args[1]
    assert anchor_arg.text == ""
    assert anchor_arg.start_ms == 5000
    assert anchor_arg.id == "clip_silent_5000"


async def test_low_confidence_cadence_clip_still_discarded() -> None:
    """A low-confidence cadence clip (silent transcript) still emits
    CLIP_DISCARDED — the existing discard path is unchanged."""
    clip = _clip(f"clips/{SESSION_ID}/000005000_x.mp4", timestamp_ms=5000)

    provider = MagicMock()
    provider.caption_clip = AsyncMock(
        return_value=_caption(confidence="low", confidence_reason="motion blur")
    )
    registry = MagicMock()
    registry.get_vision_provider_for_kind_with_fallback = MagicMock(
        return_value=provider
    )
    audit = AsyncMock()
    audit.write_event = AsyncMock()

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=audit),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
    ):
        captions = await vision_service.caption_visual_evidence(
            evidence=[clip],
            trigger_segments=[],
            anchor_segments=[],  # silent — synthetic anchor, then low conf
        )

    assert captions == []
    discards = [
        c for c in audit.write_event.await_args_list
        if c.kwargs.get("event_type") == AuditEventType.CLIP_DISCARDED
    ]
    assert len(discards) == 1
    assert discards[0].kwargs["s3_key"] == clip.s3_key
    assert discards[0].kwargs["confidence"] == "low"


# ── run_stage2_vision — relaxed no-trigger short-circuit ─────────────────────


def _transcript_json(*, with_trigger: bool) -> str:
    seg = TranscriptSegment(
        id="seg_001",
        start_ms=14000,
        end_ms=15000,
        text="examining the right shoulder",
        is_visual_trigger=with_trigger,
        trigger_type="motion" if with_trigger else None,
    )
    return Transcript(
        session_id=SESSION_ID, provider_used="whisper", segments=[seg]
    ).model_dump_json()


def _stage1_note() -> Note:
    return Note(
        session_id=SESSION_ID,
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.5,
        sections=[NoteSection(id="physical_exam", title="Physical Exam", status="pending_video")],
    )


def _db_for(transcript_json: str) -> MagicMock:
    """A mock AsyncSession: first execute → transcript row, second →
    session row (clinician_id None so the prompt lookups are skipped)."""
    transcript_row = MagicMock()
    transcript_row.transcript_json = transcript_json
    transcript_result = MagicMock()
    transcript_result.scalar_one_or_none.return_value = transcript_row

    session_row = MagicMock()
    session_row.clinician_id = None
    session_result = MagicMock()
    session_result.scalar_one_or_none.return_value = session_row

    db = MagicMock()
    db.execute = AsyncMock(side_effect=[transcript_result, session_result])
    return db


async def test_silent_exam_clips_only_runs_stage2() -> None:
    """Regression: zero is_visual_trigger segments + CLIPS_ONLY → Stage 2
    PROCEEDS (retrieves + captions clips) instead of short-circuiting."""
    db = _db_for(_transcript_json(with_trigger=False))
    session_uuid = uuid.UUID(SESSION_ID)

    mock_caption = AsyncMock(return_value=[_caption()])
    mock_retrieve_clips = AsyncMock(
        return_value=[_clip(f"clips/{SESSION_ID}/000005000_x.mp4", timestamp_ms=5000)]
    )
    mock_write_audit = AsyncMock()

    with (
        patch.object(vision_api, "resolve_evidence_mode", return_value=VisualEvidenceMode.CLIPS_ONLY),
        patch.object(vision_api, "get_latest_note", AsyncMock(return_value=_stage1_note())),
        patch.object(vision_api, "retrieve_clips_for_triggers", mock_retrieve_clips),
        patch.object(vision_api, "retrieve_frames_for_triggers", AsyncMock(return_value=[])),
        patch.object(vision_api, "caption_visual_evidence", mock_caption),
        patch.object(vision_api, "reconcile_captions", AsyncMock(side_effect=lambda caps, note, system_prompt=None: caps)),
        patch.object(vision_api, "create_note_version", AsyncMock()),
        patch.object(vision_api, "record_clip_metrics", AsyncMock()),
        patch.object(vision_api, "write_audit", mock_write_audit),
    ):
        resp = await vision_api.run_stage2_vision(session_uuid, db)

    # Stage 2 ran — clips retrieved + captioned.
    mock_retrieve_clips.assert_awaited_once()
    mock_caption.assert_awaited_once()
    # The full transcript was passed as the clip anchor pool.
    assert mock_caption.await_args.kwargs["anchor_segments"]
    # It did NOT short-circuit with the no-trigger reason.
    reasons = [
        c.kwargs.get("reason") for c in mock_write_audit.await_args_list
    ]
    assert "no_visual_triggers" not in reasons
    assert resp.enriches_count == 1


async def test_silent_exam_frames_only_still_short_circuits() -> None:
    """Frames are trigger-anchored, so FRAMES_ONLY + zero triggers still
    fast-skips (no retrieval, STAGE2_COMPLETE reason=no_visual_triggers)."""
    db = _db_for(_transcript_json(with_trigger=False))
    session_uuid = uuid.UUID(SESSION_ID)

    mock_caption = AsyncMock(return_value=[])
    mock_retrieve_clips = AsyncMock(return_value=[])
    mock_write_audit = AsyncMock()

    with (
        patch.object(vision_api, "resolve_evidence_mode", return_value=VisualEvidenceMode.FRAMES_ONLY),
        patch.object(vision_api, "get_latest_note", AsyncMock(return_value=_stage1_note())),
        patch.object(vision_api, "retrieve_clips_for_triggers", mock_retrieve_clips),
        patch.object(vision_api, "retrieve_frames_for_triggers", AsyncMock(return_value=[])),
        patch.object(vision_api, "caption_visual_evidence", mock_caption),
        patch.object(vision_api, "write_audit", mock_write_audit),
    ):
        resp = await vision_api.run_stage2_vision(session_uuid, db)

    # Short-circuited — no retrieval, no captioning.
    mock_retrieve_clips.assert_not_awaited()
    mock_caption.assert_not_awaited()
    reasons = [
        c.kwargs.get("reason") for c in mock_write_audit.await_args_list
    ]
    assert "no_visual_triggers" in reasons
    assert resp.frames_processed == 0
