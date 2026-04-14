"""Trigger classifier — keyword/phrase detector over transcript segments.

Not an ML model — a curated specialty-specific keyword list.
More reliable, explainable, and maintainable for this use case.

Runs over transcript segments and flags those where something visual
is likely happening. Each flagged segment gets is_visual_trigger=True
and a trigger_type.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.core.types import Template, Transcript, TranscriptSegment

logger = logging.getLogger("aurion.trigger_classifier")

# ── Global Suppression List ───────────────────────────────────────────────
# These phrases describe retrospective narration, not live observation.
# A frame at that moment captures nothing useful.

SUPPRESSION_PHRASES: list[str] = [
    "last visit",
    "previously",
    "the patient reported",
    "history of",
    "they mentioned",
    "recalled",
    "prior to",
    "at baseline",
    "in the past",
    "reported that",
    "mentioned that",
    "told me",
    "said that",
    "has been",
    "had been",
    "was experiencing",
]

# ── Default Trigger Categories (used when template has no keywords) ───────
# These are the fallback global triggers per the pipeline spec.

DEFAULT_TRIGGER_CATEGORIES: dict[str, list[str]] = {
    "live_imaging_review": [
        "looking at the x-ray",
        "on the mri",
        "ct shows",
        "you can see here",
        "pulling up",
        "looking at the",
        "on the screen",
        "this view",
        "ap view",
        "lateral view",
    ],
    "active_physical_examination": [
        "range of motion",
        "rom",
        "flexion",
        "extension",
        "palpation",
        "tenderness",
        "guarding",
        "rotation",
        "strength",
        "sensation",
        "reflexes",
        "special test",
    ],
    "wound_tissue_assessment": [
        "wound edges",
        "granulation",
        "dimensions",
        "measuring",
        "drainage",
        "flap",
        "perfusion",
        "capillary refill",
        "wound",
        "incision",
    ],
    "gait_functional_observation": [
        "gait",
        "walking",
        "limping",
        "antalgic",
        "weight bearing",
        "loading",
    ],
    "general_visual_pointer": [
        "you can see",
        "look at this",
        "right here",
        "this area",
        "comparing",
        "looking here",
    ],
}


def classify_triggers(
    transcript: Transcript,
    template: Optional[Template] = None,
) -> Transcript:
    """Run trigger classification over all transcript segments.

    Modifies segments in place, setting is_visual_trigger and trigger_type.
    Uses template-specific keywords if available, falls back to defaults.

    Returns the same transcript with updated segments.
    """
    # Build keyword map from template or defaults
    keyword_map = _build_keyword_map(template)

    flagged_count = 0
    suppressed_count = 0

    for segment in transcript.segments:
        text_lower = segment.text.lower()

        # Check suppression first — retrospective narration blocks triggers
        if _is_suppressed(text_lower):
            segment.is_visual_trigger = False
            segment.trigger_type = None
            suppressed_count += 1
            continue

        # Check for trigger matches
        trigger_type = _find_trigger(text_lower, keyword_map)
        if trigger_type:
            segment.is_visual_trigger = True
            segment.trigger_type = trigger_type
            flagged_count += 1
        else:
            segment.is_visual_trigger = False
            segment.trigger_type = None

    logger.info(
        "Trigger classification complete: session=%s total=%d flagged=%d suppressed=%d",
        transcript.session_id,
        len(transcript.segments),
        flagged_count,
        suppressed_count,
    )
    return transcript


def _build_keyword_map(template: Optional[Template]) -> dict[str, list[str]]:
    """Build a keyword map from template sections or use defaults."""
    if template and any(s.visual_trigger_keywords for s in template.sections):
        # Use template-specific keywords
        keyword_map: dict[str, list[str]] = {}
        for section in template.sections:
            if section.visual_trigger_keywords:
                section_trigger_type = _section_id_to_trigger_type(section.id)
                keyword_map[section_trigger_type] = [
                    kw.lower() for kw in section.visual_trigger_keywords
                ]
        return keyword_map

    # Fall back to global defaults
    return DEFAULT_TRIGGER_CATEGORIES


def _section_id_to_trigger_type(section_id: str) -> str:
    """Map template section IDs to trigger type names."""
    mapping = {
        "physical_exam": "active_physical_examination",
        "imaging_review": "live_imaging_review",
        "wound_assessment": "wound_tissue_assessment",
        "functional_assessment": "gait_functional_observation",
        "vital_signs": "live_imaging_review",
        "investigations": "live_imaging_review",
    }
    return mapping.get(section_id, "general_visual_pointer")


def _is_suppressed(text_lower: str) -> bool:
    """Check if text matches any suppression phrase."""
    return any(phrase in text_lower for phrase in SUPPRESSION_PHRASES)


def _find_trigger(text_lower: str, keyword_map: dict[str, list[str]]) -> Optional[str]:
    """Find the first matching trigger category for the text."""
    for trigger_type, keywords in keyword_map.items():
        for keyword in keywords:
            if keyword in text_lower:
                return trigger_type
    return None
