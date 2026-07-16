"""LOCAL A/B harness — does the new template AI-instructions produce a
complete, grounded note vs the current thin one? NOT committed; scratch only.

Runs the REAL note-gen path for two template variants against the same
Lipo 360 transcript:
  A = plastic_surgery sections (incl wound/imaging) + terse descriptive prompt
      -> reproduces the thin note + the misleading completeness score
  B = consult-shaped sections + the complete grounded-scribe prompt
      -> the proposed fix

For each: provider.generate_note() -> critique_note() -> calculate_completeness()
— byte-for-byte the calls generate_stage1_note() makes (minus DB persistence,
which is irrelevant to comparing output). Uses the active provider (OpenAI
locally).

Run:  docker exec -w /app aurion-api python -m app._ab_lipo_test
"""

from __future__ import annotations

import asyncio

from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.config.provider_registry import get_registry
from app.modules.note_gen.critique import critique_note
from app.modules.note_gen.service import calculate_completeness, get_template

# ── Lipo 360 transcript (mirrors the user's deployed-dev session) ────────────
# (start_ms, end_ms, speaker, text, is_visual_trigger, trigger_type)
SEGMENTS = [
    (0, 5000, "physician", "Hi, come on in. So what brings you in to see me today?", False, None),
    (5000, 16000, "patient", "I'm here for a Lipo 360 consultation. I've got this muffin top that's been really bothering me, and honestly I'd love to be able to see my abs again.", False, None),
    (16000, 27000, "patient", "It's gotten worse over the last couple of years, especially since I went into perimenopause — everything seems to settle around my middle now.", False, None),
    (27000, 37000, "physician", "I understand. Has your weight been stable, and have you been able to exercise and watch your diet?", False, None),
    (37000, 48000, "patient", "Yeah, I work out three or four times a week and I eat pretty clean, but this lower belly and the love handles just won't go anywhere.", False, None),
    (48000, 57000, "physician", "Okay. Let's go over your medical history. Do you have any medical conditions?", False, None),
    (57000, 66000, "patient", "I have Crohn's disease, and I also get pretty bad dry eyes.", False, None),
    (66000, 76000, "physician", "And what medications are you currently taking?", False, None),
    (76000, 87000, "patient", "I'm on Humira for the Crohn's, I'm taking Ozempic, and I'm on hormone replacement therapy for the menopause symptoms.", False, None),
    (87000, 95000, "physician", "Do you have any allergies to medications?", False, None),
    (95000, 103000, "patient", "Yes — penicillin. It gives me a bad rash.", False, None),
    (103000, 113000, "physician", "Good to know. Any family history of medical problems, particularly cancer?", False, None),
    (113000, 124000, "patient", "My mother had breast cancer. I had a mammogram last year though, and it came back normal.", False, None),
    (124000, 136000, "physician", "Thank you. Let me take a few measurements and then examine you. You're about five foot four, and you're one hundred and sixty pounds today.", False, None),
    (136000, 147000, "physician", "Examining the abdomen now — I can pinch a few centimeters of fat, more concentrated in the lower abdomen below the belly button.", True, "physical_exam"),
    (147000, 158000, "physician", "Along the flanks, the love handles, there's a good amount of pinchable fat on both sides.", True, "physical_exam"),
    (158000, 168000, "physician", "Around to the back, there's some fullness over the bra line and the upper back as well.", True, "physical_exam"),
    (168000, 179000, "physician", "Skin quality is good with decent elasticity, only mild laxity in the lower abdomen. No hernias and no significant diastasis.", True, "physical_exam"),
    (179000, 191000, "physician", "So putting it together — you're a straightforward, good candidate for a 360 liposuction. The skin should retract nicely.", False, None),
    (191000, 205000, "physician", "What I'd recommend is an awake Lipo 360 — we treat the abdomen, the flanks, and the back in one session. I'd add J-plasma to tighten the skin, and we may do a small skin pinch in the lower abdomen if needed.", False, None),
    (205000, 219000, "physician", "Let me walk you through the risks. You can feel faint during the awake procedure. Afterward there's swelling, bruising, and the contour can be a little lumpy or bumpy early on as it settles.", False, None),
    (219000, 231000, "physician", "There can also be numbness, areas of firmness, contour irregularity, and asymmetry. Infection is rare but possible. We'd go over all of this again before surgery.", False, None),
    (231000, 243000, "physician", "For recovery, plan on three to four weeks off from exercising, and I'd take about a week off work. You'll be in a compression garment during that time.", False, None),
    (243000, 255000, "physician", "Separately, you mentioned the lines on your forehead — we can treat the upper brow with Botox. That area would take roughly twenty-five units.", False, None),
    (255000, 268000, "physician", "Here's the plan: we'll send you a consultation estimate. If you'd like to go ahead, you'll book with our surgical coordinator and we'll arrange a pre-op blood test.", False, None),
    (268000, 277000, "patient", "That all sounds good, thank you. I'll look out for the estimate.", False, None),
]

AI_OLD = (
    "Document the encounter descriptively. Record only what was directly said. "
    "Keep it brief — a handful of key claims, not dozens. Do not interpret, do "
    "not conclude, and do not add anything beyond the transcript."
)

AI_NEW = (
    "You are documenting a COMPLETE plastic surgery consultation note for "
    "Aurion Clinical AI. Produce a thorough, well-organized clinical note — the "
    "kind an experienced surgical scribe would write — that records everything "
    "discussed or observed in the encounter.\n\n"
    "Record, in detail:\n"
    "- Chief complaint / aesthetic concern in the patient's own terms.\n"
    "- HPI: goals, what bothers the patient, duration and triggers, prior "
    "treatments or surgeries.\n"
    "- Past medical & surgical history; current medications (note brand and "
    "generic where evident); allergies — always record allergies, and if none "
    "were discussed, state that explicitly.\n"
    "- Family history relevant to surgical risk.\n"
    "- Examination / anatomic assessment, broken out by region (abdomen, "
    "flanks, back, skin quality, tissue laxity, pinch test).\n"
    "- The provider's stated assessment of candidacy.\n"
    "- Procedure discussion: proposed procedure and technique, adjuncts, "
    "alternatives, and every risk, side effect, and limitation the provider "
    "reviewed.\n"
    "- Recovery and activity guidance.\n"
    "- Adjunct or secondary treatments discussed.\n"
    "- Plan and next steps.\n\n"
    "Rules:\n"
    "- Document and record only what is supported by the captured sources. "
    "Every statement must trace to its source.\n"
    "- Err toward more detail: capture each distinct point the provider made "
    "rather than collapsing them. A thorough consult note has dozens of "
    "recorded findings, not a handful.\n"
    "- Do not infer, conclude, or add clinical reasoning beyond what the "
    "provider stated. When the provider states an assessment or recommendation, "
    "record it and attribute it to the provider.\n"
    "- You may compute BMI when height and weight are both present, and note a "
    "drug's generic/brand equivalent; mark these as derived.\n"
    "- If a required section was not addressed, mark it not captured rather "
    "than inventing content.\n\n"
    "Return only valid JSON per the note schema. No preamble, no markdown."
)

CONSULT_SECTIONS = [
    ("chief_complaint", "Chief Complaint / Aesthetic Concern", "Why the patient came in, in their own terms"),
    ("hpi", "History of Present Illness", "Goals, what bothers the patient, duration, triggers, prior treatments"),
    ("past_medical_surgical_history", "Past Medical & Surgical History", "Conditions and prior surgeries"),
    ("medications_allergies", "Medications & Allergies", "Current medications and drug allergies"),
    ("family_history", "Family History", "Family history relevant to surgical risk"),
    ("examination", "Examination / Anatomic Assessment", "Exam by region: abdomen, flanks, back, skin quality, laxity, pinch test"),
    ("assessment_candidacy", "Assessment & Candidacy", "The provider's stated assessment of candidacy"),
    ("procedure_discussion_consent", "Procedure Discussion, Risks & Consent", "Proposed procedure, technique, adjuncts, alternatives, risks reviewed"),
    ("recovery_activity", "Recovery & Activity Guidance", "Downtime, activity restrictions, garments"),
    ("adjunct_treatments", "Adjunct Treatments", "Secondary or adjunct treatments discussed"),
    ("plan_next_steps", "Plan & Next Steps", "Estimate, booking, pre-op steps"),
]


def build_transcript() -> Transcript:
    segs = [
        TranscriptSegment(
            id=f"seg_{i:03d}", start_ms=s, end_ms=e, text=txt,
            speaker=spk, is_visual_trigger=trig, trigger_type=ttype,
        )
        for i, (s, e, spk, txt, trig, ttype) in enumerate(SEGMENTS)
    ]
    return Transcript(session_id="ab-lipo", provider_used="ab_test", segments=segs)


def variant_a() -> Template:
    base = get_template("plastic_surgery")  # real shipped sections (incl wound/imaging)
    return Template(
        key="lipo_baseline", display_name="Lipo (baseline / terse)",
        version="1.0", sections=base.sections, system_prompt=AI_OLD,
    )


def variant_b() -> Template:
    sections = [
        TemplateSection(id=sid, title=title, required=True, description=desc)
        for sid, title, desc in CONSULT_SECTIONS
    ]
    return Template(
        key="lipo_complete", display_name="Lipo (complete grounded-scribe)",
        version="1.0", sections=sections, system_prompt=AI_NEW,
    )


PROVIDER = "anthropic"  # local OpenAI key is invalid (401); Anthropic key works


async def generate(label: str, template: Template, transcript: Transcript):
    registry = get_registry()
    provider = registry.get_note_provider(override=PROVIDER)
    note = await provider.generate_note(
        transcript, template, stage=1, output_language="en",
        system_prompt=template.system_prompt,
        prior_context_text=None, participants=None, specialty_prefix=None,
    )
    note.session_id = "ab-lipo"
    note.stage = 1
    note.specialty = "plastic_surgery"
    try:
        await critique_note(note, transcript)
    except Exception as ex:  # noqa: BLE001
        print(f"[{label}] critique skipped: {ex!r}")
    note.completeness_score = round(calculate_completeness(note, template), 4)
    return note


def summarize(header: str, note) -> None:
    total = sum(len(s.claims) for s in note.sections)
    print(f"\n{'=' * 78}\n{header}\n{'=' * 78}")
    print(f"provider={note.provider_used}  completeness={note.completeness_score}  "
          f"sections={len(note.sections)}  total_claims={total}")
    for s in note.sections:
        print(f"\n## {s.title or s.id}  [{s.status}]  ({len(s.claims)} claims)")
        for c in s.claims:
            tag = f"{c.source_type}:{c.source_id}"
            print(f"   - {c.text}   [{tag}]")


async def main() -> None:
    transcript = build_transcript()
    a_t, b_t = variant_a(), variant_b()
    print("Running A (baseline terse + plastic_surgery sections)...")
    a = await generate("A", a_t, transcript)
    print("Running B (complete grounded-scribe + consult sections)...")
    b = await generate("B", b_t, transcript)

    summarize("VARIANT A — baseline terse  (current thin behaviour)", a)
    summarize("VARIANT B — complete grounded-scribe  (proposed fix)", b)

    print(f"\n\n{'#' * 78}\nHEADLINE\n{'#' * 78}")
    print(f"A: completeness={a.completeness_score}  "
          f"claims={sum(len(s.claims) for s in a.sections)}")
    print(f"B: completeness={b.completeness_score}  "
          f"claims={sum(len(s.claims) for s in b.sections)}")


if __name__ == "__main__":
    asyncio.run(main())
