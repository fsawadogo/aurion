"""Pre-generation template override (TE-4e parity, extended PATCH shape).

The old ``{specialty}`` shape survives byte-compatible; the new explicit
``template_key`` / ``custom_template_id`` shapes replace the session's
context-mapped pin so the clinician's pick is provably what Stage 1 uses.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.api.v1.sessions import SessionResponse, UpdateTemplateRequest

# ── Request shape ──────────────────────────────────────────────────────────


def test_legacy_specialty_shape_still_valid() -> None:
    req = UpdateTemplateRequest(specialty="orthopedic_surgery")
    assert req.specialty == "orthopedic_surgery"
    assert req.template_key is None and req.custom_template_id is None


def test_builtin_override_shape() -> None:
    req = UpdateTemplateRequest(template_key="plastic_surgery")
    assert req.template_key == "plastic_surgery"


def test_custom_override_shape() -> None:
    tid = uuid.uuid4()
    req = UpdateTemplateRequest(custom_template_id=tid)
    assert req.custom_template_id == tid


@pytest.mark.parametrize(
    "payload",
    [
        {},  # nothing set
        {"specialty": "general", "template_key": "general"},
        {"template_key": "general", "custom_template_id": str(uuid.uuid4())},
        {
            "specialty": "general",
            "template_key": "general",
            "custom_template_id": str(uuid.uuid4()),
        },
    ],
)
def test_exactly_one_field_enforced(payload: dict) -> None:
    with pytest.raises(ValidationError):
        UpdateTemplateRequest(**payload)


# ── Response carries the pin ───────────────────────────────────────────────


def test_session_response_defaults_pin_fields_to_none() -> None:
    resp = SessionResponse(
        id=uuid.uuid4(),
        clinician_id=uuid.uuid4(),
        specialty="general",
        state="idle",
        created_at="",
        updated_at="",
    )
    assert resp.template_key is None
    assert resp.custom_template_id is None


def test_session_response_serializes_pin_fields() -> None:
    tid = uuid.uuid4()
    resp = SessionResponse(
        id=uuid.uuid4(),
        clinician_id=uuid.uuid4(),
        specialty="general",
        state="idle",
        template_key=None,
        custom_template_id=tid,
        created_at="",
        updated_at="",
    )
    dumped = resp.model_dump()
    assert dumped["custom_template_id"] == tid
    assert dumped["template_key"] is None
