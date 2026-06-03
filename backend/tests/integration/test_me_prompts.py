"""Integration tests for ``GET /api/v1/me/prompts`` (AI-PROMPTS-A).

Covers the acceptance criteria from
``docs/plans/ai-prompts-phase-a.md``:

  * AC-1: CLINICIAN reads the catalog and receives 8 prompts.
  * AC-2: ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER also receive 8.
  * AC-3: every entry has non-empty system_prompt + purpose +
    runs_when.
  * AC-4: descriptive-mode safety phrases preserved verbatim. **This
    is the safety regression test** — if a future change strips
    "describe", "do not interpret", or "do not diagnose" from the
    AI-facing prompts, this test fails and the build breaks.
  * AC-5: no PHI patterns in the response.

Plus negative gates:
  * Unsupported roles (none today, but the dependency is single-purpose).
  * Phase B overlay fields present with their static defaults
    (``override_text=None``, ``is_overridden=False``).
"""

from __future__ import annotations

import os
import re
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock

# Env vars before app import — APP_ENV=local enables the dev-token
# ``<role>:<user_id>`` bearer parser. See clips_endpoint suite for the
# pattern.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.modules.prompts import PROMPTS  # noqa: E402

EXPECTED_PROMPT_COUNT = 8


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """In-process ASGI client. Phase B adds a DB read to the GET path
    for the per-physician overlay lookup — we still don't want a real
    DB for these metadata-only assertions, so we stub the session so
    ``db.execute(...)`` returns an empty result. That keeps Phase A's
    "no overlays" expectation true."""
    from app.core.database import get_db
    from app.main import app

    async def _yield_mock_db() -> AsyncGenerator[MagicMock, None]:
        db = MagicMock()
        # ``db.execute`` is awaited — return an AsyncMock whose result
        # serves an empty scalars().all() list. That keeps the GET
        # endpoint's overlay-lookup path happy with zero overlays.
        empty_result = MagicMock()
        empty_result.scalars.return_value.all.return_value = []
        empty_result.scalar_one_or_none.return_value = None
        db.execute = AsyncMock(return_value=empty_result)
        yield db

    app.dependency_overrides[get_db] = _yield_mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://aurion.test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _headers(role: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {role}:{uuid.uuid4()}"}


# ── AC-1: CLINICIAN gets 8 prompts ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_clinician_sees_eight_prompts(app_client: AsyncClient) -> None:
    response = await app_client.get(
        "/api/v1/me/prompts", headers=_headers("CLINICIAN")
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert isinstance(payload, list)
    assert len(payload) == EXPECTED_PROMPT_COUNT


# ── AC-2: ADMIN / EVAL_TEAM / COMPLIANCE_OFFICER also see 8 ─────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "role",
    ["ADMIN", "EVAL_TEAM", "COMPLIANCE_OFFICER"],
)
async def test_other_authorised_roles_also_read(
    app_client: AsyncClient, role: str
) -> None:
    response = await app_client.get(
        "/api/v1/me/prompts", headers=_headers(role)
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert len(payload) == EXPECTED_PROMPT_COUNT


@pytest.mark.asyncio
async def test_unauthenticated_request_blocked(app_client: AsyncClient) -> None:
    response = await app_client.get("/api/v1/me/prompts")
    # ``get_current_user`` raises 401/403 depending on path — accept
    # either as long as it isn't 200.
    assert response.status_code in (401, 403)


# ── AC-3: every entry has the required metadata fields ─────────────────────


@pytest.mark.asyncio
async def test_every_prompt_has_required_fields(
    app_client: AsyncClient,
) -> None:
    response = await app_client.get(
        "/api/v1/me/prompts", headers=_headers("CLINICIAN")
    )
    payload = response.json()
    for prompt in payload:
        assert prompt["id"], "prompt id must be non-empty"
        assert prompt["name"], f"{prompt['id']} missing display name"
        assert prompt["purpose"], f"{prompt['id']} missing purpose"
        assert prompt["runs_when"], f"{prompt['id']} missing runs_when"
        assert prompt["system_prompt"], (
            f"{prompt['id']} missing system_prompt — this is the AI-facing "
            f"text and must never be empty"
        )
        assert prompt["category"] in {
            "note",
            "vision",
            "extraction",
            "preview",
        }, f"{prompt['id']} has invalid category {prompt['category']}"
        # Phase B overlay fields. For a fresh CLINICIAN with no saved
        # overlays the response is base-only — overlay_text is None,
        # is_overridden is False, assembled_preview == system_prompt.
        assert prompt["overlay_text"] is None
        assert prompt["is_overridden"] is False
        assert prompt["assembled_preview"] == prompt["system_prompt"]


@pytest.mark.asyncio
async def test_response_schema_keys_stable(app_client: AsyncClient) -> None:
    """Lock the exact key set the portal page deserializes. If a field
    is added or renamed without a UI update this test fails fast."""
    response = await app_client.get(
        "/api/v1/me/prompts", headers=_headers("CLINICIAN")
    )
    payload = response.json()
    expected_keys = {
        "id",
        "name",
        "purpose",
        "category",
        "runs_when",
        "provider_field",
        "system_prompt",
        "schema_note",
        "overlay_text",
        "is_overridden",
        "assembled_preview",
    }
    for prompt in payload:
        assert set(prompt.keys()) == expected_keys, prompt["id"]


# ── AC-4: descriptive-mode safety regression ───────────────────────────────


# Phrases that MUST appear (case-insensitive) in the AI-facing system
# prompts that drive note generation + vision frame + vision clip
# captioning. These come directly from CLAUDE.md ("Single Most
# Important Constraint" + "Vision" section) — they ARE the
# descriptive-mode boundary. Losing any of them would let the LLM
# drift into interpretive output.
#
# We check the literal substrings that the original prompts use today;
# if a future edit rephrases them, the test fails and the safety
# review must update the assertions deliberately (not silently).
_DESCRIPTIVE_PHRASES_NOTE_GEN = (
    "Describe only what was directly captured",
    "Do not infer, interpret, diagnose",
    "Report what happened. Do not conclude what it means",
)
_DESCRIPTIVE_PHRASES_VISION = (
    "Describe only what is literally visible",
    "Do not diagnose, interpret, or infer clinical meaning",
)
_DESCRIPTIVE_PHRASES_RECONCILE = (
    "Compare LITERALLY",
    "Do not infer clinical meaning",
)


@pytest.mark.asyncio
async def test_descriptive_mode_phrases_locked(
    app_client: AsyncClient,
) -> None:
    """Safety gate. If any of these literal phrases disappear, the
    descriptive-mode boundary has been weakened — fix the prompt or
    update the assertion with explicit security review."""
    response = await app_client.get(
        "/api/v1/me/prompts", headers=_headers("CLINICIAN")
    )
    payload = {p["id"]: p for p in response.json()}

    note_gen_text = payload["note_generation"]["system_prompt"]
    for phrase in _DESCRIPTIVE_PHRASES_NOTE_GEN:
        assert phrase in note_gen_text, (
            f"note_generation prompt lost descriptive-mode phrase "
            f"{phrase!r} — safety boundary regression"
        )

    for vision_id in ("vision_frame", "vision_clip"):
        text = payload[vision_id]["system_prompt"]
        for phrase in _DESCRIPTIVE_PHRASES_VISION:
            assert phrase in text, (
                f"{vision_id} prompt lost descriptive-mode phrase "
                f"{phrase!r} — safety boundary regression"
            )

    reconcile_text = payload["conflict_reconciliation"]["system_prompt"]
    for phrase in _DESCRIPTIVE_PHRASES_RECONCILE:
        assert phrase in reconcile_text, (
            f"conflict_reconciliation prompt lost {phrase!r} — "
            f"safety boundary regression"
        )


# ── AC-5: no PHI / patient identifiers in the registry text ────────────────


# Conservative PHI patterns. The prompts are templates and must not
# carry sample identifiers (SSN-shaped numbers, dates of birth,
# RAMQ-style health card numbers, plausible names attached to
# "patient" / "dr"). If a future prompt edit pastes a real-looking
# sample, this catches it before the response reaches the portal.
_PHI_REGEXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # US SSN
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO date (proxy for DOB)
    re.compile(r"\b[A-Z]{4}\d{8}\b"),  # RAMQ Quebec health card
    re.compile(r"\bMRN[-\s]?\d{4,}\b", re.IGNORECASE),
)


@pytest.mark.asyncio
async def test_no_phi_in_prompts(app_client: AsyncClient) -> None:
    response = await app_client.get(
        "/api/v1/me/prompts", headers=_headers("CLINICIAN")
    )
    for prompt in response.json():
        text = (
            prompt["system_prompt"]
            + " "
            + prompt["purpose"]
            + " "
            + prompt["runs_when"]
            + " "
            + (prompt["schema_note"] or "")
        )
        for pattern in _PHI_REGEXES:
            assert not pattern.search(text), (
                f"prompt {prompt['id']} contains a PHI-looking "
                f"pattern matching {pattern.pattern}"
            )


# ── Registry shape sanity (catches drift before it hits the wire) ──────────


def test_registry_count_matches_expected() -> None:
    """If the registry grows past 8 the plan documented the new entry
    + AC-1 / AC-2 need updating. Failing loudly here is the cheap
    forcing function."""
    assert len(PROMPTS) == EXPECTED_PROMPT_COUNT


def test_registry_keys_match_ids() -> None:
    """Dict key and entry id must agree — otherwise the URL fragment
    on the portal page won't match the entry the client looks up."""
    for key, entry in PROMPTS.items():
        assert key == entry.id, f"registry dict key {key} != entry id {entry.id}"
