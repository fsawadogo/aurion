"""Focused owner-deadline coverage for doctor-facing Stage 1 generation."""

from __future__ import annotations

import asyncio
import time
from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.types import Note, NoteSection, Template, TemplateSection, Transcript
from app.modules.config.schema import AppConfigSchema
from app.modules.note_gen import service


def _transcript() -> Transcript:
    return Transcript.model_validate(
        {
            "session_id": "00000000-0000-0000-0000-000000000001",
            "provider_used": "whisper",
            "segments": [
                {
                    "id": "seg_001",
                    "start_ms": 0,
                    "end_ms": 1000,
                    "text": "The patient described persistent left knee pain.",
                }
            ],
        }
    )


def _note() -> Note:
    return Note(
        session_id="00000000-0000-0000-0000-000000000001",
        stage=1,
        version=1,
        provider_used="anthropic",
        specialty="general",
        completeness_score=1.0,
        sections=[
            NoteSection(
                id="hpi",
                title="History",
                status="populated",
                claims=[],
            )
        ],
    )


@contextmanager
def _stage1_environment(provider, critique, usage=None):
    template = Template(
        key="general",
        display_name="General",
        sections=[TemplateSection(id="hpi", title="History")],
    )
    registry = SimpleNamespace(
        get_note_provider_with_fallback=lambda: provider,
    )
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(service, "_enforce_transcript_guard", AsyncMock())
        )
        stack.enter_context(
            patch.object(
                service,
                "_resolve_stage1_template",
                AsyncMock(return_value=template),
            )
        )
        stack.enter_context(patch.object(service, "get_registry", return_value=registry))
        stack.enter_context(
            patch.object(
                service,
                "assemble_prompt_for_session",
                AsyncMock(return_value="safe system prompt"),
            )
        )
        stack.enter_context(
            patch.object(
                service,
                "_load_prior_context_block",
                AsyncMock(return_value=(None, "")),
            )
        )
        stack.enter_context(
            patch.object(
                service,
                "_record_provider_usage",
                usage if usage is not None else AsyncMock(),
            )
        )
        stack.enter_context(
            patch.object(
                service,
                "_emit_longitudinal_context_audit",
                AsyncMock(),
            )
        )
        create_version = stack.enter_context(
            patch.object(service, "create_note_version", AsyncMock())
        )
        stack.enter_context(patch.object(service, "critique_note", critique))
        stack.enter_context(
            patch.object(service, "get_config", return_value=AppConfigSchema())
        )
        yield create_version


def _db() -> AsyncMock:
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    return db


@pytest.mark.asyncio
async def test_default_budget_allows_work_past_alert_target_before_hard_deadline() -> None:
    """The alert target must not cancel otherwise useful provider work."""

    async def generate_note(*_args, **_kwargs) -> Note:
        # Scaled clock: 30 ms represents the 30 s alert target, while the
        # patched 100 ms hard deadline represents the 90 s availability cap.
        await asyncio.sleep(0.05)
        return _note()

    provider = SimpleNamespace(generate_note=AsyncMock(side_effect=generate_note))
    started = time.monotonic()
    with (
        _stage1_environment(provider, AsyncMock()) as create_version,
        patch.object(service, "stage1_hard_deadline_ms", return_value=100),
    ):
        note = await service.generate_stage1_note(
            transcript=_transcript(),
            specialty="general",
            session_id="00000000-0000-0000-0000-000000000001",
            db=_db(),
            participants=[],
        )

    elapsed = time.monotonic() - started
    assert elapsed >= 0.03
    assert elapsed < 0.2
    assert note.provider_used == "anthropic"
    create_version.assert_awaited_once()


@pytest.mark.asyncio
async def test_default_budget_cancels_provider_at_hard_deadline() -> None:
    provider_cancelled = asyncio.Event()

    async def blocked_provider(*_args, **_kwargs) -> Note:
        try:
            await asyncio.Event().wait()
        finally:
            provider_cancelled.set()

    provider = SimpleNamespace(generate_note=AsyncMock(side_effect=blocked_provider))
    with (
        _stage1_environment(provider, AsyncMock()) as create_version,
        patch.object(service, "stage1_hard_deadline_ms", return_value=60),
    ):
        with pytest.raises(service.Stage1DeadlineExceededError) as caught:
            await service.generate_stage1_note(
                transcript=_transcript(),
                specialty="general",
                session_id="00000000-0000-0000-0000-000000000001",
                db=_db(),
                participants=[],
            )

    assert caught.value.reason == "stage1_deadline_exceeded"
    assert provider_cancelled.is_set()
    create_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_and_critique_share_the_owner_remaining_budget() -> None:
    critique_cancelled = asyncio.Event()

    async def generate_note(*_args, **_kwargs) -> Note:
        await asyncio.sleep(0.07)
        return _note()

    async def blocked_critique(*_args, **_kwargs) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            critique_cancelled.set()

    provider = SimpleNamespace(generate_note=AsyncMock(side_effect=generate_note))
    critique = AsyncMock(side_effect=blocked_critique)
    loop = asyncio.get_running_loop()
    started = time.monotonic()

    with _stage1_environment(provider, critique) as create_version:
        note = await service.generate_stage1_note(
            transcript=_transcript(),
            specialty="general",
            session_id="00000000-0000-0000-0000-000000000001",
            db=_db(),
            participants=[],
            deadline_at=loop.time() + 0.12,
        )

    assert time.monotonic() - started < 0.25
    assert critique_cancelled.is_set()
    assert note.provider_used == "anthropic"
    create_version.assert_awaited_once()


@pytest.mark.asyncio
async def test_owned_provider_timeout_is_stable_and_cancels_work() -> None:
    provider_cancelled = asyncio.Event()

    async def blocked_provider(*_args, **_kwargs) -> Note:
        try:
            await asyncio.Event().wait()
        finally:
            provider_cancelled.set()

    provider = SimpleNamespace(generate_note=AsyncMock(side_effect=blocked_provider))
    critique = AsyncMock()

    with _stage1_environment(provider, critique) as create_version:
        with pytest.raises(service.Stage1DeadlineExceededError) as caught:
            await service.generate_stage1_note(
                transcript=_transcript(),
                specialty="general",
                session_id="00000000-0000-0000-0000-000000000001",
                db=_db(),
                participants=[],
                deadline_at=asyncio.get_running_loop().time() + 0.08,
            )

    assert caught.value.reason == "stage1_deadline_exceeded"
    assert str(caught.value) == (
        "Stage 1 exceeded its configured processing deadline."
    )
    assert provider_cancelled.is_set()
    create_version.assert_not_awaited()


@pytest.mark.asyncio
async def test_stalled_success_telemetry_cannot_outlive_owner_budget() -> None:
    telemetry_cancelled = asyncio.Event()

    async def blocked_usage(**_kwargs) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            telemetry_cancelled.set()

    provider = SimpleNamespace(generate_note=AsyncMock(return_value=_note()))
    critique = AsyncMock()
    usage = AsyncMock(side_effect=blocked_usage)
    started = time.monotonic()

    with _stage1_environment(provider, critique, usage) as create_version:
        note = await service.generate_stage1_note(
            transcript=_transcript(),
            specialty="general",
            session_id="00000000-0000-0000-0000-000000000001",
            db=_db(),
            participants=[],
            deadline_at=asyncio.get_running_loop().time() + 0.08,
        )

    assert time.monotonic() - started < 0.3
    assert telemetry_cancelled.is_set()
    assert note.provider_used == "anthropic"
    # Scheduler precision may leave a sub-millisecond remainder in which the
    # best-effort critique can start and return immediately. The invariant here
    # is that stalled telemetry was cancelled and note delivery stayed bounded.
    assert critique.await_count <= 1
    create_version.assert_awaited_once()


@pytest.mark.asyncio
async def test_external_cancellation_is_not_translated_to_deadline() -> None:
    provider_started = asyncio.Event()
    provider_cancelled = asyncio.Event()

    async def blocked_provider(*_args, **_kwargs) -> Note:
        provider_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            provider_cancelled.set()

    provider = SimpleNamespace(generate_note=AsyncMock(side_effect=blocked_provider))

    with (
        _stage1_environment(provider, AsyncMock()) as create_version,
        patch.object(service, "stage1_hard_deadline_ms", return_value=5_000),
    ):
        task = asyncio.create_task(
            service.generate_stage1_note(
                transcript=_transcript(),
                specialty="general",
                session_id="00000000-0000-0000-0000-000000000001",
                db=_db(),
                participants=[],
            )
        )
        await provider_started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert provider_cancelled.is_set()
    create_version.assert_not_awaited()
