"""Unit tests for the per-user prompt-testing gate + regenerate-note (#590).

Covers ``require_prompt_testing`` (the admin-assignable, role-agnostic capability
dependency — 403 unless the caller's ``prompt_testing_enabled`` row flag is set)
and the owner-scoped ``POST /sessions/{id}/regenerate-note`` handler it guards:
the missing-transcript 404, the own-scoped custom-template override (SECURITY),
and the happy path — reuse the STORED transcript (no re-transcribe) + honour a
template override + return the new note version. Plus the admin response mapping
carries the new flag.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.admin._shared import user_to_response
from app.api.v1.sessions import (
    RegenerateNoteRequest,
    RegenerateNoteResponse,
    regenerate_note,
)
from app.core.types import Note, Transcript, UserRole
from app.modules.auth.service import require_prompt_testing

# ── Helpers ─────────────────────────────────────────────────────────────────


def _session(session_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(id=session_id, specialty="orthopedic_surgery")


def _caller() -> SimpleNamespace:
    return SimpleNamespace(user_id=uuid.uuid4(), role=None, email="x@x.com")


def _transcript(session_id: uuid.UUID) -> Transcript:
    return Transcript(
        session_id=str(session_id), provider_used="whisper", segments=[]
    )


def _db_flag(enabled: bool | None) -> AsyncMock:
    """A db whose single scalar SELECT returns the flag — drives the gate."""
    db = AsyncMock()
    result = MagicMock()
    result.scalar_one_or_none.return_value = enabled
    db.execute = AsyncMock(return_value=result)
    return db


def _db() -> AsyncMock:
    """A db for handler tests: the transcript load + own-scope check are patched,
    so the handler only awaits ``commit()``."""
    db = AsyncMock()
    db.commit = AsyncMock()
    return db


# ── The gate: require_prompt_testing ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_gate_denies_when_flag_off():
    with pytest.raises(HTTPException) as exc:
        await require_prompt_testing(_caller(), _db_flag(False))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_gate_denies_when_user_missing():
    with pytest.raises(HTTPException) as exc:
        await require_prompt_testing(_caller(), _db_flag(None))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_gate_allows_when_flag_on():
    user = _caller()
    assert await require_prompt_testing(user, _db_flag(True)) is user


# ── Handler: regenerate_note ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_404_when_no_transcript():
    sid = uuid.uuid4()
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=_session(sid)),
        ),
        patch(
            "app.api.v1.sessions._load_transcript", AsyncMock(return_value=None)
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await regenerate_note(
                sid, RegenerateNoteRequest(), _caller(), _db()
            )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_regenerate_reuses_stored_transcript_and_returns_new_version():
    sid = uuid.uuid4()
    transcript = _transcript(sid)
    note = Note(
        session_id=str(sid),
        stage=1,
        version=3,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.82,
    )
    gen = AsyncMock(return_value=note)
    db = _db()
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=_session(sid)),
        ),
        patch(
            "app.api.v1.sessions._load_transcript",
            AsyncMock(return_value=transcript),
        ),
        patch("app.api.v1.sessions.generate_stage1_note", gen),
    ):
        resp = await regenerate_note(
            sid,
            RegenerateNoteRequest(template_key="musculoskeletal"),
            _caller(),
            db,
        )

    assert isinstance(resp, RegenerateNoteResponse)
    assert resp.version == 3
    assert resp.stage == 1
    assert resp.provider_used == "anthropic"
    # Honoured the template override and reused the STORED transcript: the route
    # passes the loaded Transcript straight through — no transcription pipeline.
    kwargs = gen.call_args.kwargs
    assert kwargs["template_key"] == "musculoskeletal"
    assert kwargs["transcript"] is transcript
    db.commit.assert_awaited_once()


# ── Custom-template override is own-scoped (SECURITY) ────────────────────────


@pytest.mark.asyncio
async def test_regenerate_rejects_non_owned_custom_template():
    # A granted caller passing another clinician's PRIVATE template id must 404
    # — get_owned_or_shared returns None for a template they neither own nor is
    # shared. Guards against the cross-tenant template leak.
    sid = uuid.uuid4()
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=_session(sid)),
        ),
        patch(
            "app.modules.custom_templates.service.get_owned_or_shared",
            AsyncMock(return_value=None),
        ),
        patch("app.api.v1.sessions.generate_stage1_note", AsyncMock()) as gen,
    ):
        with pytest.raises(HTTPException) as exc:
            await regenerate_note(
                sid,
                RegenerateNoteRequest(custom_template_id=uuid.uuid4()),
                _caller(),
                _db(),
            )
    assert exc.value.status_code == 404
    gen.assert_not_awaited()  # never reached note-gen with a foreign template


@pytest.mark.asyncio
async def test_regenerate_allows_owned_or_shared_custom_template():
    sid = uuid.uuid4()
    cid = uuid.uuid4()
    transcript = _transcript(sid)
    note = Note(
        session_id=str(sid),
        stage=1,
        version=2,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.5,
    )
    gen = AsyncMock(return_value=note)
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=_session(sid)),
        ),
        patch(
            "app.modules.custom_templates.service.get_owned_or_shared",
            AsyncMock(return_value=SimpleNamespace(id=cid)),
        ),
        patch(
            "app.api.v1.sessions._load_transcript",
            AsyncMock(return_value=transcript),
        ),
        patch("app.api.v1.sessions.generate_stage1_note", gen),
    ):
        resp = await regenerate_note(
            sid,
            RegenerateNoteRequest(custom_template_id=cid),
            _caller(),
            _db(),
        )
    assert resp.version == 2
    assert gen.call_args.kwargs["custom_template_id"] == cid


# ── Admin response mapping ──────────────────────────────────────────────────


def test_user_to_response_carries_prompt_testing_enabled():
    row = SimpleNamespace(
        id=uuid.uuid4(),
        email="a@b.com",
        full_name="A",
        role=UserRole.CLINICIAN,
        is_active=True,
        voice_enrolled=False,
        mfa_required=False,
        mfa_enrolled_at=None,
        created_at=None,
        last_login_at=None,
        prompt_testing_enabled=True,
    )
    resp = user_to_response(row)
    assert resp.prompt_testing_enabled is True
