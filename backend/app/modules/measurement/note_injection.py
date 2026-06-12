"""Route a physician-confirmed measurement into the note as a claim (#63).

A measurement only enters the note once the physician confirms it on-device
(design §4). When a confirmed ``MeasurementCitation`` is ingested, this maps
it to the right note section and appends a ``NoteClaim`` with
``source_type="measurement"`` — the same traceable-claim pattern the vision
and screen pipelines use (``merge_visual_citations``). The orchestration
layer (the ingest endpoint) loads the latest note, calls ``inject_into_note``,
and writes a new note version; this module stays pure (no DB, no I/O).

Descriptive-mode boundary (CLAUDE.md §descriptive; design §4): the claim
reports the number "approximately", with its method + the physician-confirmed
provenance. No trend, no interpretation, no diagnosis. The "approximate, not
certified" posture is carried structurally by ``certified_measurement=False``
on the citation itself.
"""

from __future__ import annotations

from app.core.types import MeasurementCitation, Note, NoteClaim

# Kind → ordered preference of target section ids. The measurement routes into
# the FIRST of these that the active note actually defines, so the same map
# works across specialties (plastic has wound_assessment; ortho/MSK/ER/general
# have physical_exam; MSK additionally has functional_assessment, the natural
# home for range-of-motion). A kind with no matching section is left
# un-injected (still persisted + listable) rather than forced somewhere wrong.
_SECTION_ROUTES: dict[str, tuple[str, ...]] = {
    "wound_length": ("wound_assessment", "physical_exam"),
    "wound_width": ("wound_assessment", "physical_exam"),
    "wound_area": ("wound_assessment", "physical_exam"),
    "rom_angle": ("functional_assessment", "physical_exam"),
}

# How a metric scale / capture method reads in the note. Factual, not certified.
_METHOD_LABELS: dict[str, str] = {
    "arkit_lidar": "iPhone AR, LiDAR",
    "arkit_world": "iPhone AR, world tracking",
    "fiducial_homography": "iPhone AR, fiducial scale",
    "vision_pose_3d": "iPhone AR, pose estimate",
    "ar_goniometer": "AR goniometer",
}


def claim_id_for(measurement_id: str) -> str:
    """Deterministic claim id so a re-injected measurement is identifiable."""
    return f"mclaim_{measurement_id}"


def _format_value(value: float) -> str:
    # Drop a trailing ".0" but keep real decimals (42.0 -> "42", 18.5 -> "18.5").
    return f"{value:g}"


def format_measurement_text(citation: MeasurementCitation) -> str:
    """Descriptive-mode claim text for a confirmed measurement.

    Examples (design §4):
      "Wound length measured at approximately 42 mm (iPhone AR, LiDAR,
       physician-confirmed)."
      "Range of motion measured at approximately 35 degrees (AR goniometer,
       physician-aligned)."
    """
    method = _METHOD_LABELS.get(citation.method, citation.method)
    val = _format_value(citation.value)
    if citation.kind == "rom_angle":
        return (
            f"Range of motion measured at approximately {val} degrees "
            f"({method}, physician-aligned)."
        )
    label = {
        "wound_length": "Wound length",
        "wound_width": "Wound width",
        "wound_area": "Wound area",
    }[citation.kind]
    unit = "cm²" if citation.unit == "cm2" else citation.unit
    return (
        f"{label} measured at approximately {val} {unit} "
        f"({method}, physician-confirmed)."
    )


def select_target_section(note: Note, kind: str):
    """The first routed section the note actually has, or None."""
    for section_id in _SECTION_ROUTES.get(kind, ()):
        section = note.get_section(section_id)
        if section is not None:
            return section
    return None


def already_injected(note: Note, measurement_id: str) -> bool:
    return any(
        claim.source_type == "measurement" and claim.source_id == measurement_id
        for section in note.sections
        for claim in section.claims
    )


def inject_into_note(note: Note, citation: MeasurementCitation) -> bool:
    """Append a measurement claim to the right section, in place.

    Returns True if the note was changed. No-op (False) when the measurement
    isn't physician-confirmed, the note already carries it (idempotent on
    ``measurement_id``), or no routed section exists in this note.
    """
    if not citation.physician_confirmed:
        return False
    if already_injected(note, citation.measurement_id):
        return False
    target = select_target_section(note, citation.kind)
    if target is None:
        return False

    target.claims.append(
        NoteClaim(
            id=claim_id_for(citation.measurement_id),
            text=format_measurement_text(citation),
            source_type="measurement",
            source_id=citation.measurement_id,
            source_quote=(
                f"[On-device {citation.method}, "
                f"{citation.confidence} confidence]"
            ),
        )
    )
    if target.status in ("not_captured", "pending_video", "processing_failed"):
        target.status = "populated"
    return True
