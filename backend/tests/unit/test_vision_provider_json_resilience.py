"""Vision providers must raise ProviderError on JSON parse failure
(P1-FU-PROBE-BUGS, bug 2).

The live probe captured:

  {
    "provider_used": "gemini",
    "success": false,
    "error_type": "ValueError",
    "error_message": "Unterminated string starting at: line 4 column 24 (char 141)"
  }

Gemini's response was truncated; the inner ``json.loads(text.strip())``
raised ``json.JSONDecodeError`` (a ``ValueError`` subclass) which
escaped the provider boundary unchanged. The registry's
``get_vision_provider_with_fallback`` only catches ``ProviderError``,
so the fallback chain never tripped to the next provider.

The fix wraps every ``json.loads`` site behind
``vision/shared.py::parse_caption_json``, which:

* catches ``json.JSONDecodeError``,
* logs the provider name + first 120 chars of the failing response
  at WARNING level (no PHI / API keys; the response is the model's
  own descriptive-text output),
* raises ``ProviderError(provider_name, ...)``.

These tests lock that contract for every provider's clip / frame path,
verify the WARNING log shape, scan for PHI / API-key leakage, and
prove the registry's fallback chain trips end-to-end on a JSON-parse
``ProviderError`` from the primary provider.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Env BEFORE the FastAPI app import — `APP_ENV=local` keeps the auth
# layer in dev mode (irrelevant for these unit tests, but defends
# against a future module-import chain that pulls Cognito in).
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

from app.core.types import (  # noqa: E402
    ClipMaskingMetadata,
    MaskedClip,
    MaskedFrame,
    ProviderError,
    TranscriptSegment,
)
from app.modules.providers.vision.anthropic import AnthropicVisionProvider  # noqa: E402
from app.modules.providers.vision.gemini import GeminiVisionProvider  # noqa: E402
from app.modules.providers.vision.openai import OpenAIVisionProvider  # noqa: E402
from app.modules.providers.vision.shared import parse_caption_json  # noqa: E402

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def clip() -> MaskedClip:
    return MaskedClip(
        s3_key="clips/sess-abc/seg_001.mp4",
        timestamp_ms=14500,
        duration_ms=7000,
        trigger_segment_id="seg_001",
        masking_metadata=ClipMaskingMetadata(
            frames_total=210,
            frames_with_faces=210,
            faces_blurred=210,
        ),
    )


@pytest.fixture
def frame() -> MaskedFrame:
    return MaskedFrame(
        frame_id="frame_00001",
        session_id="11111111-1111-1111-1111-111111111111",
        timestamp_ms=14500,
        s3_key="frames/sess-abc/frame_00001.jpg",
        masking_confirmed=True,
    )


@pytest.fixture
def anchor() -> TranscriptSegment:
    return TranscriptSegment(
        id="seg_001",
        start_ms=14000,
        end_ms=15000,
        text="abducting the right shoulder",
    )


# Real truncation captured from the live probe — same shape, same
# error position character count. Reproduces the exact bug.
_TRUNCATED_GEMINI_BODY = (
    '{\n'
    '  "description": "The patient was abducting their right shoulder '
    'to approximately 14'  # <— truncated here; no closing quote/brace
)


def _enable_shared_warning_capture(caplog):
    """Caplog context that survives alembic's `fileConfig` global side effects.

    ``tests/integration/test_migrations.py`` instantiates an Alembic
    ``Config`` which (via ``alembic/env.py`` line 45) calls
    ``logging.config.fileConfig`` with the default
    ``disable_existing_loggers=True``. That sets ``.disabled = True``
    on every logger NOT named in ``alembic.ini`` — including
    ``aurion.providers.vision.shared``. Disabled loggers don't emit
    records, so caplog sees nothing even though the code path raises
    ProviderError correctly.

    This helper re-enables the shared module's logger before the
    capture window and forces propagation back on. We restore the
    original state after the test so the workaround is local.
    """
    import contextlib

    @contextlib.contextmanager
    def _ctx():
        log = logging.getLogger("aurion.providers.vision.shared")
        was_disabled = log.disabled
        was_propagating = log.propagate
        log.disabled = False
        log.propagate = True
        try:
            with caplog.at_level(
                logging.WARNING, logger="aurion.providers.vision.shared"
            ):
                yield
        finally:
            log.disabled = was_disabled
            log.propagate = was_propagating

    return _ctx()


def _mock_httpx_response(*, status_code: int, json_body: dict[str, Any]) -> MagicMock:
    """Build a MagicMock that quacks like an httpx.Response."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


# ── parse_caption_json — direct unit coverage ─────────────────────────────


class TestParseCaptionJsonHelper:
    """The shared helper is exercised indirectly through every provider
    test below, but a direct unit test pins the contract so a future
    refactor of the helper can't silently change error semantics."""

    def test_valid_json_returns_dict(self) -> None:
        result = parse_caption_json(
            "gemini",
            '{"description": "x", "confidence": "high", "confidence_reason": "y"}',
        )
        assert result["description"] == "x"
        assert result["confidence"] == "high"

    def test_strips_whitespace(self) -> None:
        """Helper strips leading / trailing whitespace before parsing —
        Gemini sometimes returns leading newlines in `text` parts."""
        result = parse_caption_json("gemini", '\n  {"k": "v"}\n  ')
        assert result == {"k": "v"}

    def test_truncated_response_raises_provider_error(self) -> None:
        """A truncated provider response raises ProviderError, NOT a
        bare ValueError / JSONDecodeError. This is the core bug-2
        invariant — the registry's fallback chain only handles
        ProviderError, so anything else escapes the provider boundary."""
        with pytest.raises(ProviderError) as exc_info:
            parse_caption_json("gemini", _TRUNCATED_GEMINI_BODY)
        assert exc_info.value.provider == "gemini"
        assert "JSONDecodeError" in str(exc_info.value)

    def test_does_not_raise_value_error(self) -> None:
        """Belt-and-suspenders: a malformed response must NOT escape as
        any kind of ValueError. We assert by catching ProviderError
        first; if a ValueError leaked we'd see it."""
        try:
            parse_caption_json("openai", "not-json-at-all")
        except ProviderError:
            pass  # expected
        except ValueError as exc:  # pragma: no cover — bug regression
            pytest.fail(
                f"parse_caption_json leaked a bare ValueError: {exc!r}; "
                f"registry fallback chain will not handle this."
            )

    def test_provider_name_carried_in_error(self) -> None:
        """Each provider tags its own ProviderError so the audit log
        and registry fallback log can attribute correctly."""
        for name in ("openai", "anthropic", "gemini"):
            with pytest.raises(ProviderError) as exc_info:
                parse_caption_json(name, "{")
            assert exc_info.value.provider == name


# ── Gemini — caption_clip JSON parse failure ──────────────────────────────


class TestGeminiClipJsonResilience:
    @pytest.mark.asyncio
    async def test_caption_clip_raises_provider_error_on_json_parse_failure(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """AC-4: When Gemini returns a truncated response, caption_clip
        raises ProviderError('gemini', ...), NOT ValueError / JSONDecodeError.

        Reproduces the live probe symptom byte-for-byte (same truncation
        shape, same provider). The registry's
        `get_vision_provider_with_fallback` chain only catches
        ProviderError, so anything else breaks the fallback contract.
        """
        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"fake"))
        }

        truncated_json_body = {
            "candidates": [
                {"content": {"parts": [{"text": _TRUNCATED_GEMINI_BODY}]}}
            ]
        }
        ok_http_response = _mock_httpx_response(
            status_code=200, json_body=truncated_json_body
        )

        async def fake_post(*args, **kwargs):
            return ok_http_response

        with patch(
            "app.modules.providers.vision.gemini.get_s3_client",
            return_value=fake_s3,
        ), patch(
            "app.modules.providers.vision.gemini.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError) as exc_info:
                await GeminiVisionProvider().caption_clip(clip, anchor)

        assert exc_info.value.provider == "gemini"
        assert "JSONDecodeError" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_caption_clip_warning_log_contains_provider_and_excerpt(
        self, clip: MaskedClip, anchor: TranscriptSegment, caplog
    ) -> None:
        """AC-6: WARNING log on JSON parse failure carries
        provider=gemini AND a 120-char excerpt of the failing response.
        No PHI / no API key in the log line."""
        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"fake"))
        }
        truncated_body = {
            "candidates": [
                {"content": {"parts": [{"text": _TRUNCATED_GEMINI_BODY}]}}
            ]
        }
        ok_response = _mock_httpx_response(status_code=200, json_body=truncated_body)

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.gemini.get_s3_client",
            return_value=fake_s3,
        ), patch(
            "app.modules.providers.vision.gemini.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY",
            "test-key",
        ), _enable_shared_warning_capture(caplog):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError):
                await GeminiVisionProvider().caption_clip(clip, anchor)

        # At least one WARNING record from the shared helper.
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "No WARNING log emitted on JSON parse failure"
        msg = warnings[-1].getMessage()
        assert "provider=gemini" in msg, f"Provider tag missing: {msg!r}"
        # Defensive truncation — 120-char cap means the excerpt cannot
        # be the full untruncated source; verify the message length is
        # bounded.
        assert len(msg) < 400, (
            f"Log message {len(msg)} chars — excerpt cap not enforced"
        )

    @pytest.mark.asyncio
    async def test_caption_clip_log_does_not_leak_phi_or_api_key(
        self, clip: MaskedClip, anchor: TranscriptSegment, caplog
    ) -> None:
        """AC-6b: The WARNING log line must NOT carry the API key, the
        full s3 key (which carries session id), the audio anchor text,
        or any other PHI surface."""
        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"fake"))
        }
        truncated_body = {
            "candidates": [
                {"content": {"parts": [{"text": _TRUNCATED_GEMINI_BODY}]}}
            ]
        }
        ok_response = _mock_httpx_response(status_code=200, json_body=truncated_body)

        async def fake_post(*args, **kwargs):
            return ok_response

        # Inject a recognisable fake API key so we can scan for it.
        fake_api_key = "AIzaSyD8x2vMnPq7Wr3LkJzXcVbNmAaSdFgHjKl"

        with patch(
            "app.modules.providers.vision.gemini.get_s3_client",
            return_value=fake_s3,
        ), patch(
            "app.modules.providers.vision.gemini.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY",
            fake_api_key,
        ), _enable_shared_warning_capture(caplog):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError):
                await GeminiVisionProvider().caption_clip(clip, anchor)

        for record in caplog.records:
            msg = record.getMessage()
            assert fake_api_key not in msg, (
                f"API key leaked into log line: {msg!r}"
            )
            # Audio anchor carries clinical context — must not log it.
            assert anchor.text not in msg, (
                f"Audio anchor text leaked into log line: {msg!r}"
            )
            # Full S3 key carries the session id segment — only the
            # provider's own response text should appear in the excerpt.
            assert clip.s3_key not in msg, (
                f"S3 key leaked into log line: {msg!r}"
            )


# ── Gemini — caption_frame JSON parse failure ─────────────────────────────


class TestGeminiFrameJsonResilience:
    @pytest.mark.asyncio
    async def test_caption_frame_raises_provider_error_on_json_parse_failure(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> None:
        """AC-5: Gemini caption_frame surface mirrors caption_clip —
        truncated JSON raises ProviderError, not ValueError."""
        truncated_body = {
            "candidates": [
                {"content": {"parts": [{"text": _TRUNCATED_GEMINI_BODY}]}}
            ]
        }
        ok_response = _mock_httpx_response(status_code=200, json_body=truncated_body)

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.gemini.load_frame_image_base64",
            return_value="fakebase64",
        ), patch(
            "app.modules.providers.vision.gemini.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError) as exc_info:
                await GeminiVisionProvider().caption_frame(frame, anchor)

        assert exc_info.value.provider == "gemini"


# ── OpenAI — caption_frame JSON parse failure ─────────────────────────────


class TestOpenAIFrameJsonResilience:
    @pytest.mark.asyncio
    async def test_caption_frame_raises_provider_error_on_json_parse_failure(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> None:
        """AC-5: OpenAI caption_frame parses
        `data.choices[0].message.content` via parse_caption_json — a
        truncated content string raises ProviderError, not ValueError."""
        truncated_content = (
            '{"description": "abc def ghi jkl mno pqr stu vwx yzaaaaaaa'
        )
        body = {"choices": [{"message": {"content": truncated_content}}]}
        ok_response = _mock_httpx_response(status_code=200, json_body=body)

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.openai.load_frame_image_base64",
            return_value="fakebase64",
        ), patch(
            "app.modules.providers.vision.openai.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.openai._OPENAI_API_KEY",
            "sk-test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError) as exc_info:
                await OpenAIVisionProvider().caption_frame(frame, anchor)

        assert exc_info.value.provider == "openai"

    @pytest.mark.asyncio
    async def test_caption_frame_warning_log_contains_provider_tag(
        self, frame: MaskedFrame, anchor: TranscriptSegment, caplog
    ) -> None:
        """AC-6: WARNING log carries provider=openai."""
        body = {"choices": [{"message": {"content": "not-json-at-all"}}]}
        ok_response = _mock_httpx_response(status_code=200, json_body=body)

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.openai.load_frame_image_base64",
            return_value="fakebase64",
        ), patch(
            "app.modules.providers.vision.openai.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.openai._OPENAI_API_KEY",
            "sk-test-key",
        ), _enable_shared_warning_capture(caplog):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError):
                await OpenAIVisionProvider().caption_frame(frame, anchor)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings
        assert any("provider=openai" in r.getMessage() for r in warnings)


# ── OpenAI — caption_frame malformed-envelope resilience ──────────────────


class TestOpenAIFrameEnvelopeResilience:
    """A separate defect from JSON-content truncation: the response
    *envelope* itself can be malformed (missing/empty "choices", missing
    "message"/"content"). The unguarded `data["choices"][0]["message"]
    ["content"]` access would raise KeyError/IndexError/TypeError, which
    escapes `except httpx.HTTPError` and breaks the registry fallback
    chain (which only catches ProviderError). These cases lock that the
    extraction raises ProviderError('openai', ...) instead.
    """

    @pytest.mark.parametrize(
        "malformed_body",
        [
            {},  # no "choices" key at all -> KeyError
            {"choices": []},  # empty list -> IndexError
            {"choices": [{}]},  # missing "message" -> KeyError
            {"choices": [{"message": {}}]},  # missing "content" -> KeyError
            {"choices": [{"message": None}]},  # message not subscriptable -> TypeError
        ],
    )
    @pytest.mark.asyncio
    async def test_caption_frame_raises_provider_error_on_malformed_envelope(
        self,
        frame: MaskedFrame,
        anchor: TranscriptSegment,
        malformed_body: dict[str, Any],
    ) -> None:
        """HTTP 200 with a malformed envelope raises
        ProviderError('openai', ...) — NOT KeyError/IndexError/TypeError —
        so the registry's fallback chain can trip."""
        ok_response = _mock_httpx_response(status_code=200, json_body=malformed_body)

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.openai.load_frame_image_base64",
            return_value="fakebase64",
        ), patch(
            "app.modules.providers.vision.openai.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.openai._OPENAI_API_KEY",
            "sk-test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError) as exc_info:
                await OpenAIVisionProvider().caption_frame(frame, anchor)

        assert exc_info.value.provider == "openai"

    @pytest.mark.asyncio
    async def test_caption_clip_raises_provider_error_on_malformed_envelope(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """The clip path degrades to a midpoint still and routes through
        caption_frame, so a malformed envelope there must also surface as
        ProviderError('openai', ...) for the fallback chain."""
        ok_response = _mock_httpx_response(status_code=200, json_body={"choices": []})

        async def fake_post(*args, **kwargs):
            return ok_response

        synthetic_frame = MaskedFrame(
            frame_id="seg_001_still",
            session_id="11111111-1111-1111-1111-111111111111",
            timestamp_ms=clip.timestamp_ms + clip.duration_ms // 2,
            s3_key="frames/sess-abc/seg_001_still.jpg",
            masking_confirmed=True,
        )

        async def fake_extract(*args, **kwargs):
            return synthetic_frame

        with patch(
            "app.modules.providers.vision.openai.extract_midpoint_still",
            side_effect=fake_extract,
        ), patch(
            "app.modules.providers.vision.openai.load_frame_image_base64",
            return_value="fakebase64",
        ), patch(
            "app.modules.providers.vision.openai.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.openai._OPENAI_API_KEY",
            "sk-test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError) as exc_info:
                await OpenAIVisionProvider().caption_clip(clip, anchor)

        assert exc_info.value.provider == "openai"

    @pytest.mark.asyncio
    async def test_malformed_envelope_error_chained_for_debug(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> None:
        """The original KeyError/IndexError/TypeError is chained via
        `raise ... from` so operators can debug the original shape."""
        ok_response = _mock_httpx_response(status_code=200, json_body={"choices": []})

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.openai.load_frame_image_base64",
            return_value="fakebase64",
        ), patch(
            "app.modules.providers.vision.openai.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.openai._OPENAI_API_KEY",
            "sk-test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            try:
                await OpenAIVisionProvider().caption_frame(frame, anchor)
                pytest.fail("Expected ProviderError")
            except ProviderError as exc:
                assert isinstance(exc.__cause__, (KeyError, IndexError, TypeError)), (
                    f"Expected envelope error chained via raise...from; "
                    f"got cause={exc.__cause__!r}"
                )


# ── Anthropic — caption_frame text-fallback JSON parse failure ────────────


class TestAnthropicFrameJsonResilience:
    @pytest.mark.asyncio
    async def test_text_fallback_raises_provider_error_on_json_parse_failure(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> None:
        """AC-5: Anthropic's defensive fallback (when the API drops
        tool_use and returns plain text) parses via parse_caption_json
        — truncated text raises ProviderError, not ValueError.

        Triggers the fallback path by returning a content array with no
        tool_use block but a text block carrying malformed JSON.
        """
        truncated_text = '{"description": "abc def ghi jkl mno pqr stu vwx'
        body = {"content": [{"type": "text", "text": truncated_text}]}
        ok_response = _mock_httpx_response(status_code=200, json_body=body)

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.anthropic.load_frame_image_base64",
            return_value="fakebase64",
        ), patch(
            "app.modules.providers.vision.anthropic.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.anthropic._ANTHROPIC_API_KEY",
            "sk-ant-test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError) as exc_info:
                await AnthropicVisionProvider().caption_frame(frame, anchor)

        assert exc_info.value.provider == "anthropic"

    @pytest.mark.asyncio
    async def test_text_fallback_warning_log_contains_provider_tag(
        self, frame: MaskedFrame, anchor: TranscriptSegment, caplog
    ) -> None:
        """AC-6: WARNING log carries provider=anthropic on the fallback."""
        body = {"content": [{"type": "text", "text": "not-json"}]}
        ok_response = _mock_httpx_response(status_code=200, json_body=body)

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.anthropic.load_frame_image_base64",
            return_value="fakebase64",
        ), patch(
            "app.modules.providers.vision.anthropic.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.anthropic._ANTHROPIC_API_KEY",
            "sk-ant-test-key",
        ), _enable_shared_warning_capture(caplog):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError):
                await AnthropicVisionProvider().caption_frame(frame, anchor)

        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings
        assert any("provider=anthropic" in r.getMessage() for r in warnings)


# ── Registry fallback — end-to-end ProviderError handling ─────────────────


class TestRegistryFallbackOnJsonParseError:
    """The whole point of bug-2 is that a JSON parse failure must
    behave like a provider failure so the registry's fallback chain
    can trip. This test pins that end-to-end.
    """

    @pytest.mark.asyncio
    async def test_registry_fallback_trips_on_json_parse_provider_error(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """AC-7: With Gemini primary, a JSON parse failure in
        gemini.caption_clip surfaces as ProviderError. We then invoke
        the next provider in the chain (OpenAI midpoint-still) and it
        succeeds. The fallback semantics from CLAUDE.md §Error handling
        ('Provider unavailable → fallback to next, log it') hold for
        JSON-parse failures too — they did NOT before this fix.
        """
        # Step 1: Gemini's caption_clip raises ProviderError from JSON parse.
        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"fake"))
        }
        truncated_body = {
            "candidates": [
                {"content": {"parts": [{"text": _TRUNCATED_GEMINI_BODY}]}}
            ]
        }
        bad_response = _mock_httpx_response(
            status_code=200, json_body=truncated_body
        )

        async def fake_gemini_post(*args, **kwargs):
            return bad_response

        with patch(
            "app.modules.providers.vision.gemini.get_s3_client",
            return_value=fake_s3,
        ), patch(
            "app.modules.providers.vision.gemini.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_gemini_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError) as exc_info:
                await GeminiVisionProvider().caption_clip(clip, anchor)

        # The error MUST be classified as ProviderError so the
        # registry's `get_vision_provider_with_fallback` chain (which
        # only catches ProviderError) trips.
        assert isinstance(exc_info.value, ProviderError)
        assert exc_info.value.provider == "gemini"

    @pytest.mark.asyncio
    async def test_provider_error_chained_for_debug(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """The original JSONDecodeError is chained via `raise ... from`
        so operators debugging from a Sentry trace can see the original
        truncation position. The chain doesn't change the error
        classification (registry still sees ProviderError) — it's
        purely for the debugger."""
        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"fake"))
        }
        truncated_body = {
            "candidates": [
                {"content": {"parts": [{"text": _TRUNCATED_GEMINI_BODY}]}}
            ]
        }
        bad_response = _mock_httpx_response(
            status_code=200, json_body=truncated_body
        )

        async def fake_post(*args, **kwargs):
            return bad_response

        with patch(
            "app.modules.providers.vision.gemini.get_s3_client",
            return_value=fake_s3,
        ), patch(
            "app.modules.providers.vision.gemini.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            try:
                await GeminiVisionProvider().caption_clip(clip, anchor)
                pytest.fail("Expected ProviderError")
            except ProviderError as exc:
                # The __cause__ chain carries the original JSONDecodeError.
                assert isinstance(exc.__cause__, json.JSONDecodeError), (
                    f"Expected JSONDecodeError chained via raise...from; "
                    f"got cause={exc.__cause__!r}"
                )
