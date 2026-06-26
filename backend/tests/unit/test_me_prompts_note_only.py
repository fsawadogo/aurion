"""Unit tests for the clinician AI-Prompts note-only display flag (ps-fu5).

`_visible_prompts` narrows the catalog to the `note` category for CLINICIANs
when `feature_flags.clinician_prompts_note_only` is on; support roles always see
the full catalog.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.api.v1.me_prompts import _visible_prompts
from app.core.types import UserRole


def _config(note_only: bool) -> MagicMock:
    cfg = MagicMock()
    cfg.feature_flags.clinician_prompts_note_only = note_only
    return cfg


def test_clinician_sees_only_note_category_when_flag_on() -> None:
    with patch("app.api.v1.me_prompts.get_config", return_value=_config(True)):
        visible = _visible_prompts(UserRole.CLINICIAN)
    assert visible, "expected at least the note-generation prompt"
    assert {p.category for p in visible} == {"note"}


def test_clinician_sees_full_catalog_when_flag_off() -> None:
    with patch("app.api.v1.me_prompts.get_config", return_value=_config(False)):
        visible = _visible_prompts(UserRole.CLINICIAN)
    # The full catalog spans more than just the note category.
    assert {p.category for p in visible} > {"note"}


def test_support_roles_see_full_catalog_even_when_flag_on() -> None:
    with patch("app.api.v1.me_prompts.get_config", return_value=_config(True)):
        for role in (
            UserRole.ADMIN,
            UserRole.EVAL_TEAM,
            UserRole.COMPLIANCE_OFFICER,
        ):
            assert {p.category for p in _visible_prompts(role)} > {"note"}, role
