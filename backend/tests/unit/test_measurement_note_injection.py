"""#63 note-injection — routing a confirmed measurement into the note.

Pins the load-bearing behaviour of the pure injection layer: kind→section
routing across specialties, the descriptive-mode claim text (number reported
"approximately" with method + provenance, never interpreted), the
physician-confirmed gate, idempotency on measurement_id, and graceful no-op
when the active note has no section to carry the metric.
"""

from __future__ import annotations

from app.core.types import MeasurementCitation, Note, NoteClaim, NoteSection
from app.modules.measurement import note_injection as ni

# ── builders ─────────────────────────────────────────────────────────────────


def _note(*section_ids: str, specialty: str = "plastic_surgery") -> Note:
    return Note(
        session_id="s1", stage=1, provider_used="anthropic", specialty=specialty,
        sections=[NoteSection(id=sid, title=sid) for sid in section_ids],
    )


def _m(kind: str, value: float, unit: str, *, method="arkit_lidar",
       confidence="high", confirmed=True, mid="meas_001") -> MeasurementCitation:
    return MeasurementCitation(
        measurement_id=mid, session_id="s1", kind=kind, value=value, unit=unit,
        method=method, confidence=confidence, physician_confirmed=confirmed,
    )


_INTERPRETIVE = ("consistent with", "suggest", "suggests", "consider", "consider imaging",
                 "diagnos", "pathology", "since last", "% ", "trend", "worsen", "improv")


# ── claim text (descriptive mode) ─────────────────────────────────────────────


class TestClaimText:
    def test_wound_length_text(self):
        t = ni.format_measurement_text(_m("wound_length", 42.0, "mm"))
        assert t == ("Wound length measured at approximately 42 mm "
                     "(iPhone AR, LiDAR, physician-confirmed).")

    def test_wound_area_uses_cm2_glyph(self):
        t = ni.format_measurement_text(_m("wound_area", 3.2, "cm2"))
        assert "approximately 3.2 cm²" in t and "physician-confirmed" in t

    def test_rom_text_degrees_and_aligned(self):
        t = ni.format_measurement_text(
            _m("rom_angle", 35, "deg", method="ar_goniometer")
        )
        assert t == ("Range of motion measured at approximately 35 degrees "
                     "(AR goniometer, physician-aligned).")

    def test_value_drops_trailing_zero_keeps_decimals(self):
        assert "approximately 18 mm" in ni.format_measurement_text(
            _m("wound_width", 18.0, "mm"))
        assert "approximately 18.5 mm" in ni.format_measurement_text(
            _m("wound_width", 18.5, "mm"))

    def test_text_is_descriptive_not_interpretive(self):
        for kind, val, unit, method in (
            ("wound_length", 42.0, "mm", "arkit_lidar"),
            ("wound_area", 3.2, "cm2", "arkit_lidar"),
            ("rom_angle", 35, "deg", "ar_goniometer"),
        ):
            t = ni.format_measurement_text(_m(kind, val, unit, method=method)).lower()
            assert "approximately" in t
            assert not any(bad in t for bad in _INTERPRETIVE)


# ── section routing ───────────────────────────────────────────────────────────


class TestRouting:
    def test_wound_prefers_wound_assessment(self):
        note = _note("wound_assessment", "physical_exam")
        assert ni.select_target_section(note, "wound_length").id == "wound_assessment"

    def test_wound_falls_back_to_physical_exam(self):
        note = _note("hpi", "physical_exam", specialty="orthopedic_surgery")
        assert ni.select_target_section(note, "wound_width").id == "physical_exam"

    def test_rom_prefers_functional_assessment(self):
        note = _note("physical_exam", "functional_assessment", specialty="musculoskeletal")
        assert ni.select_target_section(note, "rom_angle").id == "functional_assessment"

    def test_rom_falls_back_to_physical_exam(self):
        note = _note("hpi", "physical_exam", specialty="orthopedic_surgery")
        assert ni.select_target_section(note, "rom_angle").id == "physical_exam"

    def test_no_target_returns_none(self):
        note = _note("chief_complaint", "hpi", "plan")
        assert ni.select_target_section(note, "wound_length") is None
        assert ni.select_target_section(note, "rom_angle") is None


# ── injection ──────────────────────────────────────────────────────────────────


class TestInject:
    def test_injects_confirmed_wound_into_section_and_marks_populated(self):
        note = _note("wound_assessment")
        changed = ni.inject_into_note(note, _m("wound_length", 42.0, "mm"))
        assert changed is True
        section = note.get_section("wound_assessment")
        assert section.status == "populated"
        assert len(section.claims) == 1
        claim = section.claims[0]
        assert claim.source_type == "measurement"
        assert claim.source_id == "meas_001"
        assert claim.id == "mclaim_meas_001"
        assert "42 mm" in claim.text

    def test_unconfirmed_measurement_is_not_injected(self):
        note = _note("wound_assessment")
        changed = ni.inject_into_note(note, _m("wound_length", 42.0, "mm", confirmed=False))
        assert changed is False
        assert note.get_section("wound_assessment").claims == []

    def test_idempotent_on_measurement_id(self):
        note = _note("wound_assessment")
        assert ni.inject_into_note(note, _m("wound_length", 42.0, "mm")) is True
        # Same measurement id again — no duplicate, returns False.
        assert ni.inject_into_note(note, _m("wound_length", 42.0, "mm")) is False
        assert len(note.get_section("wound_assessment").claims) == 1

    def test_no_section_is_noop(self):
        note = _note("chief_complaint", "hpi", "plan")
        assert ni.inject_into_note(note, _m("wound_length", 42.0, "mm")) is False
        assert all(s.claims == [] for s in note.sections)

    def test_rom_into_functional_assessment(self):
        note = _note("physical_exam", "functional_assessment", specialty="musculoskeletal")
        assert ni.inject_into_note(
            note, _m("rom_angle", 35, "deg", method="ar_goniometer")) is True
        fa = note.get_section("functional_assessment")
        assert len(fa.claims) == 1
        assert "35 degrees" in fa.claims[0].text
        assert note.get_section("physical_exam").claims == []

    def test_populated_section_keeps_status_and_appends(self):
        note = _note("wound_assessment")
        sec = note.get_section("wound_assessment")
        sec.status = "populated"
        sec.claims.append(NoteClaim(id="c1", text="prior", source_type="transcript",
                                    source_id="seg_001"))
        assert ni.inject_into_note(note, _m("wound_width", 18.0, "mm")) is True
        assert sec.status == "populated"
        assert len(sec.claims) == 2
