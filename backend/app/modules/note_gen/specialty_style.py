"""Per-specialty style snippets injected into the Stage 1 note prompt
(Tier 2 / item G).

Each specialty has documentation conventions: orthopedic notes quantify
ROM and laterality; pediatric notes attribute to the caregiver when the
child can't articulate; emergency notes always end with a disposition.
The base system prompt is specialty-agnostic — these snippets layer
specialty-appropriate guidance on top without changing the rules
(descriptive mode, source traceability, no inference).

The guidance is style-only: WHAT terminology and structure to favour
when the transcript supports it. It NEVER tells the model to add
content the transcript didn't already contain. If a transcript doesn't
mention laterality, the orthopedic snippet doesn't make the model
hallucinate one — descriptive mode still wins.

Keep each snippet to ~3 sentences. Longer prompts dilute attention;
the model benefits more from a tight pointer than a textbook.
"""

from __future__ import annotations

_STYLE: dict[str, str] = {
    # ── MVP templates (CLAUDE.md §"Specialty Templates") ─────────────
    "orthopedic_surgery": (
        "Style: use precise anatomical terminology (e.g. 'medial joint "
        "line', 'lateral malleolus') and quantify when the transcript "
        "does — degrees of range of motion, centimetres of effusion, "
        "side (right/left). Imaging review should always note modality + "
        "laterality + view (e.g. 'AP and lateral right knee X-ray')."
    ),
    "plastic_surgery": (
        "Style: when wounds are discussed, capture dimensions (length × "
        "width × depth) and tissue qualifiers (color, drainage character, "
        "edges) exactly as stated. Note flap viability descriptors "
        "(perfusion, capillary refill, color match) when applicable. Do "
        "not infer healing trajectory."
    ),
    "musculoskeletal": (
        "Style: include functional context the physician mentions — gait "
        "(antalgic, normal, limp side), sport- or activity-specific "
        "movements, pain at rest vs with loading. Document special tests "
        "by name + result (e.g. 'McMurray test positive on right')."
    ),
    "emergency_medicine": (
        "Style: lead with vital signs and chief complaint. Disposition is "
        "MANDATORY — admit / discharge / transfer / observation — and "
        "must be sourced to a physician statement. Time-stamp critical "
        "interventions when the transcript provides them."
    ),
    "general": (
        "Style: prefer brevity over completeness. Use full sentences only "
        "when the physician narrates in prose; otherwise terse, "
        "telegraphic phrasing is appropriate (e.g. 'BP 132/84, HR 78, "
        "afebrile')."
    ),
    # ── Post-MVP templates (#70) ─────────────────────────────────────
    "family_medicine": (
        "Style: capture holistic context the physician raises — social "
        "history (smoking, alcohol, occupation), family history, "
        "continuity references to prior visits ('as discussed at the "
        "last visit'). Preventive screening cadence should be documented "
        "when explicitly addressed."
    ),
    "internal_medicine": (
        "Style: when the physician runs a systematic Review of Systems, "
        "render each system as a separate ROS line. If a differential is "
        "explicitly stated ('could be X vs Y vs Z'), list each option in "
        "the Assessment as the physician phrased it — do not add "
        "options."
    ),
    "pediatrics": (
        "Style: attribute statements to the appropriate speaker when the "
        "transcript makes it identifiable — 'Mother reports', 'Father "
        "noted', 'Child describes' — defaulting to 'Caregiver' when "
        "ambiguous. Growth parameters and immunization status should be "
        "captured verbatim if discussed (e.g. '50th percentile for "
        "weight at 12 months', 'MMR up to date')."
    ),
}


def get_specialty_style(specialty_key: str) -> str:
    """Return the style snippet for ``specialty_key``, or an empty string
    if the specialty has no snippet defined.

    Specialty keys that aren't in the table (e.g. legacy / experimental
    templates) silently degrade to no snippet rather than erroring —
    the base prompt still works on its own.
    """
    return _STYLE.get(specialty_key, "")
