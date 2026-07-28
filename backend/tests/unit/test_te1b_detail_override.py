"""TE-1b — the per-session detail_level override (the missing control surface).

TE-1 made the capture directive gradable with resolution session-override →
template → default, but nothing could SET the session half. These tests pin
the new surface: the regenerate request validates the level, the session
write-back follows the encounter_context contract (omitted → unchanged), and
an override applied onto a template copy grades the directive without
mutating the shared template object.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.api.v1.sessions import RegenerateNoteRequest
from app.core.types import Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.providers.note_gen import shared
from app.modules.providers.note_gen.shared import (
    _DIRECTIVE_BRIEF,
    _DIRECTIVE_DETAILED,
    build_user_prompt,
)


def _transcript() -> Transcript:
    return Transcript(
        session_id=str(uuid.uuid4()),
        provider_used="whisper",
        segments=[TranscriptSegment(id="seg_0", start_ms=0, end_ms=10, text="hi")],
    )


def _template(detail_level=None) -> Template:
    return Template(
        key="general",
        display_name="General",
        sections=[TemplateSection(id="hpi", title="HPI")],
        detail_level=detail_level,
    )


def _flags_on():
    return SimpleNamespace(
        feature_flags=SimpleNamespace(template_engine_enabled=True)
    )


# ── Request validation ─────────────────────────────────────────────────────


@pytest.mark.parametrize("level", ["brief", "standard", "detailed"])
def test_request_accepts_valid_levels(level: str) -> None:
    req = RegenerateNoteRequest(detail_level=level)
    assert req.detail_level == level


def test_request_rejects_unknown_level() -> None:
    with pytest.raises(ValidationError):
        RegenerateNoteRequest(detail_level="exhaustive")


def test_request_detail_level_defaults_to_omitted() -> None:
    # Omitted → None → the endpoint leaves the stored session value untouched
    # (the same contract encounter_context uses).
    assert RegenerateNoteRequest().detail_level is None


# ── Override semantics ─────────────────────────────────────────────────────


def test_session_override_copy_beats_template_level() -> None:
    """The service applies the session override via model_copy — the copy
    grades the directive while the original template object is unchanged."""
    template = _template(detail_level="detailed")
    overridden = template.model_copy(update={"detail_level": "brief"})

    with patch.object(shared, "get_config", return_value=_flags_on()):
        prompt = build_user_prompt(_transcript(), overridden, stage=1)

    assert _DIRECTIVE_BRIEF in prompt
    assert _DIRECTIVE_DETAILED not in prompt
    # The shared/cached template object must never be mutated by an override.
    assert template.detail_level == "detailed"


def test_no_override_uses_template_level() -> None:
    template = _template(detail_level="brief")
    with patch.object(shared, "get_config", return_value=_flags_on()):
        prompt = build_user_prompt(_transcript(), template, stage=1)
    assert _DIRECTIVE_BRIEF in prompt
