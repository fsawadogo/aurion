"""Unit tests for the `_serialize` active-prompt cascade (ps-fu4).

`active_prompt` / `active_source` must follow the SAME order as live note
generation (`assemble_prompt`): personal override → active admin publication →
registry default. Pure projection — no DB.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.v1.me_prompts import _serialize
from app.modules.prompts import PROMPTS
from app.modules.prompts.assembly import PublishedPromptMeta

_PID = "note_generation"


def _meta(text: str) -> PublishedPromptMeta:
    return PublishedPromptMeta(
        name="Org note prompt",
        version_no=3,
        scope="ALL",
        target_role=None,
        published_at=datetime(2026, 6, 24, tzinfo=timezone.utc),
        text=text,
    )


def test_default_when_no_override_no_publication() -> None:
    out = _serialize(PROMPTS[_PID], None, None)
    assert out.active_source == "default"
    assert out.active_prompt == PROMPTS[_PID].system_prompt
    assert out.admin_publication is None
    assert out.is_overridden is False


def test_published_when_publication_and_no_override() -> None:
    out = _serialize(PROMPTS[_PID], None, _meta("PUBLISHED TEXT"))
    assert out.active_source == "published"
    assert out.active_prompt == "PUBLISHED TEXT"
    assert out.admin_publication is not None
    assert out.admin_publication.name == "Org note prompt"
    assert out.is_overridden is False


def test_override_wins_over_publication_but_publication_still_surfaced() -> None:
    out = _serialize(PROMPTS[_PID], "MY OVERRIDE", _meta("PUBLISHED TEXT"))
    assert out.active_source == "override"
    assert out.active_prompt == "MY OVERRIDE"
    # The publication is still returned so the UI can flag it as shadowed.
    assert out.admin_publication is not None
    assert out.is_overridden is True
