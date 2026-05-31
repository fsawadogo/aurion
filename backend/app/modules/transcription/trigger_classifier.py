"""Trigger classifier — keyword/phrase detector over transcript segments.

Not an ML model — a curated specialty-specific keyword list.
More reliable, explainable, and maintainable for this use case.

Runs over transcript segments and flags those where something visual
is likely happening. Each flagged segment gets is_visual_trigger=True
and a trigger_type.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.types import Template, Transcript
from app.modules.transcription.semantic_trigger import (
    classify_unmatched_segments,
)
from app.modules.transcription.semantic_trigger import (
    is_enabled as semantic_enabled,
)

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


async def classify_triggers(
    transcript: Transcript,
    template: Optional[Template] = None,
) -> Transcript:
    """Run trigger classification over all transcript segments.

    Two-pass classification:
      1. Keyword pass (fast, free, explainable) — flags segments that
         match the template's visual_trigger_keywords or the default
         keyword lists.
      2. Optional semantic pass (Tier 2 / F) — for segments NOT flagged
         by keywords, embed them against trigger-category prose
         descriptions via OpenAI text-embedding-3-small. Catches
         paraphrases the keyword lists miss. Off by default; enable
         via AURION_SEMANTIC_TRIGGER_ENABLED=1.

    Suppression (retrospective narration) always blocks, regardless
    of pass — the model shouldn't think "last visit" was a live event.

    Modifies segments in place. Returns the same transcript with
    updated segments.
    """
    # Build keyword map from template or defaults
    keyword_map = _build_keyword_map(template)

    flagged_count = 0
    suppressed_count = 0
    unmatched: list[tuple[str, str]] = []

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
            # Collect for the semantic fallback below if enabled.
            unmatched.append((segment.id, segment.text))

    # Semantic fallback pass — single batched embeddings call on all
    # unmatched segments. Best-effort: any failure returns {} and the
    # segments stay unflagged (current keyword-only behaviour).
    semantic_added = 0
    if semantic_enabled() and unmatched:
        decisions = await classify_unmatched_segments(unmatched)
        if decisions:
            seg_by_id = {s.id: s for s in transcript.segments}
            for seg_id, trigger_type in decisions.items():
                seg = seg_by_id.get(seg_id)
                if seg and not seg.is_visual_trigger:
                    seg.is_visual_trigger = True
                    seg.trigger_type = trigger_type
                    semantic_added += 1

    logger.info(
        "Trigger classification complete: session=%s total=%d "
        "flagged=%d (keyword=%d semantic=%d) suppressed=%d",
        transcript.session_id,
        len(transcript.segments),
        flagged_count + semantic_added,
        flagged_count,
        semantic_added,
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
