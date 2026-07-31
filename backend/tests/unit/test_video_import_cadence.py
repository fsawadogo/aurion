"""Cadence-based frame extraction for uploaded videos.

Frame extraction was trigger-gated: a video whose transcript flagged no visual
keywords produced ZERO frames, so a SILENT physical exam gave the vision layer
nothing (an audio-only note). Cadence sampling adds time-anchored frames across
the whole timeline regardless of spoken triggers. These tests lock the pure
window-builder: off by default, evenly spaced when on, unioned with (never
replacing) trigger frames, and hard-capped so a long video can't fan out into
thousands of vision calls.
"""

from __future__ import annotations

from app.api.v1.video_import import _cadence_windows
from app.modules.config.schema import PipelineConfig


def test_cadence_off_by_default() -> None:
    assert PipelineConfig().video_import_cadence_seconds == 0


def test_cadence_zero_yields_nothing() -> None:
    # Back-compat: cadence off → no cadence windows → byte-identical to the
    # trigger-only path.
    assert _cadence_windows(60_000, 0, 60) == []


def test_unknown_duration_yields_nothing() -> None:
    assert _cadence_windows(0, 10, 60) == []


def test_points_are_evenly_spaced_zero_length_windows() -> None:
    w = _cadence_windows(60_000, 10, 60)
    # 0,10,20,30,40,50,60 s → 7 points, each a zero-length (t, t) window so it
    # reuses extract_frames_at_windows' midpoint sampling.
    assert w == [(t, t) for t in range(0, 60_001, 10_000)]


def test_cap_thins_a_long_video_to_the_ceiling() -> None:
    # 5s cadence over 1h would be ~720 points; the cap thins it to <= max_frames
    # while still spanning the whole duration (so coverage stays end-to-end).
    w = _cadence_windows(3_600_000, 5, 60)
    assert len(w) <= 60
    assert w[0] == (0, 0)
    assert w[-1][0] >= 3_500_000  # last sample near the end, not truncated early


def test_cap_of_one_is_safe() -> None:
    # Degenerate cap must not divide-by-zero or loop unbounded.
    w = _cadence_windows(60_000, 5, 1)
    assert len(w) == 1
    assert w[0] == (0, 0)


def test_short_video_under_one_interval_still_samples_start() -> None:
    # A video shorter than one cadence interval still gets its 0ms frame.
    w = _cadence_windows(3_000, 10, 60)
    assert w == [(0, 0)]
