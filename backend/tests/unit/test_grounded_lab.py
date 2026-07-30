"""Grounded Lab — descriptive-vs-grounded replay of a session's clip.

The lab re-runs Stage-2 captioning twice against the SAME frames (descriptive +
grounded) so a reviewer can validate grounded findings before they ride live
notes. These tests lock the two things that make it safe and correct:

  * ``pair_captions`` aligns the two runs by frame_id, keeps the union (so a
    frame one mode discarded still shows), and orders chronologically.
  * The run is READ-ONLY — the audit event exists and its allow-list is
    PHI-free counts only; the module never imports a note-persistence call.
"""

from __future__ import annotations

from app.api.v1.admin.grounded_lab import GroundedLabPair, pair_captions
from app.core.audit_events import (
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
    validate_audit_kwargs,
)
from app.core.types import FrameCaption


def _cap(
    frame_id: str,
    ts: int,
    desc: str,
    *,
    status: str = "ENRICHES",
    conflict: bool = False,
    confidence: str = "high",
) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id,
        session_id="s1",
        timestamp_ms=ts,
        audio_anchor_id="seg_003",
        provider_used="gemini",
        visual_description=desc,
        confidence=confidence,
        confidence_reason="clear view",
        conflict_flag=conflict,
        conflict_detail="audio said 90" if conflict else None,
        integration_status=status,
    )


# ── pairing ──────────────────────────────────────────────────────────────────


def test_pairs_same_frame_side_by_side() -> None:
    desc = [_cap("frame_2", 200, "The clinician flexes the knee.")]
    grnd = [_cap("frame_2", 200, "Reduced knee flexion, reaches ~110 degrees.")]
    pairs = pair_captions(desc, grnd)
    assert len(pairs) == 1
    p = pairs[0]
    assert p.frame_id == "frame_2"
    assert p.descriptive is not None and "flexes" in p.descriptive.text
    assert p.grounded is not None and "110" in p.grounded.text


def test_union_keeps_frame_only_one_mode_produced() -> None:
    # Grounded surfaced a finding the descriptive run discarded — that gap is
    # exactly what the reviewer needs to see, so the frame must still appear.
    desc: list[FrameCaption] = []
    grnd = [_cap("frame_9", 900, "Swelling at the lateral joint line.")]
    pairs = pair_captions(desc, grnd)
    assert len(pairs) == 1
    assert pairs[0].descriptive is None
    assert pairs[0].grounded is not None


def test_pairs_ordered_by_timestamp() -> None:
    desc = [
        _cap("frame_b", 500, "second"),
        _cap("frame_a", 100, "first"),
    ]
    grnd = [_cap("frame_c", 300, "middle")]
    pairs = pair_captions(desc, grnd)
    assert [p.timestamp_ms for p in pairs] == [100, 300, 500]


def test_conflict_flag_carries_through() -> None:
    grnd = [_cap("frame_x", 400, "Effusion visible.", status="CONFLICTS", conflict=True)]
    pairs = pair_captions([], grnd)
    assert pairs[0].grounded is not None
    assert pairs[0].grounded.conflict_flag is True
    assert pairs[0].grounded.integration_status == "CONFLICTS"


def test_empty_runs_produce_no_pairs() -> None:
    assert pair_captions([], []) == []


def test_pair_is_the_expected_type() -> None:
    pairs = pair_captions([_cap("f", 1, "x")], [])
    assert isinstance(pairs[0], GroundedLabPair)


# ── read-only audit contract ─────────────────────────────────────────────────


def test_grounded_lab_run_event_exists() -> None:
    assert AuditEventType.GROUNDED_LAB_RUN.value == "grounded_lab_run"


def test_run_event_allows_only_phi_free_counts() -> None:
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.GROUNDED_LAB_RUN]
    assert allowed == {
        "actor_id",
        "frame_count",
        "descriptive_findings",
        "grounded_findings",
    }


def test_run_event_rejects_a_caption_body() -> None:
    # No caption text / patient content may ride the immutable log.
    unknown = validate_audit_kwargs(
        AuditEventType.GROUNDED_LAB_RUN,
        {"actor_id", "frame_count", "visual_description"},
    )
    assert unknown == {"visual_description"}


def test_module_never_persists_a_note_version() -> None:
    # The lab must not mutate the chart. Guard against a future edit importing a
    # note-writing helper into the module.
    import app.api.v1.admin.grounded_lab as mod

    assert not hasattr(mod, "create_note_version")
    assert not hasattr(mod, "merge_visual_citations")
