"""The Grounded Lab must merge visual citations the way live Stage 2 does.

``merge_visual_citations`` routes a caption by what it SHOWS (VIS-03, widened to
every caption in #761) — but ONLY when it is handed the trigger pool; the
``trigger_segments is None`` path deliberately keeps every legacy caller
byte-identical by falling back to anchor routing.

The lab omitted that argument, so it routed by anchor while production routed by
content. That is the wrong way round: the lab is the surface we validate claim
placement on BEFORE it reaches live patient notes, so a lab result that disagrees
with the pipeline it models is worse than no result — it validates the wrong
thing. This is a source-level drift guard (same shape as the AppConfig validator
guard) because the failure is a silently-omitted optional kwarg: it type-checks,
it runs, it just quietly measures the wrong pipeline.
"""

from __future__ import annotations

import ast
from pathlib import Path

_LAB = (
    Path(__file__).resolve().parents[2]
    / "app"
    / "api"
    / "v1"
    / "admin"
    / "grounded_lab.py"
)


def _merge_calls() -> list[ast.Call]:
    tree = ast.parse(_LAB.read_text(encoding="utf-8"))
    return [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "merge_visual_citations"
    ]


def test_lab_merges_are_content_routed_like_production() -> None:
    """Every merge_visual_citations call in the lab passes trigger_segments.

    Without it the merge cannot tell a cadence caption from a trigger one and
    silently falls back to anchor routing — the lab would then show different
    section placement than the live Stage 2 it exists to validate.
    """
    calls = _merge_calls()
    assert calls, "expected the lab to merge visual citations"

    missing = [
        call.lineno
        for call in calls
        if not any(kw.arg == "trigger_segments" for kw in call.keywords)
    ]
    assert not missing, (
        f"merge_visual_citations at line(s) {missing} in grounded_lab.py does not "
        "pass trigger_segments, so it falls back to anchor routing while live "
        "Stage 2 routes by caption content. The lab must model production."
    )


def test_lab_passes_the_same_pool_it_captioned_with() -> None:
    """The merge gets the SAME `trigger_segments` name the capture pass used.

    Classification must not be able to disagree across the two calls; passing a
    different (or freshly-derived) pool would reintroduce exactly the drift the
    lab is meant to detect.
    """
    for call in _merge_calls():
        kw = next(k for k in call.keywords if k.arg == "trigger_segments")
        assert isinstance(kw.value, ast.Name) and kw.value.id == "trigger_segments", (
            f"merge_visual_citations at line {call.lineno} should pass the "
            "function's own `trigger_segments` pool, not a re-derived one."
        )
