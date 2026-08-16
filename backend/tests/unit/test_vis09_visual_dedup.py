"""VIS-09 — duplicate visual captions collapse before the merge.

The defect this closes, measured on session 30cccd75 (bb7dabb1, 180s exam +
X-ray clip): Stage 2 added ~85 visual claims, ~65 of them in Imaging Review
describing ~5 distinct things — dozens of restatements of one radiograph,
because frames are cadence-sampled and every frame became its own claim.

The safety property under test is narrow and load-bearing: dedup keys on
redundancy against SIBLING captions, never on wording. A caption with no
duplicate is never a candidate for removal, which is what keeps TE-4's
``test_merge_never_deletes_a_caption_for_its_wording`` true.
"""

from __future__ import annotations

import logging

from app.core.types import FrameCaption, Note, NoteSection
from app.modules.vision.service import classify_conflicts


def _caption(
    description: str,
    *,
    frame_id: str = "frame_1",
    confidence: str = "high",
    status: str = "ENRICHES",
) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id,
        session_id="s1",
        timestamp_ms=1000,
        audio_anchor_id="seg_001",
        provider_used="anthropic",
        visual_description=description,
        confidence=confidence,
        confidence_reason="",
        conflict_flag=False,
        conflict_detail=None,
        integration_status=status,
    )


def _note() -> Note:
    return Note(
        session_id="s1",
        stage=2,
        version=1,
        provider_used="anthropic",
        specialty="musculoskeletal",
        completeness_score=0.0,
        sections=[NoteSection(id="imaging_review", status="populated", claims=[])],
    )


def _statuses(captions):
    return [c.integration_status for c in captions]


# ── Real captions from session 30cccd75, Imaging Review ────────────────────
# Verbatim (trimmed) from the note produced 2026-08-16. The AP standing view
# was described this many times; a physician writes it once.

_AP_STANDING = [
    "A monitor displays a PACS/radiology viewer showing an AP view of bilateral knees side by side. A marker 'R' is visible on one image, indicating the right knee. A text label reading 'UPRIGHT' is visible on the image, indicating a weight-bearing/standing view.",
    "A monitor displays a radiograph showing two knee joints side by side in an AP (anteroposterior) standing view. The label 'UPRIGHT' is visible on the image, and an 'R' marker is visible on one side. On the image side bearing the 'R' marker, the medial joint space appears visibly narrowed compared to the lateral compartment.",
    "A monitor displays two knee radiographs side by side in AP projection. A label reading 'UPRIGHT' is visible, and a marker 'R' is visible on the left image. There is visible narrowing of the medial joint space compared to the lateral compartment.",
    "A computer monitor displays a digital radiograph viewer showing two knee X-ray images side by side. A label 'R' is visible on one image, and the text 'UPRIGHT' is displayed centrally, indicating weight-bearing AP standing views.",
    "A monitor displays a radiograph viewer showing a bilateral knee AP view. The label 'UPRIGHT' is visible, indicating a weight-bearing projection. A marker 'R' is visible on one side of the image. The medial compartments appear narrowed relative to the lateral compartments.",
    "A desktop monitor displays a bilateral AP standing knee radiograph. A label reading 'R' is visible on the left of the screen, and 'UPRIGHT' is visible centrally. Two knee joints are displayed side by side.",
]

_LATERAL = [
    "A monitor screen displays a lateral-projection plain radiograph of a knee. The osseous structures visible include the distal femur, proximal tibia, fibula head, and patella. No laterality marker is legible in the frame.",
    "A computer monitor displays a lateral-view knee radiograph. The distal femur, proximal tibia, and patella are visible. The patella is seen in profile. A small bony projection is visible on the inferior pole of the patella.",
    "A computer monitor displays a lateral-view knee radiograph. A vertical dashed line is overlaid on the image, consistent with a measurement or alignment tool. The patellar region is visible at the anterior of the joint.",
]

_SUNRISE = [
    "A PACS-style radiology viewer displays a close-up radiographic view consistent with a sunrise/Merchant (axial patellofemoral) projection, showing the patella and the trochlear groove. A small 'L' marker is visible.",
    "A computer monitor displays a radiographic imaging workstation. The large central panel shows a skyline (axial/sunrise) projection of a patella, with the patellofemoral joint visible. A white letter 'R' marker is visible.",
]


# ── AC-1 ───────────────────────────────────────────────────────────────────

def test_duplicate_captions_collapse_to_one():
    """AC-1 — N descriptions of one radiograph leave exactly one ENRICHES."""
    caps = [
        _caption(d, frame_id=f"frame_{i}") for i, d in enumerate(_AP_STANDING)
    ]
    classify_conflicts(caps, _note())

    survivors = [c for c in caps if c.integration_status == "ENRICHES"]
    assert len(survivors) == 1, _statuses(caps)
    assert sum(1 for c in caps if c.integration_status == "REPEATS") == len(caps) - 1


# ── AC-2 ───────────────────────────────────────────────────────────────────

def test_distinct_imaging_views_survive_dedup():
    """AC-2 — AP standing, lateral and sunrise are three findings, not one.

    The failure this guards is over-merging: all three share heavy vocabulary
    ("monitor", "radiograph", "patella", "visible"), so a naive similarity
    would collapse the whole imaging review into a single claim.
    """
    caps = [
        _caption(d, frame_id=f"ap_{i}") for i, d in enumerate(_AP_STANDING)
    ] + [
        _caption(d, frame_id=f"lat_{i}") for i, d in enumerate(_LATERAL)
    ] + [
        _caption(d, frame_id=f"sun_{i}") for i, d in enumerate(_SUNRISE)
    ]
    classify_conflicts(caps, _note())

    survivors = [c for c in caps if c.integration_status == "ENRICHES"]
    kept = " ".join(c.visual_description.lower() for c in survivors)
    assert "upright" in kept, "AP standing view was collapsed away"
    assert "lateral" in kept, "lateral view was collapsed away"
    assert any(w in kept for w in ("sunrise", "merchant", "skyline")), (
        "sunrise/Merchant view was collapsed away"
    )


# ── AC-3 ───────────────────────────────────────────────────────────────────

def test_lone_caption_never_dropped():
    """AC-3 — a cluster of one always survives."""
    caps = [_caption("A solitary observation of the left knee.")]
    classify_conflicts(caps, _note())
    assert caps[0].integration_status == "ENRICHES"


def test_te4_negative_findings_survive():
    """AC-3 — every phrase from TE-4's no-deletion guard survives.

    These are the captions a previous content-based regex destroyed. Each is a
    real clinical observation and several carry the only measurement present.
    """
    destroyed_before = [
        "Bone is not visible at the base of the ulcer.",
        "Necrotic tissue is not visible; the wound bed is uniformly pink.",
        "Unable to assess wound depth; margins are clean and approximated.",
        "The left knee is not visible; the right knee shows a 4cm effusion.",
        "There is no visible evidence of infection at the port site.",
        "The mole borders are not discernible; diameter approximately 8mm.",
    ]
    caps = [
        _caption(d, frame_id=f"frame_{i}")
        for i, d in enumerate(destroyed_before)
    ]
    classify_conflicts(caps, _note())

    for c in caps:
        assert c.integration_status == "ENRICHES", (
            f"caption dropped for its wording: {c.visual_description!r}"
        )


# ── AC-4 ───────────────────────────────────────────────────────────────────

def test_no_wording_based_deletion():
    """AC-4 — identical wording is dropped only when a SIBLING carries it.

    The same caption text survives alone and is deduped in company. That is
    the whole distinction between VIS-09 and the regex TE-4 banned.
    """
    text = "A monitor displays a lateral knee radiograph with a patellar spur."

    alone = [_caption(text)]
    classify_conflicts(alone, _note())
    assert alone[0].integration_status == "ENRICHES"

    together = [_caption(text, frame_id=f"f{i}") for i in range(3)]
    classify_conflicts(together, _note())
    assert sum(1 for c in together if c.integration_status == "ENRICHES") == 1


def test_conflicts_are_never_deduped_away():
    """A CONFLICTS caption is a physician-review gate — dedup must not eat it."""
    caps = [
        _caption(_AP_STANDING[0], frame_id="a", status="CONFLICTS"),
        _caption(_AP_STANDING[1], frame_id="b"),
        _caption(_AP_STANDING[2], frame_id="c"),
    ]
    classify_conflicts(caps, _note())
    assert caps[0].integration_status == "CONFLICTS"
    assert caps[0].conflict_flag is True


# ── AC-5 ───────────────────────────────────────────────────────────────────

def test_dropped_captions_are_logged_without_phi(caplog):
    """AC-5 — drops are auditable by frame_id, and log no caption text.

    Caption text may describe patient anatomy, so it must never reach a log
    line (CLAUDE.md: PHI never in logs).
    """
    caps = [
        _caption(
            "A monitor displays an AP standing radiograph of both knees, "
            "UPRIGHT label, R marker, medial joint space narrowed.",
            frame_id=f"frame_{i}",
        )
        for i in range(4)
    ]
    with caplog.at_level(logging.INFO, logger="aurion.vision"):
        classify_conflicts(caps, _note())

    text = caplog.text
    assert "Duplicate visual caption discarded" in text
    assert "frame_1" in text or "frame_2" in text or "frame_3" in text
    for fragment in ("UPRIGHT", "medial joint space", "radiograph"):
        assert fragment not in text, f"caption text leaked into logs: {fragment}"


# ── AC-6 ───────────────────────────────────────────────────────────────────

def test_real_session_30cccd75_collapses():
    """AC-6 — the real Imaging Review caption set collapses to a few claims.

    Eleven captions from the live run standing in for the ~65 observed; the
    ratio is what matters. All three distinct views must still be present.
    """
    caps = [
        _caption(d, frame_id=f"frame_{i}")
        for i, d in enumerate(_AP_STANDING + _LATERAL + _SUNRISE)
    ]
    classify_conflicts(caps, _note())

    survivors = [c for c in caps if c.integration_status == "ENRICHES"]
    assert len(survivors) <= 5, (
        f"{len(survivors)} survivors from {len(caps)} captions — "
        "dedup is not collapsing the run"
    )
    assert len(survivors) >= 3, "the three distinct views must all survive"


def test_empty_and_single_caption_sets_are_safe():
    """Degenerate inputs must not raise."""
    assert classify_conflicts([], _note()) == []
    one = [_caption("A single frame.")]
    assert classify_conflicts(one, _note()) == one
