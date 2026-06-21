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

Keep snippets tight — a focused pointer beats a textbook, and longer
prompts dilute attention. The pilot specialties (orthopedic_surgery,
plastic_surgery) carry richer, section-targeted guidance grounded in
clinical-documentation standards (AAOS ROM/strength conventions, wound
assessment fields); the rest stay terse until validated against pilot
sessions. All guidance is still style-only + descriptive (capture X *when
stated* — never instruct the model to diagnose, interpret, or add content).
"""

from __future__ import annotations

_STYLE: dict[str, str] = {
    # ── MVP templates (CLAUDE.md §"Specialty Templates") ─────────────
    "orthopedic_surgery": (
        "Style: document the exam in the order the physician follows — "
        "inspection, palpation, range of motion, strength, special tests, "
        "neurovascular status — using precise anatomical terms (e.g. "
        "'medial joint line', 'lateral malleolus'). Capture, only as "
        "stated: range of motion as degrees (active vs passive when the "
        "physician distinguishes them); strength on the 0-5 scale when "
        "graded (e.g. '4/5'); named special tests with their result and "
        "side (e.g. 'Lachman negative on the left', 'McMurray positive on "
        "the right'); and laterality (right/left) wherever mentioned. "
        "Imaging review must note modality + laterality + view (e.g. 'AP "
        "and lateral right knee X-ray'). Record the physician's stated "
        "working diagnosis verbatim in the assessment — never add "
        "differentials and never interpret findings."
    ),
    "plastic_surgery": (
        "Style: document wounds with the standard assessment fields the "
        "physician states — anatomical location; dimensions as length × "
        "width × depth in centimetres; wound-bed tissue types and their "
        "proportions (granulation, slough, eschar, necrosis); exudate "
        "amount and character (serous, serosanguineous, purulent; colour; "
        "odour); wound edges (well-approximated, undermining, tunnelling); "
        "and periwound skin (erythema, induration, maceration). For flaps "
        "and grafts, capture viability descriptors as stated — colour "
        "match, capillary refill time, perfusion, temperature. Record "
        "signs of infection and healing observations exactly as the "
        "physician describes them; never infer a healing trajectory or "
        "wound aetiology."
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
