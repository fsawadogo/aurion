"""Unit tests for portal UI prefs persistence (Phase A1).

Locks:
  * UpdateProfileRequest accepts ui_theme + ui_language
  * Both fields validate against their enums (ui_theme: system/light/
    dark; ui_language: en/fr)
  * ProfileResponse round-trips both fields with their defaults
  * The model column attributes exist and accept the expected values
"""

from __future__ import annotations

import uuid

import pytest

from app.api.v1.profile import ProfileResponse, UpdateProfileRequest
from app.core.models import PhysicianProfileModel

# ── UpdateProfileRequest validation ─────────────────────────────────────


def test_ui_theme_accepts_valid_values():
    """All three theme values pass validation."""
    for theme in ("system", "light", "dark"):
        req = UpdateProfileRequest(ui_theme=theme)
        assert req.ui_theme == theme


def test_ui_theme_rejects_invalid_value():
    """Bogus theme triggers ValidationError."""
    with pytest.raises(Exception):  # pydantic ValidationError
        UpdateProfileRequest(ui_theme="midnight")


def test_ui_theme_rejects_capitalization():
    """Case-sensitive — physicians can't sneak in 'System'."""
    with pytest.raises(Exception):
        UpdateProfileRequest(ui_theme="System")


def test_ui_theme_none_passes_through():
    """Optional field; None is the unset sentinel."""
    req = UpdateProfileRequest(ui_theme=None)
    assert req.ui_theme is None


def test_ui_language_accepts_en_fr():
    """Locked to EN/FR for the pilot — same set as iOS."""
    for lang in ("en", "fr"):
        req = UpdateProfileRequest(ui_language=lang)
        assert req.ui_language == lang


def test_ui_language_rejects_unsupported_locale():
    """Reject anything outside the current pilot set."""
    with pytest.raises(Exception):
        UpdateProfileRequest(ui_language="es")


def test_ui_language_rejects_ietf_subtag_today():
    """`fr-CA` is forward-compat at the column level (16-char cap) but
    the validator doesn't accept it yet. When we widen the validator,
    drop this test."""
    with pytest.raises(Exception):
        UpdateProfileRequest(ui_language="fr-CA")


def test_update_request_with_multiple_ui_fields():
    """Both fields can be set in one request — typical user-settings
    sheet pattern."""
    req = UpdateProfileRequest(ui_theme="dark", ui_language="fr")
    assert req.ui_theme == "dark"
    assert req.ui_language == "fr"


# ── ProfileResponse defaults ─────────────────────────────────────────────


def test_response_defaults_when_omitted():
    """Older code paths that don't populate the new fields get the
    same defaults the column server_default uses."""
    resp = ProfileResponse(
        clinician_id=str(uuid.uuid4()),
        display_name="Dr. Test",
        primary_specialty="general",
        preferred_templates=[],
        consultation_types=[],
        output_language="en",
    )
    assert resp.ui_theme == "system"
    assert resp.ui_language == "en"


def test_response_roundtrip_with_dark_french():
    resp = ProfileResponse(
        clinician_id=str(uuid.uuid4()),
        display_name="Dr. Test",
        primary_specialty="general",
        preferred_templates=[],
        consultation_types=[],
        output_language="en",
        ui_theme="dark",
        ui_language="fr",
    )
    assert resp.ui_theme == "dark"
    assert resp.ui_language == "fr"


# ── Model attribute presence ─────────────────────────────────────────────


def test_model_columns_present():
    """Sanity — the ORM attributes exist. A future refactor that
    drops them surfaces here before the migration is inconsistent."""
    profile = PhysicianProfileModel(
        id=uuid.uuid4(),
        clinician_id=uuid.uuid4(),
        display_name="Dr. Test",
        primary_specialty="general",
        preferred_templates="[]",
        consultation_types="[]",
        allied_health_team="[]",
        output_language="en",
        ui_theme="dark",
        ui_language="fr",
    )
    assert profile.ui_theme == "dark"
    assert profile.ui_language == "fr"


def test_model_columns_default_when_unset():
    """Construct without specifying — defaults apply at SQL flush time
    via the server_default; in-memory construction leaves them None
    if not set. The model declaration uses default= for ORM-side
    population on `db.add()` followed by `db.flush()` — verify in
    integration land, not here."""
    profile = PhysicianProfileModel(
        id=uuid.uuid4(),
        clinician_id=uuid.uuid4(),
        display_name="Dr. Test",
        primary_specialty="general",
        preferred_templates="[]",
        consultation_types="[]",
        allied_health_team="[]",
        output_language="en",
    )
    # Either default is applied immediately (some SQLAlchemy versions
    # do this) or None until flush. Both are acceptable here.
    assert profile.ui_theme in (None, "system")
    assert profile.ui_language in (None, "en")
