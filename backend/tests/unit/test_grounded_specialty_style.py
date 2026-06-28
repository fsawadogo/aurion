"""GS-3 (#545) — specialty style guidance under Grounded Synthesis Mode.

OFF (default) returns the descriptive snippets byte-identical. ON returns
grounded variants (synthesis allowed, grounding required) for the 5 MVP
specialties; post-MVP specialties are unchanged.
"""

from __future__ import annotations

from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig
from app.modules.note_gen import specialty_style
from app.modules.note_gen.specialty_style import _GROUNDED_STYLE, _STYLE, get_specialty_style


def _cfg(on: bool) -> AppConfigSchema:
    return AppConfigSchema(feature_flags=FeatureFlagsConfig(grounded_synthesis_enabled=on))


MVP = ("orthopedic_surgery", "plastic_surgery", "musculoskeletal", "emergency_medicine", "general")


def test_off_is_descriptive_byte_identical(monkeypatch):
    monkeypatch.setattr(specialty_style, "get_config", lambda: _cfg(False))
    for k in _STYLE:
        assert get_specialty_style(k) == _STYLE[k]


def test_on_mvp_returns_grounded(monkeypatch):
    monkeypatch.setattr(specialty_style, "get_config", lambda: _cfg(True))
    for k in MVP:
        s = get_specialty_style(k).lower()
        assert s == _GROUNDED_STYLE[k].lower()
        assert "synthesize" in s and "cite" in s          # synthesis + grounding
        assert "support" in s                              # forbids unsupported
        assert "never interpret findings" not in s         # descriptive clause gone
        assert "never add interpretation" not in s


def test_on_postmvp_unchanged(monkeypatch):
    # pediatrics has no grounded variant → falls through to descriptive.
    monkeypatch.setattr(specialty_style, "get_config", lambda: _cfg(True))
    assert get_specialty_style("pediatrics") == _STYLE["pediatrics"]


def test_unknown_key_empty(monkeypatch):
    monkeypatch.setattr(specialty_style, "get_config", lambda: _cfg(True))
    assert get_specialty_style("nonexistent") == ""
