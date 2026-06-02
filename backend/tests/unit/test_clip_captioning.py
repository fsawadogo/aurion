"""P1-2 -- native clip captioning + still-fallback (Gemini, OpenAI, Anthropic).

Covers the full acceptance-criteria matrix for the second slice of the
dual-mode visual evidence rollout. P1-1 added the abstract `caption_clip`
method to `VisionProvider`; P1-2 lights up real implementations:

  - Gemini   -> native MP4 understanding via `inline_data` mime `video/mp4`
  - OpenAI   -> midpoint-still fallback via `extract_midpoint_still`
  - Anthropic -> midpoint-still fallback via `extract_midpoint_still`

These tests lock the schema surface, the DRY contract (single ffmpeg
invocation site across both fallback providers), the ProviderError
propagation needed for the registry's fallback chain, the
ffmpeg-missing surface for an actionable error, and a PHI scan over
the log statements.

Plan: docs/plans/p1-2-gemini-clip-captioning.md
"""

from __future__ import annotations

import importlib
import inspect
import re
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.types import (
    ClipMaskingMetadata,
    FrameCaption,
    MaskedClip,
    MaskedFrame,
    ProviderError,
    TranscriptSegment,
)
from app.modules.providers.vision import _clip_to_still as clip_to_still_module
from app.modules.providers.vision._clip_to_still import (
    extract_midpoint_still,
    session_id_from_clip_key,
)
from app.modules.providers.vision.anthropic import AnthropicVisionProvider
from app.modules.providers.vision.gemini import GeminiVisionProvider
from app.modules.providers.vision.openai import OpenAIVisionProvider

# ── Fixtures ────────────────────────────────────────────────────────────


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
def anchor() -> TranscriptSegment:
    return TranscriptSegment(
        id="seg_001",
        start_ms=14000,
        end_ms=15000,
        text="abducting the right shoulder",
    )


def _gemini_response_payload(
    *, description: str, confidence: str = "high", reason: str = "clear view"
) -> dict[str, Any]:
    """Build the response body Gemini returns from `generateContent`."""
    body = (
        f'{{"description": "{description}", '
        f'"confidence": "{confidence}", '
        f'"confidence_reason": "{reason}"}}'
    )
    return {"candidates": [{"content": {"parts": [{"text": body}]}}]}


def _openai_response_payload(
    *, description: str, confidence: str = "high", reason: str = "clear view"
) -> dict[str, Any]:
    """Build the response body GPT-4o returns from `chat/completions`."""
    body = (
        f'{{"description": "{description}", '
        f'"confidence": "{confidence}", '
        f'"confidence_reason": "{reason}"}}'
    )
    return {"choices": [{"message": {"content": body}}]}


def _anthropic_response_payload(
    *, description: str, confidence: str = "high", reason: str = "clear view"
) -> dict[str, Any]:
    """Build the tool-use body Claude returns from `/messages`."""
    return {
        "content": [
            {
                "type": "tool_use",
                "name": "emit_frame_caption",
                "input": {
                    "description": description,
                    "confidence": confidence,
                    "confidence_reason": reason,
                },
            }
        ]
    }


def _mock_httpx_response(*, status_code: int, json_body: dict[str, Any]) -> MagicMock:
    """Build a MagicMock that quacks like an httpx.Response."""
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_body
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "server error",
            request=MagicMock(),
            response=response,
        )
    else:
        response.raise_for_status.return_value = None
    return response


# ── AC-1: Gemini native happy path ──────────────────────────────────────


class TestGeminiNativeClipCaptioning:
    @pytest.mark.asyncio
    async def test_happy_path_emits_clip_caption(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """Gemini happy path -- mocked S3 fetch + mocked generateContent
        returns valid JSON. FrameCaption emits with evidence_kind=clip,
        duration_ms=7000, provider_used=gemini, degraded_to_frame=False.
        """
        mp4_bytes = b"fake-mp4-bytes"
        # Patch the S3 client to return our fake MP4 bytes.
        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=mp4_bytes))
        }

        ok_response = _mock_httpx_response(
            status_code=200,
            json_body=_gemini_response_payload(
                description=(
                    "patient demonstrated abduction of the right shoulder "
                    "to approximately 140 degrees then visibly stopped"
                )
            ),
        )

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.gemini.get_s3_client",
            return_value=fake_s3,
        ), patch(
            "app.modules.providers.vision.gemini.httpx.AsyncClient"
        ) as mock_client_cls, patch.dict(
            "os.environ", {"GOOGLE_AI_API_KEY": "test-key"}
        ), patch(
            "app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            caption = await GeminiVisionProvider().caption_clip(clip, anchor)

        # AC-1 assertions.
        assert isinstance(caption, FrameCaption)
        assert caption.evidence_kind == "clip"
        assert caption.duration_ms == 7000
        assert caption.provider_used == "gemini"
        assert caption.degraded_to_frame is False
        assert caption.confidence == "high"
        assert "abduction" in caption.visual_description
        # The anchor id wires through to citation linking.
        assert caption.audio_anchor_id == "seg_001"

    @pytest.mark.asyncio
    async def test_native_path_sends_video_mime(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """The Gemini call body must include `mime_type: video/mp4` so
        the provider knows to invoke native video understanding. If a
        future change accidentally sends `image/jpeg` we'd be silently
        running the still-image path with worse output.
        """
        captured_payload: dict[str, Any] = {}

        async def fake_post(url, *args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            return _mock_httpx_response(
                status_code=200,
                json_body=_gemini_response_payload(description="ok"),
            )

        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"x"))
        }

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

            await GeminiVisionProvider().caption_clip(clip, anchor)

        # Walk the request body for the inline_data part.
        parts = captured_payload["contents"][0]["parts"]
        inline = next(p for p in parts if "inline_data" in p)
        assert inline["inline_data"]["mime_type"] == "video/mp4"

    @pytest.mark.asyncio
    async def test_uses_descriptive_system_prompt(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """The clip path reuses the existing VISION_SYSTEM_PROMPT verbatim
        -- no interpretive language sneaks in via a clip-specific prompt.
        """
        captured_payload: dict[str, Any] = {}

        async def fake_post(url, *args, **kwargs):
            captured_payload.update(kwargs.get("json", {}))
            return _mock_httpx_response(
                status_code=200,
                json_body=_gemini_response_payload(description="ok"),
            )

        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"x"))
        }

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

            await GeminiVisionProvider().caption_clip(clip, anchor)

        sys_prompt_text = captured_payload["systemInstruction"]["parts"][0]["text"]
        assert "Describe only what is literally visible" in sys_prompt_text
        assert "Do not diagnose" in sys_prompt_text

    @pytest.mark.asyncio
    async def test_missing_api_key_raises(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        with patch(
            "app.modules.providers.vision.gemini._GOOGLE_AI_API_KEY", ""
        ):
            with pytest.raises(ProviderError, match="GOOGLE_AI_API_KEY"):
                await GeminiVisionProvider().caption_clip(clip, anchor)


# ── AC-2: OpenAI fallback path ──────────────────────────────────────────


class TestOpenAIClipFallback:
    @pytest.mark.asyncio
    async def test_fallback_emits_degraded_clip_caption(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """OpenAI fallback path -- mocked S3 fetch + mocked ffmpeg extract
        + mocked GPT-4o call -> returns FrameCaption with evidence_kind=clip,
        duration_ms=7000, provider_used=openai, degraded_to_frame=True.
        """
        synthetic_frame = MaskedFrame(
            frame_id="seg_001_midstill",
            session_id="sess-abc",
            timestamp_ms=18000,
            s3_key="clips/sess-abc/seg_001.midstill.jpg",
            masking_confirmed=True,
        )

        ok_response = _mock_httpx_response(
            status_code=200,
            json_body=_openai_response_payload(
                description=(
                    "patient is seated with the right arm partially elevated "
                    "and the elbow extended"
                )
            ),
        )

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.openai.extract_midpoint_still",
            new=AsyncMock(return_value=synthetic_frame),
        ) as mock_extract, patch(
            "app.modules.providers.vision.openai.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.openai._OPENAI_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            caption = await OpenAIVisionProvider().caption_clip(clip, anchor)

        # The shared helper must have been invoked exactly once with the
        # clip -- DRY proof.
        mock_extract.assert_awaited_once()
        called_clip = mock_extract.await_args.args[0]
        assert called_clip.s3_key == clip.s3_key

        # AC-2 assertions on the returned caption.
        assert caption.evidence_kind == "clip"
        assert caption.duration_ms == 7000
        assert caption.provider_used == "openai"
        assert caption.degraded_to_frame is True
        assert "right arm" in caption.visual_description


# ── AC-3: Anthropic fallback path ───────────────────────────────────────


class TestAnthropicClipFallback:
    @pytest.mark.asyncio
    async def test_fallback_emits_degraded_clip_caption(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        """Anthropic fallback path -- same shape as OpenAI AC-2 with
        provider_used=anthropic.
        """
        synthetic_frame = MaskedFrame(
            frame_id="seg_001_midstill",
            session_id="sess-abc",
            timestamp_ms=18000,
            s3_key="clips/sess-abc/seg_001.midstill.jpg",
            masking_confirmed=True,
        )

        ok_response = _mock_httpx_response(
            status_code=200,
            json_body=_anthropic_response_payload(
                description=(
                    "patient demonstrated mid-range shoulder abduction with "
                    "the arm visibly elevated above shoulder height"
                )
            ),
        )

        async def fake_post(*args, **kwargs):
            return ok_response

        with patch(
            "app.modules.providers.vision.anthropic.extract_midpoint_still",
            new=AsyncMock(return_value=synthetic_frame),
        ) as mock_extract, patch(
            "app.modules.providers.vision.anthropic.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.anthropic._ANTHROPIC_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            caption = await AnthropicVisionProvider().caption_clip(clip, anchor)

        mock_extract.assert_awaited_once()
        assert caption.evidence_kind == "clip"
        assert caption.duration_ms == 7000
        assert caption.provider_used == "anthropic"
        assert caption.degraded_to_frame is True


# ── AC-4: DRY -- single ffmpeg invocation site ──────────────────────────


class TestSharedClipToStillHelper:
    """Both OpenAI and Anthropic call the SAME `extract_midpoint_still`
    helper. Asserted three ways:

    1. Import-symbol identity: the symbol resolved from each provider
       module is the exact same callable object as the helper module's
       export. If a future refactor copies the function, this trips.
    2. Source-of-truth grep: there's exactly one `asyncio.create_subprocess_exec`
       site for ffmpeg in `app/modules/providers/vision/`.
    3. Call-counted mock: each provider's clip path goes through the
       single mock, never around it.
    """

    def test_openai_imports_shared_helper(self) -> None:
        from app.modules.providers.vision import openai as openai_module

        assert (
            openai_module.extract_midpoint_still
            is clip_to_still_module.extract_midpoint_still
        )

    def test_anthropic_imports_shared_helper(self) -> None:
        from app.modules.providers.vision import anthropic as anthropic_module

        assert (
            anthropic_module.extract_midpoint_still
            is clip_to_still_module.extract_midpoint_still
        )

    def test_single_ffmpeg_invocation_site_in_vision(self) -> None:
        """Walk every module under `vision/` and confirm only one of them
        calls `asyncio.create_subprocess_exec` -- the shared helper.
        Provider-level inlining would trip this.
        """
        import pkgutil

        import app.modules.providers.vision as vision_pkg

        hits: list[str] = []
        for finder, name, ispkg in pkgutil.iter_modules(vision_pkg.__path__):
            mod = importlib.import_module(f"{vision_pkg.__name__}.{name}")
            try:
                source = inspect.getsource(mod)
            except (OSError, TypeError):
                continue
            if "create_subprocess_exec" in source:
                hits.append(name)
        assert hits == ["_clip_to_still"], (
            f"ffmpeg invocation must live ONLY in `_clip_to_still`; "
            f"found in: {hits}"
        )


# ── AC-5: Provider errors trip the fallback chain ───────────────────────


class TestClipCaptioningErrorPropagation:
    """Each provider's clip path must raise `ProviderError` on a 5xx so
    `provider_registry.get_vision_provider_with_fallback` can move on
    to the next provider. The fallback chain is what makes the
    OpenAI/Anthropic still-fallback path useful when Gemini is down.
    """

    @pytest.mark.asyncio
    async def test_gemini_5xx_raises_provider_error(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        err_response = _mock_httpx_response(status_code=503, json_body={})

        async def fake_post(*args, **kwargs):
            return err_response

        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"x"))
        }

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

            with pytest.raises(ProviderError, match="gemini"):
                await GeminiVisionProvider().caption_clip(clip, anchor)

    @pytest.mark.asyncio
    async def test_openai_5xx_propagates_through_fallback(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        synthetic_frame = MaskedFrame(
            frame_id="seg_001_midstill",
            session_id="sess-abc",
            timestamp_ms=18000,
            s3_key="clips/sess-abc/seg_001.midstill.jpg",
            masking_confirmed=True,
        )
        err_response = _mock_httpx_response(status_code=503, json_body={})

        async def fake_post(*args, **kwargs):
            return err_response

        with patch(
            "app.modules.providers.vision.openai.extract_midpoint_still",
            new=AsyncMock(return_value=synthetic_frame),
        ), patch(
            "app.modules.providers.vision.openai.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.openai._OPENAI_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError, match="openai"):
                await OpenAIVisionProvider().caption_clip(clip, anchor)

    @pytest.mark.asyncio
    async def test_anthropic_5xx_propagates_through_fallback(
        self, clip: MaskedClip, anchor: TranscriptSegment
    ) -> None:
        synthetic_frame = MaskedFrame(
            frame_id="seg_001_midstill",
            session_id="sess-abc",
            timestamp_ms=18000,
            s3_key="clips/sess-abc/seg_001.midstill.jpg",
            masking_confirmed=True,
        )
        err_response = _mock_httpx_response(status_code=503, json_body={})

        async def fake_post(*args, **kwargs):
            return err_response

        with patch(
            "app.modules.providers.vision.anthropic.extract_midpoint_still",
            new=AsyncMock(return_value=synthetic_frame),
        ), patch(
            "app.modules.providers.vision.anthropic.httpx.AsyncClient"
        ) as mock_client_cls, patch(
            "app.modules.providers.vision.anthropic._ANTHROPIC_API_KEY",
            "test-key",
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=fake_post)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            with pytest.raises(ProviderError, match="anthropic"):
                await AnthropicVisionProvider().caption_clip(clip, anchor)


# ── AC-6: ffmpeg-missing actionable error ───────────────────────────────


class TestFFmpegMissingError:
    """When the system `ffmpeg` binary isn't on PATH, the helper must
    raise a clear error mentioning the binary. The operator can install
    it without diving into the codebase.
    """

    @pytest.mark.asyncio
    async def test_extract_midpoint_still_raises_clear_error_when_ffmpeg_absent(
        self, clip: MaskedClip
    ) -> None:
        fake_s3 = MagicMock()
        fake_s3.get_object.return_value = {
            "Body": MagicMock(read=MagicMock(return_value=b"x"))
        }

        async def raise_file_not_found(*args, **kwargs):
            raise FileNotFoundError("[Errno 2] ... 'ffmpeg'")

        with patch(
            "app.modules.providers.vision._clip_to_still.get_s3_client",
            return_value=fake_s3,
        ), patch(
            "app.modules.providers.vision._clip_to_still.asyncio.create_subprocess_exec",
            new=raise_file_not_found,
        ):
            with pytest.raises(FileNotFoundError) as exc_info:
                await extract_midpoint_still(clip)

        assert "ffmpeg" in str(exc_info.value)
        # The error message must be actionable -- the operator needs to
        # know what to install, not just that something went wrong.
        assert (
            "not found" in str(exc_info.value).lower()
            or "install" in str(exc_info.value).lower()
        )


# ── AC-7: No PHI in caption_clip log statements ─────────────────────────


def test_no_phi_in_caption_clip_logs() -> None:
    """Walk the source of every `caption_clip` implementation (Gemini,
    OpenAI, Anthropic) plus the shared `_clip_to_still` helper. Every
    log statement that references the clip's S3 key must truncate it
    (slice operator `[:N]`) -- never log the full key, full anchor
    text, or transcript content.

    The rule:
    - Any `logger.{info,warning,error,debug}(...)` call containing the
      identifier `s3_key` or `clip.s3_key` must also contain a slice
      `[:N]` against that identifier or be wrapped by a truncator
      helper (`_truncate_key` / `[:_LOG_KEY_PREFIX_LEN]`).
    - No log line may interpolate `anchor.text`, `clip.text`,
      `transcript`, or similarly named fields.
    """
    modules = [
        "app.modules.providers.vision.gemini",
        "app.modules.providers.vision.openai",
        "app.modules.providers.vision.anthropic",
        "app.modules.providers.vision._clip_to_still",
    ]

    # Recognized sanitizers -- either a Python slice `[:N]` OR a wrapper
    # call (`_truncate_key(...)`). Both result in a non-PHI prefix.
    # Match `logger.X(...)` calls (across multiple lines) that mention
    # `s3_key` but have NO `[:` slice and NO `_truncate_key(` call
    # inside the argument list.
    logger_call_pattern = re.compile(
        r"logger\.(info|warning|error|debug)\(",
    )
    # Match any logger call that interpolates patient-identifying fields.
    phi_field_pattern = re.compile(
        r"logger\.(info|warning|error|debug)\([^)]*?\b("
        r"anchor\.text|clip\.text|transcript|patient_name|patient_id"
        r")\b"
    )

    def _find_balanced_paren_end(text: str, open_idx: int) -> int:
        """Find the index of the matching `)` for the `(` at open_idx."""
        depth = 0
        for i in range(open_idx, len(text)):
            if text[i] == "(":
                depth += 1
            elif text[i] == ")":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    offenses: list[str] = []
    for mod_name in modules:
        mod = importlib.import_module(mod_name)
        source = inspect.getsource(mod)
        # Strip comments so a "do not log foo" comment doesn't trip us.
        source_no_comments = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        )
        # Find every logger.X( call and inspect its full argument span.
        for match in logger_call_pattern.finditer(source_no_comments):
            open_paren_idx = match.end() - 1
            close_paren_idx = _find_balanced_paren_end(
                source_no_comments, open_paren_idx
            )
            if close_paren_idx == -1:
                continue
            call_args = source_no_comments[open_paren_idx : close_paren_idx + 1]
            if "s3_key" in call_args:
                # Sanitized if either a slice or a truncator wrapper is present.
                sanitized = (
                    "[:" in call_args
                    or "_truncate_key(" in call_args
                )
                if not sanitized:
                    offenses.append(
                        f"{mod_name}: logger emits a full S3 key (no slice / truncator)"
                    )
            phi_hit = phi_field_pattern.search(call_args)
            if phi_hit:
                offenses.append(
                    f"{mod_name}: logger emits PHI-bearing field "
                    f"`{phi_hit.group(2)}`"
                )

    assert offenses == [], "PHI scan tripped:\n  " + "\n  ".join(offenses)


# ── AC-8: LSP -- clip caption schema matches frame caption schema ───────


class TestLSPClipFrameSchemaParity:
    """The Stage 2 dispatcher (P1-3) must treat clip and frame captions
    interchangeably. The only structural differences between a clip
    caption and a frame caption are: evidence_kind, duration_ms, and
    -- for the lossy fallback -- degraded_to_frame.
    """

    def test_clip_caption_schema_matches_frame_caption_schema(self) -> None:
        # Both kinds of caption are FrameCaption instances; the field
        # set is the same Pydantic model -- LSP at the type boundary.
        frame_caption = FrameCaption(
            frame_id="frame_001",
            session_id="sess_1",
            timestamp_ms=10000,
            audio_anchor_id="seg_001",
            provider_used="openai",
            visual_description="patient seated",
            confidence="high",
            integration_status="ENRICHES",
        )
        clip_caption = FrameCaption(
            frame_id="clip_001",
            session_id="sess_1",
            timestamp_ms=14500,
            audio_anchor_id="seg_001",
            provider_used="gemini",
            visual_description="patient demonstrated abduction",
            confidence="high",
            integration_status="ENRICHES",
            evidence_kind="clip",
            duration_ms=7000,
        )
        # Same field set -- the dispatcher doesn't need to branch on
        # type.
        assert set(frame_caption.model_dump().keys()) == set(
            clip_caption.model_dump().keys()
        )


# ── Helper: session_id_from_clip_key parsing ────────────────────────────


class TestSessionIdFromClipKey:
    """The shared parser is used by both Gemini's native path and the
    still-fallback helper; locking its behavior keeps the synthetic
    `MaskedFrame.session_id` consistent across both routes.
    """

    def test_parses_canonical_clip_key(self) -> None:
        assert session_id_from_clip_key("clips/sess-abc/seg_001.mp4") == "sess-abc"

    def test_returns_empty_on_unexpected_shape(self) -> None:
        assert session_id_from_clip_key("not-a-clip-key") == ""
        assert session_id_from_clip_key("frames/sess-1/foo.jpg") == ""


# ── Helper: derived still key ──────────────────────────────────────────


class TestDeriveStillKey:
    """The derived-key shape is load-bearing: the TTL policy on the
    `frames` bucket sweeps both clip MP4s and their extracted stills
    under the `clips/` prefix. If a future refactor moves the still to
    `frames/...`, it would orphan from the clip's TTL.
    """

    def test_mp4_becomes_midstill_jpg(self) -> None:
        from app.modules.providers.vision._clip_to_still import _derive_still_key

        assert (
            _derive_still_key("clips/sess-1/seg_001.mp4")
            == "clips/sess-1/seg_001.midstill.jpg"
        )

    def test_non_mp4_key_appends_suffix(self) -> None:
        from app.modules.providers.vision._clip_to_still import _derive_still_key

        # Defensive: unexpected extension keeps the full key + appends.
        assert (
            _derive_still_key("clips/sess-1/seg_001.unknown")
            == "clips/sess-1/seg_001.unknown.midstill.jpg"
        )
