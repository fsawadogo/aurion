"""scribe-1 (#621) — Grounded Synthesis is a MODE, not a fallback default.

With ``grounded_synthesis_enabled`` ON, note generation's grounded system
prompt is ALWAYS present and any override (personal / template / published) is
layered ADDITIVELY on top — no override can strip the grounding contract. Every
other case keeps byte-identical REPLACEMENT semantics.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1 import me_prompts
from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig
from app.modules.prompts import assembly
from app.modules.prompts.assembly import PublishedPromptMeta, compose_system_prompt
from app.modules.prompts.registry import PROMPTS
from app.modules.providers.note_gen.shared import (
    NOTE_GEN_GROUNDED_SYSTEM_PROMPT,
    NOTE_GEN_SYSTEM_PROMPT,
)

_JOB = "note_generation"


def _cfg(on: bool) -> AppConfigSchema:
    return AppConfigSchema(
        feature_flags=FeatureFlagsConfig(grounded_synthesis_enabled=on)
    )


@pytest.fixture
def grounded_on(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(True))


@pytest.fixture
def grounded_off(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(False))


# ── Grounded ON: boundary always present, override appended (additive) ───────


def test_grounded_template_override_is_appended_not_substituted(grounded_on):
    # AC-1: a DESCRIPTIVE template system_prompt no longer replaces the grounded
    # boundary — the boundary stays and the template text rides on top.
    descriptive = "Describe only. Do not interpret, diagnose, or infer."
    out = compose_system_prompt(_JOB, None, descriptive, None)
    assert out.startswith(NOTE_GEN_GROUNDED_SYSTEM_PROMPT)
    assert descriptive in out
    assert out != descriptive


def test_grounded_publication_is_appended(grounded_on):
    # AC-2: an admin publication (no personal/template) is additive too.
    out = compose_system_prompt(_JOB, None, None, "PUBLISHED_TEXT")
    assert out.startswith(NOTE_GEN_GROUNDED_SYSTEM_PROMPT)
    assert "PUBLISHED_TEXT" in out


def test_grounded_personal_override_wins_the_appended_layer(grounded_on):
    out = compose_system_prompt(_JOB, "PERSONAL", "TEMPLATE", "PUBLISHED")
    assert out.startswith(NOTE_GEN_GROUNDED_SYSTEM_PROMPT)
    assert "PERSONAL" in out
    assert "TEMPLATE" not in out and "PUBLISHED" not in out


def test_grounded_no_override_is_boundary_only(grounded_on):
    assert compose_system_prompt(_JOB, None, None, None) == NOTE_GEN_GROUNDED_SYSTEM_PROMPT


def test_grounded_flag_does_not_affect_non_note_gen(grounded_on):
    # AC-6: grounded mode only changes note_generation composition. Pick any
    # real registry prompt that isn't note_generation (no stale hard-coded id).
    pid = next(p for p in PROMPTS if p != "note_generation")
    assert compose_system_prompt(pid, None, "TEMPLATE_X", None) == "TEMPLATE_X"


# ── Grounded OFF: byte-identical replacement semantics (AC-5 regression) ─────


def test_off_personal_override_replaces(grounded_off):
    assert (
        compose_system_prompt(_JOB, "PERSONAL", "TEMPLATE", "PUBLISHED") == "PERSONAL"
    )


def test_off_template_replaces_when_no_personal(grounded_off):
    assert compose_system_prompt(_JOB, None, "TEMPLATE", "PUBLISHED") == "TEMPLATE"


def test_off_published_replaces_when_no_personal_or_template(grounded_off):
    assert compose_system_prompt(_JOB, None, None, "PUBLISHED") == "PUBLISHED"


def test_off_default_is_descriptive_base(grounded_off):
    assert compose_system_prompt(_JOB, None, None, None) == NOTE_GEN_SYSTEM_PROMPT


# ── Missing / bad session path is grounded-aware (AC-3) ──────────────────────


async def test_missing_session_uses_grounded_base(grounded_on):
    # A bad-uuid session id short-circuits before any DB call and must resolve
    # the GROUNDED base (was the raw descriptive default pre-scribe-1).
    out = await assembly.assemble_prompt_for_session(_JOB, "not-a-uuid", db=None)
    assert out == NOTE_GEN_GROUNDED_SYSTEM_PROMPT


async def test_missing_session_appends_template_grounded(grounded_on):
    out = await assembly.assemble_prompt_for_session(
        _JOB, "not-a-uuid", db=None, template_prompt="TEMPLATE_Y"
    )
    assert out.startswith(NOTE_GEN_GROUNDED_SYSTEM_PROMPT)
    assert "TEMPLATE_Y" in out


# ── Transparency serializer reports the grounded base (AC-4) ─────────────────


def test_serialize_default_reports_grounded_base(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(True))
    resp = me_prompts._serialize(PROMPTS[_JOB], user_prompt_text=None, publication=None)
    assert resp.active_prompt == NOTE_GEN_GROUNDED_SYSTEM_PROMPT
    assert resp.system_prompt == NOTE_GEN_GROUNDED_SYSTEM_PROMPT
    assert resp.active_source == "default"


def test_serialize_default_off_reports_descriptive(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(False))
    resp = me_prompts._serialize(PROMPTS[_JOB], user_prompt_text=None, publication=None)
    assert resp.active_prompt == NOTE_GEN_SYSTEM_PROMPT
    assert resp.system_prompt == NOTE_GEN_SYSTEM_PROMPT


# ── Review fixes (#627): _serialize override/published branches are grounded ──


def _pub(text: str) -> PublishedPromptMeta:
    return PublishedPromptMeta(
        name="Org prompt",
        version_no=1,
        scope="ALL",
        target_role=None,
        published_at=datetime(2026, 1, 1),
        text=text,
    )


def test_serialize_override_appends_grounded(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(True))
    resp = me_prompts._serialize(
        PROMPTS[_JOB], user_prompt_text="USE BULLETS", publication=None
    )
    assert resp.active_prompt.startswith(NOTE_GEN_GROUNDED_SYSTEM_PROMPT)
    assert "USE BULLETS" in resp.active_prompt
    assert resp.active_source == "override"


def test_serialize_override_off_is_verbatim(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(False))
    resp = me_prompts._serialize(
        PROMPTS[_JOB], user_prompt_text="USE BULLETS", publication=None
    )
    assert resp.active_prompt == "USE BULLETS"
    assert resp.active_source == "override"


def test_serialize_published_appends_grounded(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(True))
    resp = me_prompts._serialize(
        PROMPTS[_JOB], user_prompt_text=None, publication=_pub("PUBTEXT")
    )
    assert resp.active_prompt.startswith(NOTE_GEN_GROUNDED_SYSTEM_PROMPT)
    assert "PUBTEXT" in resp.active_prompt
    assert resp.active_source == "published"


def test_serialize_published_off_is_verbatim(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(False))
    resp = me_prompts._serialize(
        PROMPTS[_JOB], user_prompt_text=None, publication=_pub("PUBTEXT")
    )
    assert resp.active_prompt == "PUBTEXT"
    assert resp.active_source == "published"


# ── Review fixes (#627): real DB-backed assemble_prompt additive cascade ─────


async def test_assemble_prompt_grounded_appends_personal_override(grounded_on):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "USE BULLETS"
    db.execute.return_value = result
    out = await assembly.assemble_prompt(_JOB, uuid.uuid4(), db)
    assert out.startswith(NOTE_GEN_GROUNDED_SYSTEM_PROMPT)
    assert "USE BULLETS" in out


async def test_assemble_prompt_off_returns_personal_override_verbatim(grounded_off):
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = "USE BULLETS"
    db.execute.return_value = result
    out = await assembly.assemble_prompt(_JOB, uuid.uuid4(), db)
    assert out == "USE BULLETS"


# ── Review fixes (#627): empty published handled identically in both modes ───


def test_empty_published_consistent_between_modes(monkeypatch):
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(False))
    assert compose_system_prompt(_JOB, None, None, "") == ""
    monkeypatch.setattr(assembly, "get_config", lambda: _cfg(True))
    assert compose_system_prompt(_JOB, None, None, "") == (
        NOTE_GEN_GROUNDED_SYSTEM_PROMPT + assembly._ADDITIVE_STYLE_HEADER
    )
