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

from app.modules.config.appconfig_client import get_config

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
        "Style: document the functional picture the physician describes — "
        "gait (antalgic, normal, side of limp), weight-bearing and loading "
        "tolerance, sport- or activity-specific movements, and pain at "
        "rest vs with loading. In the exam, capture range of motion as "
        "degrees (active vs passive when distinguished), strength on the "
        "0-5 scale when graded, and named special tests with their result "
        "and side (e.g. 'McMurray positive on the right'). Imaging review "
        "notes modality + laterality + view. Record only what is stated — "
        "never infer a diagnosis or injury mechanism."
    ),
    "emergency_medicine": (
        "Style: lead with vital signs — capture each value with units as "
        "stated or shown (BP, HR, RR, temperature, SpO2) — and the chief "
        "complaint. Document investigations (labs, ECG, imaging) as the "
        "results are stated, and time-stamp critical interventions when "
        "the transcript provides times. The Disposition section is "
        "MANDATORY and must be sourced to a physician statement — admit / "
        "discharge / transfer / observation — with any follow-up "
        "instructions. Record the physician's stated working diagnosis "
        "verbatim; never infer severity or interpret results."
    ),
    "general": (
        "Style: favour brevity and objective, measurable phrasing — "
        "terse, telegraphic findings are appropriate (e.g. 'BP 132/84, HR "
        "78, afebrile; chest clear'). Capture vitals with units and "
        "physical findings as stated; use full sentences only when the "
        "physician narrates in prose. Record the assessment as the "
        "physician states it; never add interpretation."
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


# ── Grounded Synthesis Mode variants (v3.2, #552 / GS-3) ────────────────────
#
# Used by `get_specialty_style` ONLY when feature_flags.grounded_synthesis_enabled
# is ON. Each entry mirrors the descriptive snippet above with the final
# anti-synthesis clause swapped for a grounding-required one: the assessment/plan
# MAY be synthesized from the captured findings, but every statement must cite
# its source — never an unsupported conclusion. Kept as a parallel dict (not
# string surgery) so each clinical snippet stays independently reviewable.
# Only the 5 MVP specialties (those with an anti-synthesis clause) have a
# grounded variant; post-MVP specialties fall through to the descriptive snippet.
_GROUNDED_STYLE: dict[str, str] = {
    "orthopedic_surgery": (
        "Style: document the exam in the order the physician follows, leading "
        "each finding with the structure or test name — inspection, palpation "
        "(name the site, e.g. 'medial joint line'), range of motion, strength, "
        "special tests, neurovascular status — using precise anatomical terms. "
        "Capture, only as stated: range of motion as degrees (active vs passive "
        "when distinguished); strength on the 0-5 scale when graded (e.g. "
        "'4/5'); named special tests with their result and side (e.g. 'Lachman "
        "negative on the left', 'McMurray positive on the right'); and "
        "laterality wherever mentioned. Imaging review must note modality + "
        "laterality + the specific view for each finding (e.g. 'standing AP "
        "view', 'lateral projection', 'sunrise/Merchant view'). In the "
        "assessment you MAY synthesize the working picture from the captured "
        "findings: one claim per working diagnosis, plus contributing factors "
        "the physician relates — each grounded by citing the exam/imaging/"
        "history source(s) it rests on (cite several where relevant); never "
        "state a diagnosis the cited findings do not support. Render the plan "
        "one item per claim, grouped as investigations, referrals, options "
        "discussed with their trade-offs, risks counselled, activity advice, "
        "and follow-up — each cited to what the physician stated."
    ),
    "plastic_surgery": (
        "Style: document wounds with the standard assessment fields the "
        "physician states — anatomical location; dimensions as length × "
        "width × depth in centimetres; wound-bed tissue types and proportions "
        "(granulation, slough, eschar, necrosis); exudate amount and character; "
        "wound edges (undermining, tunnelling); and periwound skin. For flaps "
        "and grafts, capture viability descriptors as stated — colour match, "
        "capillary refill, perfusion, temperature. You MAY synthesize a "
        "grounded assessment and plan from the captured wound findings — cite "
        "each statement to its source; never infer a healing trajectory or "
        "wound aetiology the cited findings do not support."
    ),
    "musculoskeletal": (
        "Style: document the functional picture the physician describes — "
        "gait, weight-bearing and loading tolerance, activity-specific "
        "movements, and pain at rest vs with loading. In the exam, capture "
        "range of motion as degrees (active vs passive when distinguished), "
        "strength on the 0-5 scale when graded, and named special tests with "
        "result and side. Imaging review notes modality + laterality + view. "
        "You MAY synthesize a grounded assessment that cites the exam/imaging "
        "source(s) for each statement — never infer a diagnosis or injury "
        "mechanism beyond what the cited findings support."
    ),
    "emergency_medicine": (
        "Style: lead with vital signs — each value with units as stated or "
        "shown (BP, HR, RR, temperature, SpO2) — and the chief complaint. "
        "Document investigations (labs, ECG, imaging) as results are stated, "
        "and time-stamp critical interventions when the transcript provides "
        "times. The Disposition section is MANDATORY and must be sourced to a "
        "physician statement — admit / discharge / transfer / observation — "
        "with any follow-up. You MAY synthesize a grounded assessment and "
        "disposition rationale, each statement must cite its source; never infer "
        "severity beyond what the cited results support."
    ),
    "general": (
        "Style: favour brevity and objective, measurable phrasing — terse, "
        "telegraphic findings are appropriate (e.g. 'BP 132/84, HR 78, "
        "afebrile; chest clear'). Capture vitals with units and physical "
        "findings as stated; use full sentences only when the physician "
        "narrates in prose. You MAY synthesize the assessment and plan from "
        "the captured findings when every statement cites its source — never "
        "add a conclusion the cited findings do not support."
    ),
}


def get_specialty_style(specialty_key: str) -> str:
    """Return the style snippet for ``specialty_key``, or an empty string
    if the specialty has no snippet defined.

    Under Grounded Synthesis Mode (#552, GS-3) — when
    ``feature_flags.grounded_synthesis_enabled`` is ON — the grounded variant
    is returned for the 5 MVP specialties that have one. OFF (the default), or
    for a specialty without a grounded variant, the descriptive snippet is
    returned (byte-identical to pre-v3.2).

    Specialty keys that aren't in the table (e.g. legacy / experimental
    templates) silently degrade to no snippet rather than erroring —
    the base prompt still works on its own.
    """
    if get_config().feature_flags.grounded_synthesis_enabled:
        grounded = _GROUNDED_STYLE.get(specialty_key)
        if grounded is not None:
            return grounded
    return _STYLE.get(specialty_key, "")
