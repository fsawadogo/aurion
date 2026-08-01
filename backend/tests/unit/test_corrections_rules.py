"""Correction memory — the rules layer (distil, store, inject).

Locks: suggestions exclude medical corrections and need >=2 to generalise; the
rendered prefix is fenced below the descriptive boundary (never loosens
grounding); and the get/set round-trip through the prompt-override store.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import app.modules.corrections.rules as rules


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


def _corr(before: str, after: str, cls: str):
    return SimpleNamespace(before_text=before, after_text=after, classification=cls)


# ── render / grounding fence ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_render_prefix_is_fenced_below_grounding() -> None:
    db = MagicMock()
    with patch.object(rules, "get_correction_rules", AsyncMock(return_value="Use 'the patient'.")):
        prefix = await rules.render_correction_rules_prefix(uuid.uuid4(), db)
    assert prefix is not None
    assert "Use 'the patient'." in prefix
    # The fence must state that rules never change clinical content / grounding.
    low = prefix.lower()
    assert "style only" in low
    assert "never change clinical content" in low or "grounded" in low


@pytest.mark.asyncio
async def test_render_prefix_none_when_no_rules() -> None:
    db = MagicMock()
    with patch.object(rules, "get_correction_rules", AsyncMock(return_value="")):
        assert await rules.render_correction_rules_prefix(uuid.uuid4(), db) is None


@pytest.mark.asyncio
async def test_render_prefix_none_for_no_clinician() -> None:
    assert await rules.render_correction_rules_prefix(None, MagicMock()) is None


# ── suggestions ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_suggest_excludes_medical_and_needs_two() -> None:
    # The query filters classification in (typo, semantic); a lone correction
    # can't generalise, so <2 returns [] without calling the model.
    db = MagicMock()
    db.execute = AsyncMock(return_value=_Result([_corr("client", "patient", "semantic")]))
    provider = MagicMock()
    provider.generate_text = AsyncMock()
    registry = MagicMock()
    registry.get_note_provider_with_fallback = MagicMock(return_value=provider)
    with patch.object(rules, "get_registry", return_value=registry):
        out = await rules.suggest_rules(uuid.uuid4(), db)
    assert out == []
    provider.generate_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_suggest_parses_and_dedups_rule_lines() -> None:
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_Result([
            _corr("client", "patient", "semantic"),
            _corr("client", "patient", "semantic"),
            _corr("ROM", "range of motion", "semantic"),
        ])
    )
    provider = MagicMock()
    provider.generate_text = AsyncMock(
        return_value="1. Refer to the person as 'the patient'\n"
        "- Refer to the person as 'the patient'\n"  # dup (diff bullet)
        "* Spell out abbreviations on first use\n"
    )
    registry = MagicMock()
    registry.get_note_provider_with_fallback = MagicMock(return_value=provider)
    with patch.object(rules, "get_registry", return_value=registry):
        out = await rules.suggest_rules(uuid.uuid4(), db)
    assert out == [
        "Refer to the person as 'the patient'",
        "Spell out abbreviations on first use",
    ]


@pytest.mark.asyncio
async def test_suggest_survives_provider_error() -> None:
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=_Result([
            _corr("a", "b", "typo"), _corr("c", "d", "semantic"),
        ])
    )
    provider = MagicMock()
    provider.generate_text = AsyncMock(side_effect=RuntimeError("down"))
    registry = MagicMock()
    registry.get_note_provider_with_fallback = MagicMock(return_value=provider)
    with patch.object(rules, "get_registry", return_value=registry):
        out = await rules.suggest_rules(uuid.uuid4(), db)
    assert out == []


# ── store round-trip ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_set_then_get_round_trip_new_row() -> None:
    # No existing row → insert; the stored text is trimmed.
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None))
    db.add = MagicMock()
    db.flush = AsyncMock()
    await rules.set_correction_rules(uuid.uuid4(), "  Use 'the patient'.  ", db)
    row = db.add.call_args.args[0]
    assert row.user_prompt_text == "Use 'the patient'."
    assert row.prompt_id == rules.CORRECTION_RULES_PROMPT_ID


@pytest.mark.asyncio
async def test_set_updates_existing_row() -> None:
    existing = SimpleNamespace(user_prompt_text="old")
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(scalar_one_or_none=lambda: existing)
    )
    db.add = MagicMock()
    db.flush = AsyncMock()
    await rules.set_correction_rules(uuid.uuid4(), "new rules", db)
    assert existing.user_prompt_text == "new rules"
    db.add.assert_not_called()
