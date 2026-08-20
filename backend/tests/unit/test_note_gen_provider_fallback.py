"""Stage-1 note generation — runtime provider-chain fallback.

Historically ``get_note_provider_with_fallback`` re-resolved the same
configured primary after a failure (all three providers are always
registered, so the "fallback" loop returned the primary on its first
iteration) — a Gemini 429 that outlived the provider's bounded retry
failed Stage 1 outright. These tests lock the corrected contract:

  * registry: ``get_note_provider_chain`` returns the ordered,
    duplicate-free chain with the configured primary first;
  * service: a ``ProviderError`` from the primary advances to the next
    provider in the chain and the note comes back from the fallback;
  * a non-provider error (bug in our own code) does NOT fall back;
  * an explicit per-session override is a pin — no fallback under it.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import (
    Note,
    NoteSection,
    ProviderError,
    Transcript,
    TranscriptSegment,
)
from app.modules.config.provider_registry import ProviderRegistry
from app.modules.config.schema import AppConfigSchema
from app.modules.note_gen.service import generate_stage1_note
from app.modules.providers.note_gen.anthropic import AnthropicNoteGenerationProvider
from app.modules.providers.note_gen.gemini import GeminiNoteGenerationProvider


def _mock_config(note_generation: str = "anthropic") -> AppConfigSchema:
    return AppConfigSchema.model_validate(
        {
            "providers": {
                "transcription": "whisper",
                "note_generation": note_generation,
                "vision": "openai",
            }
        }
    )


# ── Registry: chain resolution ───────────────────────────────────────────────


class TestNoteProviderChain:
    def test_chain_orders_configured_primary_first(self) -> None:
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(note_generation="gemini"),
        ):
            chain = registry.get_note_provider_chain()

        assert isinstance(chain[0], GeminiNoteGenerationProvider)
        # Duplicate-free: every registered provider appears exactly once.
        assert len(chain) == 3
        assert len({type(p) for p in chain}) == 3

    def test_with_fallback_returns_chain_head(self) -> None:
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(note_generation="anthropic"),
        ):
            provider = registry.get_note_provider_with_fallback()
        assert isinstance(provider, AnthropicNoteGenerationProvider)


# ── Service: runtime fallback across the chain ───────────────────────────────


def _transcript(session_id: str) -> Transcript:
    return Transcript(
        session_id=session_id,
        provider_used="whisper",
        segments=[
            TranscriptSegment(
                id="seg_000",
                start_ms=0,
                end_ms=2000,
                text="Patient describes anterior knee pain for two weeks.",
            )
        ],
    )


def _stub_note(session_id: str, provider_used: str) -> Note:
    return Note(
        session_id=session_id,
        stage=1,
        provider_used=provider_used,
        specialty="orthopedic_surgery",
        sections=[NoteSection(id="chief_complaint", status="not_captured")],
    )


def _provider(result: Note | None = None, error: Exception | None = None) -> MagicMock:
    provider = MagicMock()
    if error is not None:
        provider.generate_note = AsyncMock(side_effect=error)
    else:
        provider.generate_note = AsyncMock(return_value=result)
    return provider


def _service_patches(fake_registry: MagicMock):
    return (
        patch("app.modules.note_gen.service.get_registry", return_value=fake_registry),
        patch(
            "app.modules.note_gen.service.assemble_prompt_for_session",
            new_callable=AsyncMock,
            return_value="stub system prompt",
        ),
        patch(
            "app.modules.note_gen.service._load_prior_context_block",
            new_callable=AsyncMock,
            return_value=(None, ""),
        ),
        patch("app.modules.note_gen.service.critique_note", new_callable=AsyncMock),
        patch(
            "app.modules.note_gen.service.create_note_version",
            new_callable=AsyncMock,
        ),
        patch(
            "app.modules.note_gen.service._record_provider_usage",
            new_callable=AsyncMock,
        ),
    )


async def test_provider_error_falls_back_to_next_in_chain() -> None:
    session_id = str(uuid.uuid4())
    failing = _provider(error=ProviderError("gemini", "429 outlived bounded retry"))
    succeeding = _provider(result=_stub_note(session_id, "anthropic"))

    fake_registry = MagicMock()
    fake_registry.get_note_provider_chain = MagicMock(
        return_value=[failing, succeeding]
    )

    p1, p2, p3, p4, p5, p6 = _service_patches(fake_registry)
    with p1, p2, p3, p4, p5, p6:
        note = await generate_stage1_note(
            transcript=_transcript(session_id),
            specialty="orthopedic_surgery",
            session_id=session_id,
            db=AsyncMock(),
        )

    assert failing.generate_note.await_count == 1
    assert succeeding.generate_note.await_count == 1
    assert note.provider_used == "anthropic"


async def test_provider_error_on_every_provider_raises_last_error() -> None:
    session_id = str(uuid.uuid4())
    first = _provider(error=ProviderError("gemini", "rate limited"))
    second = _provider(error=ProviderError("anthropic", "unavailable"))

    fake_registry = MagicMock()
    fake_registry.get_note_provider_chain = MagicMock(return_value=[first, second])

    p1, p2, p3, p4, p5, p6 = _service_patches(fake_registry)
    with p1, p2, p3, p4, p5, p6:
        with pytest.raises(ProviderError, match="unavailable"):
            await generate_stage1_note(
                transcript=_transcript(session_id),
                specialty="orthopedic_surgery",
                session_id=session_id,
                db=AsyncMock(),
            )

    assert first.generate_note.await_count == 1
    assert second.generate_note.await_count == 1


async def test_non_provider_error_does_not_fall_back() -> None:
    session_id = str(uuid.uuid4())
    buggy = _provider(error=RuntimeError("our own bug — not a provider outage"))
    never_called = _provider(result=_stub_note(session_id, "anthropic"))

    fake_registry = MagicMock()
    fake_registry.get_note_provider_chain = MagicMock(
        return_value=[buggy, never_called]
    )

    p1, p2, p3, p4, p5, p6 = _service_patches(fake_registry)
    with p1, p2, p3, p4, p5, p6:
        with pytest.raises(RuntimeError):
            await generate_stage1_note(
                transcript=_transcript(session_id),
                specialty="orthopedic_surgery",
                session_id=session_id,
                db=AsyncMock(),
            )

    assert never_called.generate_note.await_count == 0


async def test_explicit_override_is_a_pin_no_fallback() -> None:
    session_id = str(uuid.uuid4())
    pinned = _provider(error=ProviderError("openai", "rate limited"))

    fake_registry = MagicMock()
    fake_registry.get_note_provider = MagicMock(return_value=pinned)

    p1, p2, p3, p4, p5, p6 = _service_patches(fake_registry)
    with p1, p2, p3, p4, p5, p6:
        with pytest.raises(ProviderError):
            await generate_stage1_note(
                transcript=_transcript(session_id),
                specialty="orthopedic_surgery",
                session_id=session_id,
                db=AsyncMock(),
                provider_override="openai",
            )

    fake_registry.get_note_provider.assert_called_once_with(override="openai")
    fake_registry.get_note_provider_chain.assert_not_called()
    assert pinned.generate_note.await_count == 1
