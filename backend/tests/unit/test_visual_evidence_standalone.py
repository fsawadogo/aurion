"""Standalone visual evidence — the video stream can carry a note when the
audio transcript is empty/thin (video-import path), behind
``visual_evidence_standalone_enabled`` (DARK).

Covers the four gates the feature relaxes, each fail-safe / flag-gated:
  1. Empty audio no longer HARD-FAILS — a minimal empty note is laid down.
  2. Frame extraction FORCES cadence for a silent import (+ duration fallback).
  3. A face-less frame is KEPT after a fail-closed secondary text redaction.
  4. (structural) the merge routes a visual-only note through the video-note
     path — asserted via the guard that the flag OFF changes nothing.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import cv2
import numpy as np
import pytest

import app.api.v1.video_import as vi
from app.modules.video_import import masking

# ── 3. Masking: keep-faceless + fail-closed secondary redaction ─────────────


def _solid_jpg() -> bytes:
    img = np.full((80, 120, 3), 255, np.uint8)
    ok, buf = cv2.imencode(".jpg", img)
    assert ok
    return buf.tobytes()


def test_faceless_frame_dropped_without_redact() -> None:
    """Default (redact off): a zero-face frame is dropped — unchanged."""
    with patch.object(masking, "_detect_faces", return_value=[]):
        r = masking.mask_frame(
            _solid_jpg(), drop_zero_face=True, redact_faceless=False
        )
    assert r.status == "failed"
    assert r.reason == "no_face_detected"


def test_faceless_frame_kept_and_text_redacted() -> None:
    """redact on + text found: frame KEPT, text region blurred, count set."""
    with patch.object(masking, "_detect_faces", return_value=[]), patch.object(
        masking, "_detect_text_regions", return_value=[(10, 10, 40, 15)]
    ):
        r = masking.mask_frame(_solid_jpg(), redact_faceless=True)
    assert r.status == "success"
    assert r.image_bytes is not None
    assert r.faces_detected == 0
    assert r.text_regions_redacted == 1


def test_faceless_redact_fail_closed_when_detector_absent() -> None:
    """The safety invariant: no text detector → DROP, never store un-scrubbed."""
    with patch.object(masking, "_detect_faces", return_value=[]), patch.object(
        masking,
        "_detect_text_regions",
        side_effect=RuntimeError("east_model_absent"),
    ):
        r = masking.mask_frame(_solid_jpg(), redact_faceless=True)
    assert r.status == "failed"
    assert r.reason == "text_redaction_unavailable"
    assert r.image_bytes is None


def test_faceless_redact_clean_frame_kept_zero_regions() -> None:
    """A face-free, text-free close-up (knee/foot) is kept with 0 redactions."""
    with patch.object(masking, "_detect_faces", return_value=[]), patch.object(
        masking, "_detect_text_regions", return_value=[]
    ):
        r = masking.mask_frame(_solid_jpg(), redact_faceless=True)
    assert r.status == "success"
    assert r.text_regions_redacted == 0
    assert r.image_bytes is not None


def test_face_present_unaffected_by_redact_flag() -> None:
    """A frame WITH a face is blurred exactly as before — redact is faceless-only."""
    with patch.object(masking, "_detect_faces", return_value=[(10, 10, 30, 30)]):
        r = masking.mask_frame(_solid_jpg(), redact_faceless=True)
    assert r.status == "success"
    assert r.faces_detected == 1
    assert r.faces_blurred == 1
    assert r.text_regions_redacted == 0


# ── 1. Minimal empty note (empty audio no longer hard-fails) ────────────────


@pytest.mark.asyncio
async def test_minimal_note_all_sections_not_captured() -> None:
    from app.modules.note_gen import service

    db = AsyncMock()
    with patch.object(
        service, "create_note_version", new_callable=AsyncMock
    ) as cnv:
        note = await service.build_and_persist_minimal_note(
            specialty="orthopedic_surgery",
            session_id=str(uuid.uuid4()),
            db=db,
        )
    # No provider call was made — the note is honest and empty.
    assert note.provider_used == "none"
    assert note.completeness_score == 0.0
    assert note.stage == 1
    assert len(note.sections) > 0
    assert all(s.status == "not_captured" for s in note.sections)
    assert all(not s.claims for s in note.sections)
    cnv.assert_awaited_once()


# ── 2. Forced cadence + duration fallback for a silent import ────────────────


def _db_with_transcript(sid, *, trigger: bool, duration_ms: int = 30_000):
    from app.core.types import Transcript, TranscriptSegment

    segs = (
        [
            TranscriptSegment(
                id="seg_001",
                start_ms=0,
                end_ms=duration_ms,
                text="rom" if trigger else "",
                is_visual_trigger=trigger,
            )
        ]
        if trigger
        else []  # truly-silent transcript: zero segments
    )
    transcript = Transcript(
        session_id=str(sid), provider_used="whisper", segments=segs
    )
    row = SimpleNamespace(transcript_json=transcript.model_dump_json())
    result_obj = MagicMock()
    result_obj.scalar_one_or_none = MagicMock(return_value=row)
    db = MagicMock()
    db.execute = AsyncMock(return_value=result_obj)
    return db


def _cfg(*, standalone: bool, cadence_seconds: int = 0):
    return SimpleNamespace(
        pipeline=SimpleNamespace(
            video_import_fps=1,
            video_import_cadence_seconds=cadence_seconds,
            video_import_max_cadence_frames=60,
        ),
        feature_flags=SimpleNamespace(
            video_import_drop_zero_face_frames=True,
            visual_evidence_standalone_enabled=standalone,
        ),
    )


@pytest.mark.asyncio
async def test_standalone_forces_cadence_on_silent_transcript() -> None:
    """Empty transcript + standalone: cadence is forced (from the passed video
    duration) so a silent exam still yields frames — and they're kept via the
    faceless redaction path (redact_faceless=True)."""
    sid = uuid.uuid4()
    db = _db_with_transcript(sid, trigger=False)
    extract = AsyncMock(return_value=[(1500, b"jpg")])
    kept = SimpleNamespace(
        status="success", image_bytes=b"m", faces_detected=0,
        faces_blurred=0, reason=None, text_regions_redacted=1,
    )
    with patch.object(vi, "get_config", return_value=_cfg(standalone=True)), \
        patch.object(vi, "get_frame_window_ms", return_value=0), \
        patch.object(vi, "extract_frames_at_windows", extract), \
        patch.object(vi, "get_s3_client", return_value=MagicMock()), \
        patch.object(vi, "write_audit", AsyncMock()), \
        patch.object(vi, "mask_frame", MagicMock(return_value=kept)) as mask:
        extracted, masked, dropped = await vi._extract_and_mask_frames(
            db, sid, [("/tmp/v.mp4", 0)], total_duration_ms=30_000
        )
    # Cadence produced windows off the passed duration → frames extracted.
    extract.assert_awaited_once()
    windows = extract.await_args.args[1]
    assert len(windows) > 1  # spans the timeline, not a single point
    assert extracted == 1 and masked == 1 and dropped == 0
    # Faceless frames are KEPT (redact_faceless True) on the standalone path.
    assert mask.call_args.kwargs["redact_faceless"] is True


@pytest.mark.asyncio
async def test_flag_off_silent_transcript_yields_no_frames() -> None:
    """Guard: OFF + empty transcript + cadence off → zero frames (byte-identical
    to the pre-feature trigger-only path)."""
    sid = uuid.uuid4()
    db = _db_with_transcript(sid, trigger=False)
    extract = AsyncMock(return_value=[(1500, b"jpg")])
    with patch.object(vi, "get_config", return_value=_cfg(standalone=False)), \
        patch.object(vi, "get_frame_window_ms", return_value=0), \
        patch.object(vi, "extract_frames_at_windows", extract), \
        patch.object(vi, "get_s3_client", return_value=MagicMock()), \
        patch.object(vi, "write_audit", AsyncMock()):
        extracted, masked, dropped = await vi._extract_and_mask_frames(
            db, sid, [("/tmp/v.mp4", 0)], total_duration_ms=30_000
        )
    extract.assert_not_awaited()
    assert (extracted, masked, dropped) == (0, 0, 0)


# ── 1b. run_stage1 allow_visual_only branch ─────────────────────────────────


@pytest.mark.asyncio
async def test_run_stage1_visual_only_builds_minimal_note_no_422() -> None:
    """allow_visual_only=True: an EmptyTranscriptError builds a minimal note and
    advances to AWAITING_REVIEW instead of raising the 422 hard-fail."""
    import app.api.v1.transcription as tx
    from app.core.types import (
        Note,
        NoteSection,
        SessionState,
        Transcript,
        TranscriptSegment,
    )
    from app.modules.note_gen.service import EmptyTranscriptError

    sid = uuid.uuid4()
    session = SimpleNamespace(
        id=sid,
        specialty="orthopedic_surgery",
        state=SessionState.PROCESSING_STAGE1,
        output_language="en",
        participants_json=None,
        encounter_context=None,
    )
    transcript = Transcript(
        session_id=str(sid),
        provider_used="whisper",
        segments=[TranscriptSegment(id="s0", start_ms=0, end_ms=1, text="")],
    )
    minimal = Note(
        session_id=str(sid), stage=1, provider_used="none",
        specialty="orthopedic_surgery", completeness_score=0.0,
        sections=[NoteSection(id="physical_exam", status="not_captured")],
    )

    db = AsyncMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: None)
    )
    db.add = MagicMock()  # sync in the transcript-upsert — not a coroutine
    db.flush = AsyncMock()
    transition = AsyncMock()
    with patch.object(tx, "transcribe_audio", AsyncMock(return_value=transcript)), \
        patch.object(tx, "classify_triggers", AsyncMock(return_value=transcript)), \
        patch.object(tx, "scan_transcript_for_phi", AsyncMock(
            return_value=SimpleNamespace(phi_detected=False))), \
        patch.object(tx, "write_audit", AsyncMock()), \
        patch.object(tx, "stored_template_pin", MagicMock(return_value=(None, None))), \
        patch.object(tx, "generate_stage1_note", AsyncMock(
            side_effect=EmptyTranscriptError(
                reason="transcript_empty_or_missing", human_message="x"))), \
        patch.object(tx, "build_and_persist_minimal_note", AsyncMock(
            return_value=minimal)) as build, \
        patch.object(tx, "transition_session", transition), \
        patch.object(tx, "_record_stage1_latency", AsyncMock()), \
        patch.object(tx, "notify_stage1_delivered", AsyncMock()), \
        patch.object(tx, "_purge_raw_audio_if_not_retained", AsyncMock()):
        out = await tx.run_stage1(
            db, session, b"audio", allow_visual_only=True
        )
    # Minimal note was built; the session advanced to AWAITING_REVIEW (not
    # STAGE1_FAILED_NO_AUDIO), and no 422 was raised.
    build.assert_awaited_once()
    assert out is transcript
    advanced = [c.args[2] for c in transition.await_args_list]
    assert SessionState.AWAITING_REVIEW in advanced
    assert SessionState.STAGE1_FAILED_NO_AUDIO not in advanced
