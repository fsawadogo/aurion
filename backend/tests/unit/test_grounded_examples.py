"""GS-2 (#544) — grounded few-shot examples, flag-gated (pilot specialties).

OFF (default) returns only the descriptive examples (byte-identical). ON appends
the grounded `{key}.grounded.examples.json` for the pilot specialties, whose
assessment claim is synthesized from multiple cited sources (additional_sources).
"""

from __future__ import annotations

import pytest

from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig
from app.modules.note_gen import few_shot
from app.modules.note_gen.few_shot import (
    _clear_cache,
    get_few_shot_examples,
    render_examples_block,
)

PILOT = ("orthopedic_surgery", "plastic_surgery")


def _cfg(on: bool) -> AppConfigSchema:
    return AppConfigSchema(feature_flags=FeatureFlagsConfig(grounded_synthesis_enabled=on))


@pytest.fixture(autouse=True)
def _reset():
    _clear_cache()
    yield
    _clear_cache()


def _is_grounded(example: dict) -> bool:
    return "grounded synthesis mode" in example.get("description", "").lower()


def test_off_excludes_grounded(monkeypatch):
    monkeypatch.setattr(few_shot, "get_config", lambda: _cfg(False))
    for k in PILOT:
        examples = get_few_shot_examples(k)
        assert not any(_is_grounded(e) for e in examples)


def test_on_appends_grounded_for_pilot(monkeypatch):
    monkeypatch.setattr(few_shot, "get_config", lambda: _cfg(True))
    for k in PILOT:
        examples = get_few_shot_examples(k)
        grounded = [e for e in examples if _is_grounded(e)]
        assert len(grounded) >= 1
        # the synthesized assessment claim cites >1 source (additional_sources)
        claims = [
            c
            for e in grounded
            for s in e["note"]["sections"]
            for c in s["claims"]
        ]
        assert any(c.get("additional_sources") for c in claims)


def test_grounded_example_claims_are_anchored(monkeypatch):
    # AC-3: grounding integrity — every claim (primary + every additional) has a
    # non-empty source_id.
    monkeypatch.setattr(few_shot, "get_config", lambda: _cfg(True))
    for k in PILOT:
        for e in get_few_shot_examples(k):
            if not _is_grounded(e):
                continue
            for s in e["note"]["sections"]:
                for c in s["claims"]:
                    assert c["source_id"]
                    for extra in c.get("additional_sources", []):
                        assert extra["source_id"]


def test_grounded_examples_render(monkeypatch):
    monkeypatch.setattr(few_shot, "get_config", lambda: _cfg(True))
    block = render_examples_block(get_few_shot_examples("orthopedic_surgery"))
    assert "WORKED EXAMPLES" in block and "Grounded Synthesis Mode" in block
