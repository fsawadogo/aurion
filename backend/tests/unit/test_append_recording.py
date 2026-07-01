"""Unit tests for resume-recording (note-Options phase 4).

Covers the pure transcript-merge (id continuation + timestamp offset, no
collision/overlap) and the append endpoint's gates (403 flag-off, 404 no
transcript, 422 empty addition) using the same mocked-deps pattern as
test_regenerate_note.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.transcription import AppendRecordingResponse, append_recording
from app.core.types import Note, Transcript, TranscriptSegment
from app.modules.transcription.service import merge_transcripts

# ── merge_transcripts (pure) ─────────────────────────────────────────────


def _seg(id_: str, start: int, end: int, text: str = "x") -> TranscriptSegment:
    return TranscriptSegment(id=id_, start_ms=start, end_ms=end, text=text)


def _tr(segs: list[TranscriptSegment]) -> Transcript:
    return Transcript(session_id="s", provider_used="whisper", segments=segs)


def test_merge_continues_segment_ids_no_collision() -> None:
    existing = _tr([_seg("seg_001", 0, 1000), _seg("seg_002", 1000, 2000)])
    addition = _tr([_seg("seg_001", 0, 500), _seg("seg_002", 500, 900)])
    merged = merge_transcripts(existing, addition)
    ids = [s.id for s in merged.segments]
    assert ids == ["seg_001", "seg_002", "seg_003", "seg_004"]
    assert len(set(ids)) == len(ids)  # unique


def test_merge_offsets_addition_timestamps_past_clip1() -> None:
    existing = _tr([_seg("seg_001", 0, 2000)])
    addition = _tr([_seg("seg_001", 0, 500), _seg("seg_002", 500, 1200)])
    merged = merge_transcripts(existing, addition)
    # clip-1 unchanged; clip-2 shifted by clip-1's last end (2000ms) → no overlap.
    assert (merged.segments[0].start_ms, merged.segments[0].end_ms) == (0, 2000)
    assert (merged.segments[1].start_ms, merged.segments[1].end_ms) == (2000, 2500)
    assert (merged.segments[2].start_ms, merged.segments[2].end_ms) == (2500, 3200)
    # Monotonic non-overlapping timeline.
    for a, b in zip(merged.segments, merged.segments[1:]):
        assert b.start_ms >= a.end_ms


def test_merge_preserves_clip1_verbatim() -> None:
    existing = _tr([_seg("seg_001", 0, 1000, "first clip text")])
    merged = merge_transcripts(existing, _tr([_seg("seg_001", 0, 100, "more")]))
    assert merged.segments[0].text == "first clip text"
    assert merged.segments[0].id == "seg_001"


def test_merge_onto_empty_existing() -> None:
    merged = merge_transcripts(_tr([]), _tr([_seg("seg_001", 0, 500)]))
    assert [s.id for s in merged.segments] == ["seg_001"]
    assert merged.segments[0].start_ms == 0


# ── endpoint gates ───────────────────────────────────────────────────────


def _session(sid: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=sid, specialty="orthopedic_surgery", output_language="en",
        encounter_context=None, participants_json=None,
    )


def _config(note_options_enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        feature_flags=SimpleNamespace(note_options_enabled=note_options_enabled)
    )


def _upload() -> MagicMock:
    up = MagicMock()
    up.read = AsyncMock(return_value=b"RIFFwavbytes")
    return up


def _db(transcript_row) -> AsyncMock:
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = transcript_row
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    return db


def _caller() -> SimpleNamespace:
    return SimpleNamespace(user_id=uuid.uuid4(), role=None, email="x@x.com")


@pytest.mark.asyncio
async def test_append_denied_when_flag_off() -> None:
    sid = uuid.uuid4()
    with (
        patch("app.api.v1.transcription.get_owned_session_or_404",
              AsyncMock(return_value=_session(sid))),
        patch("app.api.v1.transcription.get_config",
              return_value=_config(False)),
    ):
        with pytest.raises(HTTPException) as exc:
            await append_recording(sid, _upload(), _caller(), _db(MagicMock()))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_append_404_when_no_transcript() -> None:
    sid = uuid.uuid4()
    with (
        patch("app.api.v1.transcription.get_owned_session_or_404",
              AsyncMock(return_value=_session(sid))),
        patch("app.api.v1.transcription.get_config",
              return_value=_config(True)),
    ):
        with pytest.raises(HTTPException) as exc:
            await append_recording(sid, _upload(), _caller(), _db(None))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_append_422_when_addition_empty() -> None:
    sid = uuid.uuid4()
    row = SimpleNamespace(transcript_json=_tr([_seg("seg_001", 0, 1000)]).model_dump_json())
    with (
        patch("app.api.v1.transcription.get_owned_session_or_404",
              AsyncMock(return_value=_session(sid))),
        patch("app.api.v1.transcription.get_config",
              return_value=_config(True)),
        patch("app.api.v1.transcription.transcribe_audio",
              AsyncMock(return_value=_tr([]))),
    ):
        with pytest.raises(HTTPException) as exc:
            await append_recording(sid, _upload(), _caller(), _db(row))
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_append_happy_path_merges_and_regenerates() -> None:
    sid = uuid.uuid4()
    row = SimpleNamespace(
        transcript_json=_tr([_seg("seg_001", 0, 1000)]).model_dump_json(),
        provider_used="whisper",
    )
    addition = _tr([_seg("seg_001", 0, 500), _seg("seg_002", 500, 900)])
    note = Note(
        session_id=str(sid), stage=1, version=2, provider_used="anthropic",
        specialty="orthopedic_surgery", completeness_score=0.7,
    )
    gen = AsyncMock(return_value=note)
    with (
        patch("app.api.v1.transcription.get_owned_session_or_404",
              AsyncMock(return_value=_session(sid))),
        patch("app.api.v1.transcription.get_config",
              return_value=_config(True)),
        patch("app.api.v1.transcription.transcribe_audio",
              AsyncMock(return_value=addition)),
        patch("app.api.v1.transcription.classify_triggers",
              AsyncMock(side_effect=lambda t: t)),
        patch("app.api.v1.transcription.generate_stage1_note", gen),
        patch("app.api.v1.transcription.write_audit", AsyncMock()),
    ):
        resp = await append_recording(sid, _upload(), _caller(), _db(row))
    assert isinstance(resp, AppendRecordingResponse)
    assert resp.added_segments == 2
    assert resp.total_segments == 3  # 1 existing + 2 appended
    assert resp.version == 2
    # note-gen was called with the MERGED transcript (3 segments).
    assert len(gen.call_args.kwargs["transcript"].segments) == 3


def test_recording_appended_audit_carries_no_transcript_text() -> None:
    from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType

    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.RECORDING_APPENDED]
    for banned in ("text", "transcript", "segments", "transcript_json"):
        assert banned not in allowed
