"""Unit tests for the Stage 2 vision dispatch by evidence_kind (P1-3).

P1-3 extended the Stage 2 captioning loop to route per-evidence by
`evidence_kind`: clips go to `provider.caption_clip`, frames go to
`provider.caption_frame`. Both methods return the same `FrameCaption`
schema (LSP), so the downstream merge / conflict-detection / Stage 2
progress hooks stay evidence-kind-agnostic.

This suite locks the dispatch contract:

- Mixed frames + clips evidence routes each item to the right provider
  method (no `caption_clip` called for a frame, no `caption_frame`
  called for a clip).
- Low-confidence clips emit a `CLIP_DISCARDED` audit event carrying
  the s3_key + confidence + confidence_reason; low-confidence frames
  stay silent (existing behavior preserved).
- `registry.get_vision_provider_for_kind` returns the correct concrete
  provider class for the `"clip"` kind based on AppConfig
  `providers.vision_clip`.
- Log lines do not leak full session_id or evidence bodies.

Plan: docs/plans/p1-3-clips-endpoint.md
"""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit_events import AuditEventType
from app.core.types import (
    ClipMaskingMetadata,
    FrameCaption,
    MaskedClip,
    MaskedFrame,
    TranscriptSegment,
)
from app.modules.vision import service as vision_service

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def trigger() -> TranscriptSegment:
    return TranscriptSegment(
        id="seg_001",
        start_ms=14000,
        end_ms=15000,
        text="abducting the right shoulder",
        is_visual_trigger=True,
        trigger_type="motion",
    )


@pytest.fixture
def frame() -> MaskedFrame:
    return MaskedFrame(
        frame_id="frame_14500",
        session_id="00000000-0000-0000-0000-000000000001",
        timestamp_ms=14500,
        s3_key="frames/00000000-0000-0000-0000-000000000001/14500.jpg",
        masking_confirmed=True,
    )


@pytest.fixture
def clip() -> MaskedClip:
    return MaskedClip(
        s3_key="clips/00000000-0000-0000-0000-000000000001/aabb.mp4",
        timestamp_ms=14500,
        duration_ms=7000,
        trigger_segment_id="seg_001",
        masking_metadata=ClipMaskingMetadata(
            frames_total=210, frames_with_faces=210, faces_blurred=210
        ),
    )


def _frame_caption(
    *,
    evidence_kind: str = "frame",
    confidence: str = "high",
    confidence_reason: str = "clear view",
    provider: str = "openai",
    frame_id: str = "frame_14500",
) -> FrameCaption:
    return FrameCaption(
        frame_id=frame_id,
        session_id="00000000-0000-0000-0000-000000000001",
        timestamp_ms=14500,
        audio_anchor_id="seg_001",
        provider_used=provider,
        visual_description="Patient demonstrated shoulder abduction.",
        confidence=confidence,
        confidence_reason=confidence_reason,
        integration_status="ENRICHES",
        evidence_kind=evidence_kind,
        duration_ms=7000 if evidence_kind == "clip" else None,
    )


# ── Registry kind routing ──────────────────────────────────────────────────


def test_registry_routes_clip_kind_to_vision_clip_config(monkeypatch) -> None:
    """`get_vision_provider_for_kind("clip")` reads
    `config.providers.vision_clip` (defaults Gemini) — not the
    frame-path `providers.vision`."""
    from app.modules.config.provider_registry import ProviderRegistry
    from app.modules.config.schema import (
        AppConfigSchema,
        ProvidersConfig,
        VisionProviderKey,
    )
    from app.modules.providers.vision.gemini import GeminiVisionProvider

    cfg = AppConfigSchema(
        providers=ProvidersConfig(
            vision=VisionProviderKey.OPENAI,
            vision_clip=VisionProviderKey.GEMINI,
        )
    )
    monkeypatch.setattr(
        "app.modules.config.provider_registry.get_config",
        lambda: cfg,
    )
    monkeypatch.setattr(
        "app.modules.config.provider_registry.get_override",
        lambda _key: None,
    )

    registry = ProviderRegistry()
    provider = registry.get_vision_provider_for_kind("clip")
    assert isinstance(provider, GeminiVisionProvider)


def test_registry_routes_frame_kind_to_vision_config(monkeypatch) -> None:
    """`get_vision_provider_for_kind("frame")` reads
    `config.providers.vision`."""
    from app.modules.config.provider_registry import ProviderRegistry
    from app.modules.config.schema import (
        AppConfigSchema,
        ProvidersConfig,
        VisionProviderKey,
    )
    from app.modules.providers.vision.anthropic import AnthropicVisionProvider

    cfg = AppConfigSchema(
        providers=ProvidersConfig(
            vision=VisionProviderKey.ANTHROPIC,
            vision_clip=VisionProviderKey.GEMINI,
        )
    )
    monkeypatch.setattr(
        "app.modules.config.provider_registry.get_config",
        lambda: cfg,
    )
    monkeypatch.setattr(
        "app.modules.config.provider_registry.get_override",
        lambda _key: None,
    )

    registry = ProviderRegistry()
    provider = registry.get_vision_provider_for_kind("frame")
    assert isinstance(provider, AnthropicVisionProvider)


def test_registry_unknown_kind_raises() -> None:
    from app.core.types import ProviderError
    from app.modules.config.provider_registry import ProviderRegistry

    with pytest.raises(ProviderError):
        ProviderRegistry().get_vision_provider_for_kind("thermal")


# ── Stage 2 dispatch ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stage2_dispatches_mixed_evidence(
    frame: MaskedFrame, clip: MaskedClip, trigger: TranscriptSegment
) -> None:
    """Mixed list (one frame + one clip) → caption_frame called on the
    frame, caption_clip called on the clip. Each provider method is
    called exactly once."""
    provider = MagicMock()
    provider.caption_frame = AsyncMock(
        return_value=_frame_caption(evidence_kind="frame")
    )
    provider.caption_clip = AsyncMock(
        return_value=_frame_caption(evidence_kind="clip", frame_id="seg_001_clip")
    )
    registry = MagicMock()
    registry.get_vision_provider_for_kind_with_fallback = MagicMock(
        return_value=provider
    )

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=AsyncMock()),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
    ):
        captions = await vision_service.caption_visual_evidence(
            evidence=[frame, clip], trigger_segments=[trigger]
        )

    assert provider.caption_frame.await_count == 1
    assert provider.caption_clip.await_count == 1
    # Each call received its kind's object.
    frame_arg = provider.caption_frame.await_args.args[0]
    clip_arg = provider.caption_clip.await_args.args[0]
    assert isinstance(frame_arg, MaskedFrame)
    assert isinstance(clip_arg, MaskedClip)
    # Both captions surfaced in the result.
    assert len(captions) == 2
    kinds = {c.evidence_kind for c in captions}
    assert kinds == {"frame", "clip"}


@pytest.mark.asyncio
async def test_low_confidence_clip_emits_clip_discarded(
    clip: MaskedClip, trigger: TranscriptSegment
) -> None:
    """Low-confidence clip → CLIP_DISCARDED audit event with the
    s3_key + confidence + confidence_reason."""
    provider = MagicMock()
    provider.caption_clip = AsyncMock(
        return_value=_frame_caption(
            evidence_kind="clip",
            confidence="low",
            confidence_reason="motion blur",
        )
    )
    registry = MagicMock()
    registry.get_vision_provider_for_kind_with_fallback = MagicMock(
        return_value=provider
    )

    audit = AsyncMock()
    audit.write_event = AsyncMock()

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=audit),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
    ):
        captions = await vision_service.caption_visual_evidence(
            evidence=[clip], trigger_segments=[trigger]
        )

    # Discarded — no caption returned.
    assert captions == []

    # CLIP_DISCARDED audit event with the expected kwargs.
    clip_discard_calls = [
        c for c in audit.write_event.await_args_list
        if c.kwargs.get("event_type") == AuditEventType.CLIP_DISCARDED
    ]
    assert len(clip_discard_calls) == 1, (
        f"Expected CLIP_DISCARDED; got {[c.kwargs for c in audit.write_event.await_args_list]}"
    )
    payload = clip_discard_calls[0].kwargs
    assert payload["s3_key"] == clip.s3_key
    assert payload["confidence"] == "low"
    assert payload["confidence_reason"] == "motion blur"


@pytest.mark.asyncio
async def test_low_confidence_frame_does_not_emit_clip_discarded(
    frame: MaskedFrame, trigger: TranscriptSegment
) -> None:
    """Low-confidence frame stays silent (existing behavior) —
    no CLIP_DISCARDED emitted on the frame path."""
    provider = MagicMock()
    provider.caption_frame = AsyncMock(
        return_value=_frame_caption(
            evidence_kind="frame",
            confidence="low",
            confidence_reason="dark frame",
        )
    )
    registry = MagicMock()
    registry.get_vision_provider_for_kind_with_fallback = MagicMock(
        return_value=provider
    )
    audit = AsyncMock()
    audit.write_event = AsyncMock()

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=audit),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
    ):
        captions = await vision_service.caption_visual_evidence(
            evidence=[frame], trigger_segments=[trigger]
        )

    assert captions == []
    # No CLIP_DISCARDED on the frame path.
    clip_discard_calls = [
        c for c in audit.write_event.await_args_list
        if c.kwargs.get("event_type") == AuditEventType.CLIP_DISCARDED
    ]
    assert clip_discard_calls == []


@pytest.mark.asyncio
async def test_caption_frames_wrapper_routes_through_dispatch(
    frame: MaskedFrame, trigger: TranscriptSegment
) -> None:
    """The legacy `caption_frames` wrapper still works — it delegates
    to `caption_visual_evidence` so all existing call sites (notes
    service today) keep working byte-for-byte."""
    provider = MagicMock()
    provider.caption_frame = AsyncMock(
        return_value=_frame_caption(evidence_kind="frame")
    )
    registry = MagicMock()
    registry.get_vision_provider_for_kind_with_fallback = MagicMock(
        return_value=provider
    )

    with (
        patch.object(vision_service, "get_registry", return_value=registry),
        patch.object(vision_service, "get_audit_log_service", return_value=AsyncMock()),
        patch.object(vision_service, "try_record_provider_usage", AsyncMock()),
    ):
        captions = await vision_service.caption_frames([frame], [trigger])

    assert provider.caption_frame.await_count == 1
    assert provider.caption_clip.call_count == 0  # never called for frames
    assert len(captions) == 1
    assert captions[0].evidence_kind == "frame"


# ── PHI scan ───────────────────────────────────────────────────────────────


def _extract_logger_calls_from_module(module) -> list[str]:
    """Extract every `logger.<level>(...)` call in a module's source."""
    import ast

    source = inspect.getsource(module)
    tree = ast.parse(source)
    calls: list[str] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "logger"
        ):
            calls.append(ast.unparse(node))
    return calls


def test_no_phi_in_vision_service_log_calls() -> None:
    """AC-9: vision/service.py logger calls never pass a raw session_id
    UUID, transcript text, evidence bodies, or clip MP4 bytes.

    AST-walks the module so only real logger.* call expressions are
    scanned (docstrings + comments don't trip the check).
    """
    calls = _extract_logger_calls_from_module(vision_service)
    assert calls, "Expected logger calls in vision/service.py."

    forbidden = [
        # transcript content into logs:
        "anchor.text",
        # raw session_id positional arg:
        ", session_id,",
        ", session_id)",
        # raw evidence bodies:
        "mp4_bytes",
        ", body,",
    ]
    for call_src in calls:
        for needle in forbidden:
            assert needle not in call_src, (
                f"vision/service.py logger call leaks {needle!r}: {call_src!r}"
            )
