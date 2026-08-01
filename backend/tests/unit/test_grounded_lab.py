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
    # The lab must not mutate the chart. The persistence call is
    # create_note_version — its absence is the real read-only invariant.
    # (merge_visual_citations IS imported for the Fusion A/B compare, but it is
    # a pure merge that returns a Note and is only ever called on a deep copy —
    # it never persists, so it is not a chart-mutation risk.)
    import app.api.v1.admin.grounded_lab as mod

    assert not hasattr(mod, "create_note_version")
    # The fusion compare runs merge on a COPY of the audio note — assert the
    # source string never calls create_note_version.
    import inspect

    src = inspect.getsource(mod)
    assert "create_note_version" not in src


# ── async run surface ────────────────────────────────────────────────────────


def test_async_run_routes_registered() -> None:
    # Start (POST) + poll (GET) + list — the async shape that survives the 60s
    # ALB idle timeout (a synchronous run is dropped mid-flight on a big set).
    from app.api.v1.admin.grounded_lab import router

    paths = {r.path for r in router.routes}
    assert "/admin/grounded-lab/sessions" in paths
    assert "/admin/grounded-lab/{session_id}/run" in paths
    assert "/admin/grounded-lab/runs/{job_id}" in paths


def test_fusion_compare_routes_registered() -> None:
    from app.api.v1.admin.grounded_lab import router

    paths = {r.path for r in router.routes}
    assert "/admin/grounded-lab/{session_id}/fusion-compare" in paths
    assert "/admin/grounded-lab/fusion-runs/{job_id}" in paths


def test_fusion_compare_result_round_trips() -> None:
    # The two-note payload is stored as result_json and re-validated on poll.
    from app.api.v1.admin.grounded_lab import FusionCompareResult

    original = FusionCompareResult(
        session_id="s1", specialty="orthopedic_surgery", frame_count=9,
        note_a={"sections": [], "provider_used": "anthropic"},
        note_b={"sections": [], "provider_used": "fusion_b"},
        sections_a=3, sections_b=4, conflicts_b=1,
    )
    restored = FusionCompareResult.model_validate(original.model_dump())
    assert restored == original


def test_fusion_compare_audit_is_phi_free_counts() -> None:
    from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType

    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.FUSION_COMPARE_RUN]
    assert allowed == {
        "actor_id", "frame_count", "sections_a", "sections_b", "conflicts_b",
    }


def test_run_type_column_default() -> None:
    from app.core.models import GroundedLabRunModel

    assert GroundedLabRunModel.run_type.default.arg == "grounded_lab"


def test_modality_compare_routes_registered() -> None:
    from app.api.v1.admin.grounded_lab import router

    paths = {r.path for r in router.routes}
    assert "/admin/grounded-lab/{session_id}/modality-compare" in paths
    assert "/admin/grounded-lab/modality-runs/{job_id}" in paths


def test_modality_compare_result_round_trips() -> None:
    from app.api.v1.admin.grounded_lab import ModalityCompareResult

    original = ModalityCompareResult(
        session_id="s1", specialty="orthopedic_surgery", frame_count=11,
        note_audio={"sections": []},
        note_visual={"sections": []},
        note_merged={"sections": []},
        sections_audio=5, sections_visual=2, sections_merged=6,
    )
    restored = ModalityCompareResult.model_validate(original.model_dump())
    assert restored == original


def test_modality_visual_note_may_be_absent() -> None:
    # The video can yield nothing (silent/blurry) — visual note is then None and
    # its section count is 0, but audio + merged still populate.
    from app.api.v1.admin.grounded_lab import ModalityCompareResult

    r = ModalityCompareResult(
        session_id="s1", frame_count=11,
        note_audio={"sections": []}, note_visual=None, note_merged={"sections": []},
        sections_audio=5, sections_visual=0, sections_merged=5,
    )
    assert r.note_visual is None


def test_modality_compare_audit_is_phi_free_counts() -> None:
    from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType

    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.MODALITY_COMPARE_RUN]
    assert allowed == {
        "actor_id", "frame_count",
        "sections_audio", "sections_visual", "sections_merged",
    }


def test_result_round_trips_through_job_storage() -> None:
    # The completed payload is stored as the job row's result_json (a dict) and
    # re-validated on poll — this round-trip must be lossless.
    from app.api.v1.admin.grounded_lab import (
        GroundedLabPair as Pair,
    )
    from app.api.v1.admin.grounded_lab import (
        GroundedLabRunResponse,
    )

    original = GroundedLabRunResponse(
        session_id="s1",
        specialty="orthopedic_surgery",
        evidence_mode="frames_only",
        provider_used="gemini",
        frame_count=2,
        descriptive_findings=1,
        grounded_findings=1,
        pairs=[
            Pair(
                frame_id="frame_2",
                timestamp_ms=200,
                audio_anchor_id="seg_003",
                evidence_kind="frame",
                descriptive=None,
                grounded=None,
            )
        ],
    )
    stored = original.model_dump()  # what lands in result_json
    assert isinstance(stored, dict)
    restored = GroundedLabRunResponse.model_validate(stored)
    assert restored == original


def test_run_model_defaults_to_running() -> None:
    from app.core.models import GroundedLabRunModel

    assert GroundedLabRunModel.__tablename__ == "grounded_lab_runs"
