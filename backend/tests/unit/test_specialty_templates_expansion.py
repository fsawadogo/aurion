"""Smoke tests for the post-MVP specialty templates (issue #70).

Verifies that the three new JSON templates parse against the Pydantic
``Template`` schema, expose the expected keys, and are picked up by the
auto-loader.
"""

from __future__ import annotations

import pytest

from app.modules.note_gen.service import (
    _clear_template_cache,
    load_templates,
)

EXPECTED_NEW_KEYS = ("family_medicine", "internal_medicine", "pediatrics")


@pytest.fixture(autouse=True)
def _reset_template_cache():
    _clear_template_cache()
    yield
    _clear_template_cache()


class TestExpansion:
    def test_new_templates_are_loaded(self) -> None:
        loaded = load_templates()
        for key in EXPECTED_NEW_KEYS:
            assert key in loaded, f"missing template '{key}' from load_templates()"

    def test_each_has_required_sections(self) -> None:
        loaded = load_templates()
        for key in EXPECTED_NEW_KEYS:
            t = loaded[key]
            ids = {s.id for s in t.sections}
            # Every clinical template must at least have a complaint,
            # an HPI, an assessment, and a plan — the canonical SOAP spine.
            for required_id in ("chief_complaint", "hpi", "assessment", "plan"):
                assert required_id in ids, (
                    f"{key} missing required section '{required_id}'"
                )

    def test_visual_trigger_keywords_are_strings(self) -> None:
        loaded = load_templates()
        for key in EXPECTED_NEW_KEYS:
            for section in loaded[key].sections:
                assert all(
                    isinstance(kw, str) for kw in section.visual_trigger_keywords
                ), f"{key}.{section.id} has non-string keywords"

    def test_display_name_present(self) -> None:
        loaded = load_templates()
        for key in EXPECTED_NEW_KEYS:
            assert loaded[key].display_name
            assert isinstance(loaded[key].display_name, str)
