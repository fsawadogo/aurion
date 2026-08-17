"""Stage-2 evidence budgeting preserves clinical triggers and time coverage."""

from __future__ import annotations

from app.core.types import MaskedFrame, TranscriptSegment
from app.modules.vision.service import select_visual_evidence


def _frame(index: int, timestamp_ms: int) -> MaskedFrame:
    return MaskedFrame(
        frame_id=f"frame_{index:03d}",
        session_id="session-1",
        timestamp_ms=timestamp_ms,
        s3_key=f"frames/session-1/{timestamp_ms}.jpg",
        masking_confirmed=True,
    )


def test_budget_prioritizes_triggers_and_spans_both_pools() -> None:
    trigger_timestamps = [100_000 + index * 10_000 for index in range(40)]
    cadence_timestamps = [600_000 + index * 10_000 for index in range(40)]
    triggers = [
        TranscriptSegment(
            id=f"seg_{index:03d}",
            start_ms=timestamp_ms,
            end_ms=timestamp_ms,
            text="range of motion",
            is_visual_trigger=True,
            trigger_type="active_physical_examination",
        )
        for index, timestamp_ms in enumerate(trigger_timestamps)
    ]
    evidence = [
        *(_frame(index, timestamp) for index, timestamp in enumerate(trigger_timestamps)),
        *(_frame(index + 40, timestamp) for index, timestamp in enumerate(cadence_timestamps)),
    ]

    selected = select_visual_evidence(
        evidence,
        triggers,
        max_items=20,
        trigger_fraction=0.75,
    )

    selected_trigger = [item for item in selected if item.timestamp_ms < 600_000]
    selected_cadence = [item for item in selected if item.timestamp_ms >= 600_000]
    assert len(selected) == 20
    assert len(selected_trigger) == 15
    assert len(selected_cadence) == 5
    assert selected_trigger[0].timestamp_ms == trigger_timestamps[0]
    assert selected_trigger[-1].timestamp_ms == trigger_timestamps[-1]
    assert selected_cadence[0].timestamp_ms == cadence_timestamps[0]
    assert selected_cadence[-1].timestamp_ms == cadence_timestamps[-1]


def test_budget_is_noop_below_limit_and_orders_by_timestamp() -> None:
    evidence = [_frame(2, 3000), _frame(0, 1000), _frame(1, 2000)]

    selected = select_visual_evidence(
        evidence,
        [],
        max_items=10,
        trigger_fraction=0.75,
    )

    assert [item.timestamp_ms for item in selected] == [1000, 2000, 3000]


def test_cadence_only_budget_spans_full_visit() -> None:
    evidence = [_frame(index, index * 1000) for index in range(100)]

    selected = select_visual_evidence(
        evidence,
        [],
        max_items=10,
        trigger_fraction=0.75,
    )

    assert len(selected) == 10
    assert selected[0].timestamp_ms == 0
    assert selected[-1].timestamp_ms == 99_000
