"""Unit tests for per-user prompt-testing gate + regenerate-note (#590).

Covers the role-agnostic, owner-scoped ``POST /sessions/{id}/regenerate-note``:
the ``prompt_testing_enabled`` gate (403 when off), the missing-transcript 404,
and the happy path — reuse the STORED transcript (no re-transcribe) + honour a
template override + return the new note version. Plus the admin response
mapping carries the new flag.
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

# ── Helpers ─────────────────────────────────────────────────────────────────


def _user_row(prompt_testing_enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(prompt_testing_enabled=prompt_testing_enabled)


def _transcript_row(session_id: uuid.UUID) -> SimpleNamespace:
    t = Transcript(session_id=str(session_id), provider_used="whisper", segments=[])
    return SimpleNamespace(transcript_json=t.model_dump_json())


def _session(session_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=session_id,
        specialty="orthopedic_surgery",
        output_language="en",
        encounter_context=None,
    )


def _config(note_options_enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(
        feature_flags=SimpleNamespace(note_options_enabled=note_options_enabled)
    )


def _caller() -> SimpleNamespace:
    return SimpleNamespace(user_id=uuid.uuid4(), role=None, email="x@x.com")


def _db(*, user_row, transcript_row) -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock(return_value=user_row)  # UserModel lookup = the gate
    result = MagicMock()
    result.scalar_one_or_none.return_value = transcript_row
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()
    return db


# ── The gate ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_denied_when_both_gates_off():
    """403 when the user lacks prompt_testing AND the global
    note_options_enabled flag is off."""
    sid = uuid.uuid4()
    db = _db(user_row=_user_row(False), transcript_row=_transcript_row(sid))
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=_session(sid)),
        ),
        patch(
            "app.api.v1.sessions.get_config",
            return_value=_config(note_options_enabled=False),
        ),
    ):
        with pytest.raises(HTTPException) as exc:
            await regenerate_note(sid, RegenerateNoteRequest(), _caller(), db)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_regenerate_allowed_via_note_options_flag():
    """A clinician WITHOUT prompt_testing may regenerate their own note when
    the global note_options_enabled flag is on (owner-scoped, descriptive)."""
    sid = uuid.uuid4()
    db = _db(user_row=_user_row(False), transcript_row=_transcript_row(sid))
    note = Note(
        session_id=str(sid),
        stage=1,
        version=2,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.7,
    )
    gen = AsyncMock(return_value=note)
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=_session(sid)),
        ),
        patch(
            "app.api.v1.sessions.get_config",
            return_value=_config(note_options_enabled=True),
        ),
        patch("app.api.v1.sessions.generate_stage1_note", gen),
    ):
        resp = await regenerate_note(sid, RegenerateNoteRequest(), _caller(), db)
    assert resp.version == 2
    gen.assert_awaited_once()


@pytest.mark.asyncio
async def test_regenerate_persists_and_threads_encounter_context():
    """The change-context action persists the new context on the session AND
    passes it into note-gen so the regenerated note is focused on it."""
    sid = uuid.uuid4()
    session = _session(sid)
    session.encounter_context = "Breast augmentation consult"
    db = _db(user_row=_user_row(True), transcript_row=_transcript_row(sid))
    note = Note(
        session_id=str(sid),
        stage=1,
        version=5,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.6,
    )
    gen = AsyncMock(return_value=note)
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=session),
        ),
        patch("app.api.v1.sessions.generate_stage1_note", gen),
    ):
        await regenerate_note(
            sid,
            RegenerateNoteRequest(
                encounter_context="Breast augmentation; also liposuction"
            ),
            _caller(),
            db,
        )
    # Persisted to the session row + threaded into note-gen.
    assert session.encounter_context == "Breast augmentation; also liposuction"
    assert (
        gen.call_args.kwargs["encounter_context"]
        == "Breast augmentation; also liposuction"
    )


@pytest.mark.asyncio
async def test_regenerate_blank_context_clears_it():
    sid = uuid.uuid4()
    session = _session(sid)
    session.encounter_context = "old context"
    db = _db(user_row=_user_row(True), transcript_row=_transcript_row(sid))
    note = Note(
        session_id=str(sid), stage=1, version=2, provider_used="anthropic",
        specialty="orthopedic_surgery", completeness_score=0.5,
    )
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=session),
        ),
        patch(
            "app.api.v1.sessions.generate_stage1_note",
            AsyncMock(return_value=note),
        ),
    ):
        await regenerate_note(
            sid, RegenerateNoteRequest(encounter_context="  "), _caller(), db
        )
    assert session.encounter_context is None


@pytest.mark.asyncio
async def test_regenerate_omitted_context_leaves_session_unchanged():
    sid = uuid.uuid4()
    session = _session(sid)
    session.encounter_context = "keep me"
    db = _db(user_row=_user_row(True), transcript_row=_transcript_row(sid))
    note = Note(
        session_id=str(sid), stage=1, version=2, provider_used="anthropic",
        specialty="orthopedic_surgery", completeness_score=0.5,
    )
    gen = AsyncMock(return_value=note)
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=session),
        ),
        patch("app.api.v1.sessions.generate_stage1_note", gen),
    ):
        await regenerate_note(sid, RegenerateNoteRequest(), _caller(), db)
    assert session.encounter_context == "keep me"
    assert gen.call_args.kwargs["encounter_context"] == "keep me"


@pytest.mark.asyncio
async def test_regenerate_threads_output_language():
    """The change-language action passes output_language through to note-gen;
    omitted → falls back to the session's stored output_language."""
    sid = uuid.uuid4()
    db = _db(user_row=_user_row(True), transcript_row=_transcript_row(sid))
    note = Note(
        session_id=str(sid),
        stage=1,
        version=4,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.6,
    )
    gen = AsyncMock(return_value=note)
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=_session(sid)),
        ),
        patch("app.api.v1.sessions.generate_stage1_note", gen),
    ):
        await regenerate_note(
            sid, RegenerateNoteRequest(output_language="fr"), _caller(), db
        )
    assert gen.call_args.kwargs["output_language"] == "fr"


@pytest.mark.asyncio
async def test_regenerate_404_when_no_transcript():
    sid = uuid.uuid4()
    db = _db(user_row=_user_row(True), transcript_row=None)
    with patch(
        "app.api.v1.sessions.get_owned_session_or_404",
        AsyncMock(return_value=_session(sid)),
    ):
        with pytest.raises(HTTPException) as exc:
            await regenerate_note(sid, RegenerateNoteRequest(), _caller(), db)
    assert exc.value.status_code == 404


# ── Happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regenerate_reuses_stored_transcript_and_returns_new_version():
    sid = uuid.uuid4()
    db = _db(user_row=_user_row(True), transcript_row=_transcript_row(sid))
    note = Note(
        session_id=str(sid),
        stage=1,
        version=3,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.82,
    )
    gen = AsyncMock(return_value=note)
    with (
        patch(
            "app.api.v1.sessions.get_owned_session_or_404",
            AsyncMock(return_value=_session(sid)),
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
    # Honoured the template override and reused the STORED transcript (the route
    # never calls a transcription pipeline — it passes the parsed Transcript).
    kwargs = gen.call_args.kwargs
    assert kwargs["template_key"] == "musculoskeletal"
    assert isinstance(kwargs["transcript"], Transcript)
    db.commit.assert_awaited_once()


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


# ── Custom-template override is own-scoped (SECURITY) ────────────────────────


@pytest.mark.asyncio
async def test_regenerate_rejects_non_owned_custom_template():
    # A granted caller passing another clinician's PRIVATE template id must 404
    # — get_owned_or_shared returns None for a template they neither own nor is
    # shared. Guards against the cross-tenant template leak.
    sid = uuid.uuid4()
    db = _db(user_row=_user_row(True), transcript_row=_transcript_row(sid))
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
                db,
            )
    assert exc.value.status_code == 404
    gen.assert_not_awaited()  # never reached note-gen with a foreign template


@pytest.mark.asyncio
async def test_regenerate_allows_owned_or_shared_custom_template():
    sid = uuid.uuid4()
    cid = uuid.uuid4()
    db = _db(user_row=_user_row(True), transcript_row=_transcript_row(sid))
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
        patch("app.api.v1.sessions.generate_stage1_note", gen),
    ):
        resp = await regenerate_note(
            sid,
            RegenerateNoteRequest(custom_template_id=cid),
            _caller(),
            db,
        )
    assert resp.version == 2
    assert gen.call_args.kwargs["custom_template_id"] == cid
