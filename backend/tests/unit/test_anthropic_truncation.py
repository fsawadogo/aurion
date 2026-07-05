"""Regression: Anthropic max_tokens truncation must never yield a blank note.

Field incident (2026-07-05, video import session 43a300e1): a 400-segment
transcript exceeded the configured note-gen output ceiling. The API returned
``stop_reason="max_tokens"`` with an EMPTY tool input (``{}``), which parsed
"successfully" into a zero-section note → backfilled 10/10 → a BLANK note
delivered as success.

The provider now checks ``stop_reason``: on truncation it retries once at an
escalated ceiling, and if that truncates too it raises ``ProviderError`` (loud
pipeline failure) instead of returning the empty payload.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import (
    ProviderError,
    Template,
    TemplateSection,
    Transcript,
    TranscriptSegment,
)


def _response(json_payload: dict) -> MagicMock:
    r = MagicMock()
    r.raise_for_status = MagicMock()
    r.json = MagicMock(return_value=json_payload)
    return r


def _client(responses: list[MagicMock]) -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock(side_effect=responses)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _truncated() -> dict:
    # What the API actually returns when generation is cut off mid-tool-call:
    # stop_reason=max_tokens and an empty tool input.
    return {
        "stop_reason": "max_tokens",
        "usage": {"input_tokens": 5000, "output_tokens": 8000},
        "content": [
            {"type": "tool_use", "name": "emit_clinical_note", "input": {}}
        ],
    }


def _complete() -> dict:
    return {
        "stop_reason": "tool_use",
        "usage": {"input_tokens": 5000, "output_tokens": 1200},
        "content": [
            {
                "type": "tool_use",
                "name": "emit_clinical_note",
                "input": {
                    "sections": [
                        {
                            "id": "cc",
                            "title": "CC",
                            "status": "populated",
                            "claims": [
                                {
                                    "id": "c1",
                                    "text": "Patient reported knee pain.",
                                    "source_type": "transcript",
                                    "source_id": "seg_001",
                                    "source_quote": "knee pain",
                                }
                            ],
                        }
                    ]
                },
            }
        ],
    }


def _transcript() -> Transcript:
    return Transcript(
        session_id="s",
        provider_used="whisper",
        segments=[
            TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="knee pain")
        ],
    )


def _template() -> Template:
    return Template(
        key="general",
        display_name="General",
        sections=[TemplateSection(id="cc", title="CC", required=True)],
    )


@pytest.mark.asyncio
async def test_truncation_retries_at_escalated_ceiling_then_succeeds(monkeypatch) -> None:
    from app.modules.providers.note_gen import anthropic as a

    monkeypatch.setattr(a, "_ANTHROPIC_API_KEY", "key")
    client = _client([_response(_truncated()), _response(_complete())])

    with patch("httpx.AsyncClient", return_value=client):
        note = await a.AnthropicNoteGenerationProvider().generate_note(
            transcript=_transcript(), template=_template(), stage=1
        )

    # Retried exactly once, at a HIGHER max_tokens than the first attempt.
    assert client.post.await_count == 2
    first = client.post.await_args_list[0].kwargs["json"]["max_tokens"]
    second = client.post.await_args_list[1].kwargs["json"]["max_tokens"]
    assert second > first
    # And the retry's payload parsed into a real (non-blank) note.
    assert note.completeness_score > 0
    assert any(s.status == "populated" and s.claims for s in note.sections)


@pytest.mark.asyncio
async def test_truncation_on_every_ceiling_raises_not_blank_note(monkeypatch) -> None:
    from app.modules.providers.note_gen import anthropic as a

    monkeypatch.setattr(a, "_ANTHROPIC_API_KEY", "key")
    client = _client([_response(_truncated()), _response(_truncated())])

    with patch("httpx.AsyncClient", return_value=client):
        with pytest.raises(ProviderError) as exc:
            await a.AnthropicNoteGenerationProvider().generate_note(
                transcript=_transcript(), template=_template(), stage=1
            )

    assert "truncated" in str(exc.value)
    assert client.post.await_count == 2


@pytest.mark.asyncio
async def test_untrucated_response_is_single_call(monkeypatch) -> None:
    from app.modules.providers.note_gen import anthropic as a

    monkeypatch.setattr(a, "_ANTHROPIC_API_KEY", "key")
    client = _client([_response(_complete())])

    with patch("httpx.AsyncClient", return_value=client):
        note = await a.AnthropicNoteGenerationProvider().generate_note(
            transcript=_transcript(), template=_template(), stage=1
        )

    assert client.post.await_count == 1
    assert note.completeness_score > 0
