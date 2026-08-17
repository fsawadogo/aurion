"""Grounded visual findings — video produces cited exam findings.

Faical's decision (2026-07-30): the video may state the clinical finding the
visible evidence supports, not only literal descriptions. Safety invariant the
tests lock: grounding is STRUCTURAL — every visual claim keeps
source_type="visual" + source_id=frame_id in BOTH modes, so a grounded finding
is always cited to its frame and never becomes an ungrounded assertion. The
prompt selection is flag-gated and per-physician overrides still win.
"""

from __future__ import annotations

from app.core.types import FrameCaption
from app.modules.config.schema import FeatureFlagsConfig
from app.modules.providers.vision.shared import (
    VISION_GROUNDED_SYSTEM_PROMPT,
    VISION_SYSTEM_PROMPT,
)
from app.modules.vision.service import _build_visual_claim

# ── Flag ───────────────────────────────────────────────────────────────────


def test_flag_defaults_off() -> None:
    assert FeatureFlagsConfig().grounded_visual_findings_enabled is False


def test_visual_subflag_does_not_enable_grounded_synthesis_master() -> None:
    # The sub-flag remains independently configurable, but the Stage-2 route
    # requires both it and the governing master before selecting grounded mode.
    cfg = FeatureFlagsConfig(grounded_visual_findings_enabled=True)
    assert cfg.grounded_visual_findings_enabled is True
    assert cfg.grounded_synthesis_enabled is False


# ── Prompt content ─────────────────────────────────────────────────────────


def test_descriptive_prompt_forbids_interpretation() -> None:
    assert "Do not diagnose, interpret" in VISION_SYSTEM_PROMPT


def test_grounded_prompt_permits_findings_but_bounds_them() -> None:
    p = VISION_GROUNDED_SYSTEM_PROMPT
    # Permits stating the finding…
    assert "clinical finding" in p
    # …but keeps it grounded in the visible evidence and bans diagnosis leaps.
    assert "never assert a diagnosis" in p or "cannot establish" in p
    assert "not directly visible" in p


def test_grounded_prompt_requires_note_ready_output() -> None:
    p = VISION_GROUNDED_SYSTEM_PROMPT.lower()
    assert "one concise, note-ready clinical sentence" in p
    assert 'do not narrate "a monitor screen displays"' in p
    assert "inventory of visible anatomy" in p


def test_grounded_prompt_discards_metadata_only_evidence() -> None:
    p = VISION_GROUNDED_SYSTEM_PROMPT.lower()
    assert "metadata alone is not clinical enrichment" in p
    assert "confidence low" in p
    assert "discarded rather than inserted" in p


# ── The safety invariant: grounding is structural in BOTH modes ────────────


def _caption(desc: str, status: str = "ENRICHES") -> FrameCaption:
    return FrameCaption(
        frame_id="frame_00042",
        session_id="s1",
        timestamp_ms=14500,
        audio_anchor_id="seg_003",
        provider_used="gemini",
        visual_description=desc,
        confidence="high",
        confidence_reason="clear view of the knee exam",
        conflict_flag=False,
        conflict_detail=None,
        integration_status=status,
    )


def test_grounded_finding_still_cites_its_frame() -> None:
    # A grounded clinical finding must land as a claim cited to its frame —
    # exactly like a descriptive caption. This is the line between "grounded"
    # and "ungrounded".
    cap = _caption("Reduced knee flexion, reaches approximately 110°.")
    claim = _build_visual_claim(cap, formatted=True)
    assert claim is not None
    assert claim.source_type == "visual"
    assert claim.source_id == "frame_00042"


def test_descriptive_caption_cites_its_frame_too() -> None:
    cap = _caption("The clinician flexes the patient's knee.")
    claim = _build_visual_claim(cap, formatted=False)
    assert claim is not None
    assert claim.source_type == "visual"
    assert claim.source_id == "frame_00042"


def test_conflict_claim_keeps_prefix_and_source_in_both_modes() -> None:
    # The approval gate keys off the conflict_ id prefix — reformatting or
    # grounding must never break it (an unresolved conflict must still block
    # sign-off).
    cap = _caption("Swelling visible at the lateral joint line.", status="CONFLICTS")
    for formatted in (True, False):
        claim = _build_visual_claim(cap, formatted=formatted)
        assert claim is not None
        assert claim.id.startswith("conflict_")
        assert claim.source_type == "visual"
        assert claim.source_id == "frame_00042"
