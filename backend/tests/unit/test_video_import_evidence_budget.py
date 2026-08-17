"""Video imports apply the Stage-2 evidence budget before masking work."""

from app.api.v1.video_import import _select_import_windows


def test_import_window_budget_prioritizes_triggers_and_covers_timeline() -> None:
    trigger_windows = [(index * 1000, index * 1000) for index in range(50)]
    cadence_windows = [(100_000 + index * 1000, 100_000 + index * 1000) for index in range(50)]

    selected = _select_import_windows(
        trigger_windows,
        cadence_windows,
        max_items=20,
        trigger_fraction=0.75,
    )

    selected_trigger = [window for window in selected if window[0] < 100_000]
    selected_cadence = [window for window in selected if window[0] >= 100_000]
    assert len(selected) == 20
    assert len(selected_trigger) == 15
    assert len(selected_cadence) == 5
    assert selected_trigger[0] == trigger_windows[0]
    assert selected_trigger[-1] == trigger_windows[-1]
    assert selected_cadence[0] == cadence_windows[0]
    assert selected_cadence[-1] == cadence_windows[-1]


def test_import_window_budget_deduplicates_without_overflow() -> None:
    selected = _select_import_windows(
        [(1000, 1000), (2000, 2000)],
        [(1000, 1000), (3000, 3000)],
        max_items=10,
        trigger_fraction=0.75,
    )

    assert selected == [(1000, 1000), (2000, 2000), (3000, 3000)]
