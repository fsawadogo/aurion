"""Unit tests for the PS-02 publication precedence selector.

Pure (no DB): exercises ``_select_published`` — SELF > ROLE > ALL — so the
precedence rule that decides which shared prompt a clinician receives is locked
independently of the SQL query that feeds it.
"""

from __future__ import annotations

import uuid

import pytest

from app.modules.prompts.assembly import _select_published

OWNER = uuid.uuid4()
OTHER = uuid.uuid4()


def test_self_beats_role_and_all() -> None:
    rows = [
        ("ALL", None, None, "all-text"),
        ("ROLE", None, "CLINICIAN", "role-text"),
        ("SELF", OWNER, None, "self-text"),
    ]
    assert _select_published(rows, OWNER, "CLINICIAN") == "self-text"


def test_role_beats_all_when_no_self() -> None:
    rows = [
        ("ALL", None, None, "all-text"),
        ("ROLE", None, "CLINICIAN", "role-text"),
    ]
    assert _select_published(rows, OWNER, "CLINICIAN") == "role-text"


def test_self_only_matches_the_owner() -> None:
    rows = [
        ("SELF", OTHER, None, "self-other"),
        ("ALL", None, None, "all-text"),
    ]
    assert _select_published(rows, OWNER, "CLINICIAN") == "all-text"


def test_role_only_matches_same_role() -> None:
    rows = [
        ("ROLE", None, "ADMIN", "role-admin"),
        ("ALL", None, None, "all-text"),
    ]
    assert _select_published(rows, OWNER, "CLINICIAN") == "all-text"


def test_all_fallback() -> None:
    assert _select_published([("ALL", None, None, "all-text")], OWNER, "CLINICIAN") == "all-text"


def test_none_when_no_applicable_publication() -> None:
    rows = [
        ("SELF", OTHER, None, "x"),
        ("ROLE", None, "ADMIN", "y"),
    ]
    assert _select_published(rows, OWNER, "CLINICIAN") is None


def test_empty_rows() -> None:
    assert _select_published([], OWNER, "CLINICIAN") is None


def test_role_skipped_when_role_value_none() -> None:
    """A missing user row (role_value None) can't match a ROLE publication —
    it must fall through to ALL, never crash."""
    rows = [
        ("ROLE", None, "CLINICIAN", "role-text"),
        ("ALL", None, None, "all-text"),
    ]
    assert _select_published(rows, OWNER, None) == "all-text"


@pytest.mark.asyncio
async def test_prompt_assembly_can_return_no_runtime_override(monkeypatch) -> None:
    """Vision may choose its grounded/descriptive default after DB lookup."""
    from app.modules.prompts import assembly

    async def _no_user(*_args, **_kwargs):
        return None

    async def _no_publication(*_args, **_kwargs):
        return None

    monkeypatch.setattr(assembly, "_get_user_prompt", _no_user)
    monkeypatch.setattr(assembly, "_get_published_prompt", _no_publication)

    resolved = await assembly.assemble_prompt(
        "vision_frame",
        OWNER,
        object(),
        include_registry_default=False,
    )

    assert resolved is None


@pytest.mark.asyncio
async def test_explicit_override_equal_to_registry_default_is_preserved(
    monkeypatch,
) -> None:
    """Override presence, not text equality, controls runtime precedence."""
    from app.modules.prompts import PROMPTS, assembly

    async def _no_user(*_args, **_kwargs):
        return None

    async def _published_default(*_args, **_kwargs):
        return PROMPTS["vision_frame"].system_prompt

    monkeypatch.setattr(assembly, "_get_user_prompt", _no_user)
    monkeypatch.setattr(assembly, "_get_published_prompt", _published_default)

    resolved = await assembly.assemble_prompt(
        "vision_frame",
        OWNER,
        object(),
        include_registry_default=False,
    )

    assert resolved == PROMPTS["vision_frame"].system_prompt
