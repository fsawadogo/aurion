"""Unit tests for the live preview service (#64).

Covers:
  * _build_preview_transcript caps at 8000 chars from the TAIL
    (we want the most-recent transcript content when truncating)
  * _build_preview_transcript collapses partial text into one synthetic
    segment with stable id and zero timing
  * PREVIEW_STAGE sentinel is 0 (distinct from Stage 1 / Stage 2)
  * audit whitelist refuses the section content (PHI)
  * audit enum value locked for DynamoDB compatibility
"""

from __future__ import annotations

from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType
from app.modules.live_preview import service as live_preview

# ── _build_preview_transcript ────────────────────────────────────────────


def test_build_preview_transcript_basic_shape():
    """Wraps text in a single synthetic TranscriptSegment."""
    t = live_preview._build_preview_transcript("sess-1", "Patient reports knee pain.")
    assert t.session_id == "sess-1"
    assert t.provider_used == "live_preview_synthetic"
    assert len(t.segments) == 1
    assert t.segments[0].id == "preview_seg_0"
    assert t.segments[0].text == "Patient reports knee pain."
    # Zero timing — preview doesn't have per-utterance anchors
    assert t.segments[0].start_ms == 0
    assert t.segments[0].end_ms == 0


def test_build_preview_transcript_caps_tail():
    """Long partial transcripts are capped at 8000 chars, keeping the
    TAIL (most-recent content the physician needs). The head gets
    dropped — that's correct for live preview where the latest minute
    matters more than the first minute."""
    long_text = "OLD CONTENT " * 1000 + "RECENT CONTENT"  # ~12000 chars
    t = live_preview._build_preview_transcript("s", long_text)
    assert len(t.segments[0].text) == 8000
    # The recent part survived
    assert "RECENT CONTENT" in t.segments[0].text


def test_build_preview_transcript_short_text_passes_through():
    """Text under the cap is preserved verbatim — no truncation."""
    text = "short"
    t = live_preview._build_preview_transcript("s", text)
    assert t.segments[0].text == "short"


def test_preview_stage_sentinel_is_zero():
    """Stage 1 = 1, Stage 2 = 2, draft preview = 0. Consumer-facing
    invariant — any code joining preview rows with note versions
    relies on this distinction."""
    assert live_preview.PREVIEW_STAGE == 0


# ── Audit whitelists ─────────────────────────────────────────────────────


def test_audit_live_preview_refuses_content():
    """`sections` is PHI by definition. The audit row carries metadata
    only — preview_id + version + transcript_chars + provider +
    latency. The sections themselves live in the row's JSONB column."""
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.LIVE_PREVIEW_GENERATED]
    forbidden = {"sections", "claims", "text", "transcript"}
    leaks = forbidden & allowed
    assert not leaks, f"audit whitelist leaks PHI: {leaks}"


def test_audit_live_preview_carries_metadata():
    """The whitelist must include the fields the route emits."""
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.LIVE_PREVIEW_GENERATED]
    for field in ("actor_id", "preview_id", "version", "transcript_chars",
                  "provider_used", "latency_ms"):
        assert field in allowed, f"missing {field} in whitelist"


def test_audit_enum_value_stable():
    """Regression guard — locked string for DynamoDB compatibility."""
    assert (
        AuditEventType.LIVE_PREVIEW_GENERATED.value
        == "live_preview_generated"
    )
