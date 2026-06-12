"""#63 Phase A foundation — MeasurementCitation schema + NoteClaim/Template
extension + AppConfig MeasurementConfig + audit events.

Pins the load-bearing invariants from the design: kind↔unit consistency,
the structural "never certified" guarantee, the descriptive/SaMD posture,
backward-compatible config defaults (ships dark), and the PHI guard that
the measurement VALUE never appears in an audit kwarg whitelist.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType
from app.core.types import MeasurementCitation, NoteClaim, TemplateSection
from app.modules.config.schema import AppConfigSchema, MeasurementConfig

# ── MeasurementCitation ──────────────────────────────────────────────────────


def _wound() -> MeasurementCitation:
    return MeasurementCitation(
        measurement_id="meas_001", session_id="s1", frame_id="frame_00214",
        kind="wound_length", value=42.0, unit="mm", method="arkit_lidar",
        confidence="high", confidence_reason="stable tracking, planar",
        scale_source="lidar_depth", physician_confirmed=True,
    )


def test_valid_wound_citation() -> None:
    m = _wound()
    assert m.value == 42.0 and m.unit == "mm"
    assert m.certified_measurement is False
    assert m.provider_used == "on_device"


def test_kind_unit_consistency_enforced() -> None:
    # wound_length must be mm, not deg / cm2.
    with pytest.raises(ValidationError):
        MeasurementCitation(
            measurement_id="m", session_id="s", kind="wound_length",
            value=10, unit="deg", method="arkit_lidar", confidence="high",
        )
    # rom_angle must be deg.
    with pytest.raises(ValidationError):
        MeasurementCitation(
            measurement_id="m", session_id="s", kind="rom_angle",
            value=35, unit="mm", method="ar_goniometer", confidence="medium",
        )
    # wound_area must be cm2 — and the happy path works.
    ok = MeasurementCitation(
        measurement_id="m", session_id="s", kind="wound_area",
        value=3.2, unit="cm2", method="arkit_lidar", confidence="low",
    )
    assert ok.unit == "cm2"
    rom = MeasurementCitation(
        measurement_id="m", session_id="s", kind="rom_angle",
        value=35, unit="deg", method="ar_goniometer", confidence="medium",
    )
    assert rom.unit == "deg"


def test_certified_measurement_cannot_be_true() -> None:
    # Structural disclaimer: Literal[False] makes "certified" impossible.
    with pytest.raises(ValidationError):
        MeasurementCitation(
            measurement_id="m", session_id="s", kind="wound_length",
            value=10, unit="mm", method="arkit_lidar", confidence="high",
            certified_measurement=True,
        )


def test_negative_value_rejected() -> None:
    with pytest.raises(ValidationError):
        MeasurementCitation(
            measurement_id="m", session_id="s", kind="wound_length",
            value=-1, unit="mm", method="arkit_lidar", confidence="high",
        )


# ── NoteClaim / TemplateSection extension ────────────────────────────────────


def test_noteclaim_accepts_measurement_source_type() -> None:
    claim = NoteClaim(
        id="claim_042",
        text="Wound length measured at approximately 42 mm (iPhone AR, LiDAR, physician-confirmed).",
        source_type="measurement", source_id="meas_001",
    )
    assert claim.source_type == "measurement"


def test_template_section_measurement_flag_defaults_false() -> None:
    assert TemplateSection(id="hpi", title="HPI").measurement_output_expected is False
    assert TemplateSection(
        id="wound_assessment", title="Wound", measurement_output_expected=True
    ).measurement_output_expected is True


# ── AppConfig ────────────────────────────────────────────────────────────────


def test_measurement_ships_dark_and_phase_a_method_defaults() -> None:
    cfg = AppConfigSchema()
    assert cfg.feature_flags.measurement_enabled is False  # dark by default
    assert cfg.measurement.methods_allowed == ["arkit_lidar", "arkit_world", "ar_goniometer"]
    assert cfg.measurement.min_confidence == "medium"
    assert cfg.measurement.allow_non_lidar is True


def test_appconfig_backward_compatible_without_measurement_block() -> None:
    # Older hosted content has no `measurement` / `measurement_enabled` keys.
    doc = {"providers": {"transcription": "whisper", "note_generation": "anthropic", "vision": "openai"}}
    cfg = AppConfigSchema.model_validate(doc)
    assert isinstance(cfg.measurement, MeasurementConfig)
    assert cfg.feature_flags.measurement_enabled is False


def test_measurement_methods_reject_unknown() -> None:
    with pytest.raises(ValidationError):
        MeasurementConfig(methods_allowed=["telekinesis"])


# ── Audit PHI guard ──────────────────────────────────────────────────────────


def test_measurement_audit_events_registered_and_value_never_whitelisted() -> None:
    for evt in (
        AuditEventType.MEASUREMENT_GENERATED,
        AuditEventType.MEASUREMENT_REVIEWED,
        AuditEventType.MEASUREMENT_EDITED,
        AuditEventType.MEASUREMENT_SUPPRESSED,
    ):
        assert evt in ALLOWED_AUDIT_KWARGS
        # The numeric measurement value is derived PHI — it must NEVER be an
        # allowed audit kwarg.
        assert "value" not in ALLOWED_AUDIT_KWARGS[evt]
    assert "confidence" in ALLOWED_AUDIT_KWARGS[AuditEventType.MEASUREMENT_GENERATED]
    assert "reason" in ALLOWED_AUDIT_KWARGS[AuditEventType.MEASUREMENT_SUPPRESSED]
