"""Seed demo data for Perry (ortho) and Marie (plastic) — for live demos.

Inserts a realistic mix of completed, awaiting-review, and recent sessions
plus their Stage 1 notes so each account has populated dashboards.

Idempotent: deterministic UUIDs (uuid5 from a stable namespace). Re-running
the script skips sessions that already exist.

Usage (from docker):
    docker compose exec aurion-api python scripts/seed_demo.py
"""

from __future__ import annotations

import asyncio
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

_backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_root))

from sqlalchemy import select  # noqa: E402

from app.core.database import async_session_factory  # noqa: E402
from app.core.models import NoteVersionModel, SessionModel  # noqa: E402
from app.core.types import SessionState  # noqa: E402

# Stable UUID5 namespace so re-runs produce the same session IDs.
_DEMO_NS = uuid.UUID("11111111-2222-3333-4444-555555555555")

PERRY_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")  # plastic surgery
MARIE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")  # orthopedic surgery


def _section(section_id: str, title: str, claims: list[dict], status: str = "populated") -> dict:
    return {"id": section_id, "title": title, "status": status, "claims": claims}


def _claim(idx: int, text: str, quote: str) -> dict:
    return {
        "id": f"c{idx}",
        "text": text,
        "source_type": "transcript",
        "source_id": f"seg_{idx:03d}",
        "source_quote": quote,
    }


# ── Perry's cases (Orthopedic surgery) ──────────────────────────────────────

PERRY_CASES = [
    {
        "key": "ortho_knee_meniscus",
        "specialty": "orthopedic_surgery",
        "state": SessionState.EXPORTED,
        "days_ago": 1,
        "completeness": 0.92,
        "approved": True,
        "sections": [
            _section("chief_complaint", "Chief Complaint", [
                _claim(1, "Physician noted patient presents with right knee pain for two weeks, worsening with activity.",
                       "Patient presents with right knee pain for the past two weeks."),
            ]),
            _section("hpi", "History of Present Illness", [
                _claim(2, "Physician noted pain began gradually without specific injury, aggravated by stairs and prolonged standing.",
                       "The pain began gradually without a specific injury, worse on stairs."),
                _claim(3, "Physician noted no locking, no giving way, no constitutional symptoms.",
                       "No locking, no giving way, no fevers."),
            ]),
            _section("physical_exam", "Physical Examination", [
                _claim(4, "Physician noted tenderness on palpation at the medial joint line of the right knee.",
                       "Tenderness on palpation at the medial joint line."),
                _claim(5, "Physician noted range of motion restricted to approximately 110 degrees of flexion.",
                       "Range of motion restricted to about 110 degrees of flexion."),
                _claim(6, "Physician noted McMurray test positive on the right.",
                       "McMurray is positive on the right."),
            ]),
            _section("imaging_review", "Imaging Review", [
                _claim(7, "Physician noted MRI of the right knee shows medial meniscus tear consistent with bucket-handle pattern.",
                       "MRI shows a medial meniscus tear, looks like a bucket-handle pattern."),
            ]),
            _section("assessment", "Assessment", [
                _claim(8, "Physician stated working diagnosis of medial meniscus tear, right knee.",
                       "Working diagnosis is medial meniscus tear, right knee."),
            ]),
            _section("plan", "Plan", [
                _claim(9, "Physician planned arthroscopic partial meniscectomy and referred to physiotherapy preoperatively.",
                       "We will plan for arthroscopic partial meniscectomy and start physio in the meantime."),
            ]),
        ],
    },
    {
        "key": "ortho_shoulder_rcr",
        "specialty": "orthopedic_surgery",
        "state": SessionState.EXPORTED,
        "days_ago": 3,
        "completeness": 0.88,
        "approved": True,
        "sections": [
            _section("chief_complaint", "Chief Complaint", [
                _claim(1, "Physician noted patient presents with left shoulder pain and weakness for six weeks.",
                       "Left shoulder pain and weakness for about six weeks."),
            ]),
            _section("hpi", "History of Present Illness", [
                _claim(2, "Physician noted onset after lifting heavy boxes during a move, no acute trauma.",
                       "It started after I helped move some heavy boxes."),
                _claim(3, "Physician noted night pain disturbing sleep, partial relief with NSAIDs.",
                       "Wakes me up at night, ibuprofen helps a little."),
            ]),
            _section("physical_exam", "Physical Examination", [
                _claim(4, "Physician noted painful arc between 70 and 110 degrees abduction on the left.",
                       "Painful arc between roughly 70 and 110 degrees on the left."),
                _claim(5, "Physician noted positive Hawkins-Kennedy and empty can tests on the left.",
                       "Hawkins-Kennedy positive, empty can also positive on the left."),
                _claim(6, "Physician noted 4/5 strength in supraspinatus and infraspinatus on the left.",
                       "Supraspinatus and infraspinatus testing 4 out of 5 on the left."),
            ]),
            _section("imaging_review", "Imaging Review", [
                _claim(7, "Physician noted MRI shows partial-thickness articular-sided supraspinatus tear, no full-thickness retraction.",
                       "MRI shows a partial-thickness articular-sided supraspinatus tear, no full-thickness retraction."),
            ]),
            _section("assessment", "Assessment", [
                _claim(8, "Physician stated working diagnosis of left rotator cuff partial-thickness tear with subacromial impingement.",
                       "Looks like a partial cuff tear with impingement, left side."),
            ]),
            _section("plan", "Plan", [
                _claim(9, "Physician ordered subacromial corticosteroid injection and structured physiotherapy for six weeks; surgical consultation if no improvement.",
                       "We'll do a subacromial injection, six weeks of physio, then reassess for surgery."),
            ]),
        ],
    },
    {
        "key": "ortho_lumbar_radic",
        "specialty": "orthopedic_surgery",
        "state": SessionState.EXPORTED,
        "days_ago": 7,
        "completeness": 0.85,
        "approved": True,
        "sections": [
            _section("chief_complaint", "Chief Complaint", [
                _claim(1, "Physician noted patient presents with low back pain radiating down the right leg for one month.",
                       "Low back pain shooting down my right leg for about a month."),
            ]),
            _section("hpi", "History of Present Illness", [
                _claim(2, "Physician noted pain follows L5 dermatomal distribution to the dorsum of the foot.",
                       "Pain runs down the back of my thigh into the top of my foot."),
                _claim(3, "Physician noted no bowel or bladder dysfunction, no saddle anesthesia.",
                       "No problems with bowel or bladder, no numbness in the saddle area."),
            ]),
            _section("physical_exam", "Physical Examination", [
                _claim(4, "Physician noted positive straight-leg-raise on the right at 45 degrees.",
                       "Straight-leg-raise positive on the right at about 45 degrees."),
                _claim(5, "Physician noted decreased sensation along the L5 dermatome on the right.",
                       "Decreased sensation in the L5 dermatome on the right."),
                _claim(6, "Physician noted 4/5 dorsiflexion strength on the right.",
                       "Dorsiflexion 4 out of 5 on the right."),
            ]),
            _section("imaging_review", "Imaging Review", [
                _claim(7, "Physician noted MRI shows L4-L5 right paracentral disc protrusion with L5 nerve root compression.",
                       "MRI shows an L4-L5 paracentral disc, compressing the L5 nerve root on the right."),
            ]),
            _section("assessment", "Assessment", [
                _claim(8, "Physician stated working diagnosis of L5 radiculopathy secondary to L4-L5 disc herniation.",
                       "L5 radiculopathy from the L4-L5 disc."),
            ]),
            _section("plan", "Plan", [
                _claim(9, "Physician referred to spine surgery, prescribed gabapentin titration, ordered PT for core stabilization.",
                       "Referring to spine, starting gabapentin, and PT for core stability."),
            ]),
        ],
    },
    {
        "key": "ortho_hip_oa",
        "specialty": "orthopedic_surgery",
        "state": SessionState.AWAITING_REVIEW,
        "days_ago": 0,  # Today — not approved yet, needs review
        "completeness": 0.79,
        "approved": False,
        "sections": [
            _section("chief_complaint", "Chief Complaint", [
                _claim(1, "Physician noted patient presents with progressive right hip pain for 18 months.",
                       "Right hip pain getting worse over the last 18 months."),
            ]),
            _section("hpi", "History of Present Illness", [
                _claim(2, "Physician noted pain in groin region, worse with weight-bearing, limiting walking distance to two blocks.",
                       "Hurts in the groin, worse when I walk, can only do about two blocks."),
            ]),
            _section("physical_exam", "Physical Examination", [
                _claim(3, "Physician noted internal rotation restricted to approximately 10 degrees on the right.",
                       "Internal rotation about 10 degrees on the right."),
                _claim(4, "Physician noted positive FABER and FADIR tests on the right.",
                       "FABER and FADIR positive on the right."),
            ]),
            _section("imaging_review", "Imaging Review", [
                _claim(5, "Physician noted radiographs show severe joint space narrowing, subchondral sclerosis, and osteophyte formation at the right hip.",
                       "X-rays show severe joint space narrowing with sclerosis and osteophytes on the right."),
            ]),
            _section("assessment", "Assessment", [
                _claim(6, "Physician stated working diagnosis of severe right hip osteoarthritis.",
                       "Severe right hip osteoarthritis."),
            ]),
            _section("plan", "Plan", [
                _claim(7, "Physician discussed total hip arthroplasty as definitive treatment, will proceed with preoperative workup.",
                       "We'll talk about total hip replacement and start the preop workup."),
            ]),
        ],
    },
    {
        "key": "ortho_wrist_followup",
        "specialty": "orthopedic_surgery",
        "state": SessionState.CONSENT_PENDING,
        "days_ago": 0,
        "completeness": 0.0,
        "approved": False,
        "sections": [],
    },
]


# ── Marie's cases (Plastic surgery) ────────────────────────────────────────

MARIE_CASES = [
    {
        "key": "plastic_breast_recon_postop",
        "specialty": "plastic_surgery",
        "state": SessionState.EXPORTED,
        "days_ago": 2,
        "completeness": 0.90,
        "approved": True,
        "sections": [
            _section("chief_complaint", "Chief Complaint", [
                _claim(1, "Physician noted patient presents for two-week postoperative review following DIEP flap breast reconstruction.",
                       "She's here for two-week post-op after the DIEP flap reconstruction."),
            ]),
            _section("hpi", "History of Present Illness", [
                _claim(2, "Physician noted patient reports manageable pain and is tolerating oral analgesics without issue.",
                       "Pain is manageable, taking the oral pain medications without trouble."),
                _claim(3, "Physician noted no fever, no chills, no purulent drainage.",
                       "No fevers, no chills, no pus."),
            ]),
            _section("wound_assessment", "Wound Assessment", [
                _claim(4, "Physician noted incisions well approximated with no signs of dehiscence or infection.",
                       "Incisions well approximated, no dehiscence, no signs of infection."),
                _claim(5, "Physician noted minimal serous drainage from the abdominal donor site, no purulence.",
                       "Some serous drainage from the abdominal site, nothing purulent."),
                _claim(6, "Physician noted reconstructed breast flap warm, well-perfused, capillary refill brisk.",
                       "The flap is warm, well-perfused, capillary refill brisk."),
            ]),
            _section("imaging_review", "Imaging Review", [], status="not_captured"),
            _section("assessment", "Assessment", [
                _claim(7, "Physician stated patient is healing as expected at two weeks postoperative.",
                       "She's healing as expected at two weeks post-op."),
            ]),
            _section("plan", "Plan", [
                _claim(8, "Physician planned drain removal at next visit, continue current activity restrictions, follow-up in two weeks.",
                       "We'll pull the drains next visit, keep the activity restrictions, see her again in two weeks."),
            ]),
        ],
    },
    {
        "key": "plastic_skin_lesion",
        "specialty": "plastic_surgery",
        "state": SessionState.EXPORTED,
        "days_ago": 4,
        "completeness": 0.86,
        "approved": True,
        "sections": [
            _section("chief_complaint", "Chief Complaint", [
                _claim(1, "Physician noted patient presents with a changing pigmented lesion on the left forearm.",
                       "Patient noticed a mole on her left forearm that's been changing."),
            ]),
            _section("hpi", "History of Present Illness", [
                _claim(2, "Physician noted lesion has enlarged over six months and recently began to itch and occasionally bleed.",
                       "It's been getting bigger over six months, now itches and bleeds sometimes."),
            ]),
            _section("wound_assessment", "Wound Assessment", [
                _claim(3, "Physician noted asymmetric pigmented lesion measuring 8 by 6 millimeters on the dorsal left forearm.",
                       "Asymmetric pigmented lesion, about 8 by 6 millimeters, dorsal left forearm."),
                _claim(4, "Physician noted irregular borders with variable pigmentation.",
                       "Borders are irregular with variable pigmentation."),
            ]),
            _section("imaging_review", "Imaging Review", [], status="not_captured"),
            _section("assessment", "Assessment", [
                _claim(5, "Physician stated the lesion is concerning for atypical melanocytic process and warrants excisional biopsy.",
                       "This lesion is suspicious for an atypical melanocytic process, needs excisional biopsy."),
            ]),
            _section("plan", "Plan", [
                _claim(6, "Physician planned excisional biopsy with 2 millimeter margins and will book within two weeks pending pathology.",
                       "Excisional biopsy with 2 mm margins, scheduled in the next two weeks, await path."),
            ]),
        ],
    },
    {
        "key": "plastic_burn_dressing",
        "specialty": "plastic_surgery",
        "state": SessionState.EXPORTED,
        "days_ago": 8,
        "completeness": 0.87,
        "approved": True,
        "sections": [
            _section("chief_complaint", "Chief Complaint", [
                _claim(1, "Physician noted patient presents for dressing change following second-degree thermal burn to right hand.",
                       "Dressing change for the second-degree burn on her right hand."),
            ]),
            _section("hpi", "History of Present Illness", [
                _claim(2, "Physician noted burn occurred eight days prior from a kitchen oil splash, partial-thickness involvement.",
                       "Happened eight days ago, oil splash in the kitchen, partial thickness."),
            ]),
            _section("wound_assessment", "Wound Assessment", [
                _claim(3, "Physician noted burn area on the dorsal right hand approximately 6 by 4 centimeters with re-epithelialization at the periphery.",
                       "Burn on the dorsum of her right hand, about 6 by 4 cm, edges starting to re-epithelialize."),
                _claim(4, "Physician noted no eschar, no signs of infection, range of motion preserved at all digits.",
                       "No eschar, no infection, full range of motion in all the fingers."),
            ]),
            _section("imaging_review", "Imaging Review", [], status="not_captured"),
            _section("assessment", "Assessment", [
                _claim(5, "Physician stated burn is healing appropriately at day eight without complications.",
                       "Healing appropriately at day eight, no complications."),
            ]),
            _section("plan", "Plan", [
                _claim(6, "Physician planned silver sulfadiazine dressing changes every other day and follow-up in one week.",
                       "Silver sulfadiazine dressing changes every other day, see her back in a week."),
            ]),
        ],
    },
    {
        "key": "plastic_septorhinoplasty_consult",
        "specialty": "plastic_surgery",
        "state": SessionState.AWAITING_REVIEW,
        "days_ago": 0,
        "completeness": 0.81,
        "approved": False,
        "sections": [
            _section("chief_complaint", "Chief Complaint", [
                _claim(1, "Physician noted patient presents for consultation regarding septorhinoplasty.",
                       "She's here to talk about septorhinoplasty."),
            ]),
            _section("hpi", "History of Present Illness", [
                _claim(2, "Physician noted patient reports chronic nasal obstruction and dissatisfaction with dorsal hump.",
                       "Trouble breathing through her nose, doesn't like the dorsal hump."),
                _claim(3, "Physician noted history of nasal trauma at age 14.",
                       "Broke her nose at age 14."),
            ]),
            _section("wound_assessment", "Wound Assessment", [
                _claim(4, "Physician noted external nasal exam shows dorsal hump and slight rightward deviation.",
                       "There's a dorsal hump and a slight deviation to the right."),
                _claim(5, "Physician noted internal exam shows septal deviation toward the right with right-sided turbinate hypertrophy.",
                       "Septum deviated to the right, right-sided turbinate hypertrophy."),
            ]),
            _section("imaging_review", "Imaging Review", [], status="not_captured"),
            _section("assessment", "Assessment", [
                _claim(6, "Physician stated diagnosis of dorsal hump deformity with deviated septum and turbinate hypertrophy, candidate for septorhinoplasty.",
                       "Dorsal hump, deviated septum, turbinate hypertrophy — good candidate for septorhinoplasty."),
            ]),
            _section("plan", "Plan", [
                _claim(7, "Physician planned to review preoperative photographs and book septorhinoplasty in the next surgical block.",
                       "We'll review the preop photos and book her for the next surgical block."),
            ]),
        ],
    },
    {
        "key": "plastic_finger_lac",
        "specialty": "plastic_surgery",
        "state": SessionState.IDLE,
        "days_ago": 0,
        "completeness": 0.0,
        "approved": False,
        "sections": [],
    },
]


# ── Insertion logic ────────────────────────────────────────────────────────


def _build_note_content(session_id: uuid.UUID, case: dict) -> str:
    note = {
        "session_id": str(session_id),
        "stage": 1,
        "version": 1,
        "provider_used": "demo",
        "specialty": case["specialty"],
        "completeness_score": case["completeness"],
        "sections": case["sections"],
    }
    return json.dumps(note)


async def _seed_for_user(clinician_id: uuid.UUID, cases: list[dict], label: str) -> tuple[int, int]:
    """Returns (sessions_created, notes_created)."""
    sessions_created = 0
    notes_created = 0

    async with async_session_factory() as db:
        for case in cases:
            session_id = uuid.uuid5(_DEMO_NS, f"{clinician_id}:{case['key']}")
            existing = await db.execute(
                select(SessionModel).where(SessionModel.id == session_id)
            )
            if existing.scalar_one_or_none() is not None:
                continue

            ts = datetime.now(timezone.utc) - timedelta(days=case["days_ago"], hours=2)
            session = SessionModel(
                id=session_id,
                clinician_id=clinician_id,
                specialty=case["specialty"],
                state=case["state"],
                consent_confirmed=case["state"] != SessionState.IDLE,
                output_language="en",
                encounter_type="doctor_patient",
                created_at=ts,
                updated_at=ts,
            )
            db.add(session)
            sessions_created += 1

            if case["sections"]:
                content = _build_note_content(session_id, case)
                note = NoteVersionModel(
                    session_id=session_id,
                    version=1,
                    stage=1,
                    provider_used="demo",
                    specialty=case["specialty"],
                    completeness_score=case["completeness"],
                    content=content,
                    is_approved=case["approved"],
                    created_at=ts,
                )
                db.add(note)
                notes_created += 1

        await db.commit()

    print(f"  {label}: {sessions_created} sessions, {notes_created} notes inserted")
    return sessions_created, notes_created


async def main() -> None:
    print("=" * 60)
    print("Aurion Demo Data Seed")
    print("=" * 60)
    print()
    print("Seeding sessions and Stage 1 notes for Perry & Marie.")
    print()
    # Perry = plastic, Marie = ortho (matches CLAUDE.md pilot description).
    p_sessions, p_notes = await _seed_for_user(PERRY_ID, MARIE_CASES, "perry@creoq.ca (plastic)")
    m_sessions, m_notes = await _seed_for_user(MARIE_ID, PERRY_CASES, "marie@creoq.ca (orthopedic)")
    print()
    print("=" * 60)
    print(f"Total: {p_sessions + m_sessions} sessions, {p_notes + m_notes} notes")
    print("Re-run anytime — already-seeded rows are skipped.")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
