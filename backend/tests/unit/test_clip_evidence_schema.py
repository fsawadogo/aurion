"""P1-1 — dual-mode visual evidence schema + provider interface.

Locks the schema surface introduced by P1-1 so any future drift trips
the test suite. The PR is additive — every assertion here also proves
that today's `FRAMES_ONLY` default behavior is byte-identical.

See docs/plans/p1-1-clip-evidence-schema.md.
"""

from __future__ import annotations

from typing import get_args

import pytest
from pydantic import ValidationError

from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType
from app.core.types import (
    ClipMaskingMetadata,
    FrameCaption,
    MaskedClip,
    MaskedFrame,
    TranscriptSegment,
)
from app.modules.config.schema import (
    AppConfigSchema,
    FeatureFlagsConfig,
    PipelineConfig,
    ProvidersConfig,
    VisionProviderKey,
    VisualEvidenceMode,
)
from app.modules.providers.base import VisionProvider
from app.modules.providers.vision.anthropic import AnthropicVisionProvider
from app.modules.providers.vision.gemini import GeminiVisionProvider
from app.modules.providers.vision.openai import OpenAIVisionProvider

# ── VisualEvidenceMode enum ─────────────────────────────────────────────


class TestVisualEvidenceModeEnum:
    """AC-1: the enum locks the three values; renaming any of them
    would silently break the AppConfig contract.
    """

    def test_member_values_locked(self) -> None:
        actual = {m.name: m.value for m in VisualEvidenceMode}
        assert actual == {
            "FRAMES_ONLY": "frames_only",
            "CLIPS_ONLY": "clips_only",
            "HYBRID": "hybrid",
        }

    def test_str_subclass_for_appconfig_serialization(self) -> None:
        # AppConfig persists values as plain strings — StrEnum semantics
        # mean f"{mode}" == "frames_only", not "VisualEvidenceMode.FRAMES_ONLY".
        assert VisualEvidenceMode.FRAMES_ONLY == "frames_only"
        assert f"{VisualEvidenceMode.HYBRID}" == "VisualEvidenceMode.HYBRID" or \
               f"{VisualEvidenceMode.HYBRID}" == "hybrid"
        # The above tolerates Python 3.11 vs 3.12 StrEnum vs str(Enum)
        # differences. The wire-serialization that matters is `.value`.
        assert VisualEvidenceMode.HYBRID.value == "hybrid"


# ── PipelineConfig defaults ─────────────────────────────────────────────


class TestPipelineConfigDualMode:
    """AC-2 + AC-4: defaults preserve today's behavior (`frames_only`)
    and `clip_trigger_kinds` covers the four motion-heavy use cases.
    """

    def test_visual_evidence_mode_defaults_frames_only(self) -> None:
        config = PipelineConfig()
        assert config.visual_evidence_mode == VisualEvidenceMode.FRAMES_ONLY
        # Belt-and-suspenders: the wire form is `"frames_only"`. Anything
        # else means a future change broke the byte-identical default.
        assert config.visual_evidence_mode.value == "frames_only"

    def test_clip_window_ms_default(self) -> None:
        assert PipelineConfig().clip_window_ms == 7000

    def test_clip_ring_buffer_seconds_default(self) -> None:
        assert PipelineConfig().clip_ring_buffer_seconds == 15

    def test_clip_trigger_kinds_default(self) -> None:
        assert PipelineConfig().clip_trigger_kinds == [
            "motion",
            "rom",
            "gait",
            "procedural",
        ]

    def test_clip_window_ms_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PipelineConfig(clip_window_ms=500)  # below min 1000
        with pytest.raises(ValidationError):
            PipelineConfig(clip_window_ms=999_999)  # above max 30000

    def test_clip_trigger_kinds_is_independent_per_instance(self) -> None:
        # Mutable defaults bite if we used `Field(default=[...])`. The
        # schema uses `default_factory`; verify two instances don't share
        # the same list object.
        a = PipelineConfig()
        b = PipelineConfig()
        a.clip_trigger_kinds.append("custom")
        assert b.clip_trigger_kinds == ["motion", "rom", "gait", "procedural"]


# ── ProvidersConfig.vision_clip ─────────────────────────────────────────


class TestProvidersConfigVisionClip:
    """AC-3: `vision_clip` defaults to Gemini (only native-video model)
    and accepts any `VisionProviderKey` member.
    """

    def test_vision_clip_defaults_to_gemini(self) -> None:
        config = ProvidersConfig()
        assert config.vision_clip == VisionProviderKey.GEMINI

    def test_vision_clip_independent_from_vision(self) -> None:
        # The frame provider stays OPENAI by default; routing is
        # independent.
        config = ProvidersConfig()
        assert config.vision == VisionProviderKey.OPENAI
        assert config.vision_clip == VisionProviderKey.GEMINI

    def test_vision_clip_accepts_any_provider_key(self) -> None:
        config = ProvidersConfig(vision_clip="anthropic")
        assert config.vision_clip == VisionProviderKey.ANTHROPIC

    def test_vision_clip_invalid_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProvidersConfig(vision_clip="invalid_provider")


# ── FeatureFlagsConfig ──────────────────────────────────────────────────


class TestFeatureFlagsPerSessionOverride:
    def test_per_session_visual_evidence_mode_override_defaults_true(self) -> None:
        flags = FeatureFlagsConfig()
        assert flags.per_session_visual_evidence_mode_override is True


# ── AppConfigSchema integration ─────────────────────────────────────────


class TestAppConfigDualMode:
    """The full AppConfig document validates with the new fields present
    and with them absent (backward compat: today's deployed AppConfig
    JSON missing the new keys still loads with safe defaults).
    """

    def test_full_default_validates(self) -> None:
        config = AppConfigSchema()
        assert config.providers.vision_clip == VisionProviderKey.GEMINI
        assert (
            config.pipeline.visual_evidence_mode
            == VisualEvidenceMode.FRAMES_ONLY
        )
        assert (
            config.feature_flags.per_session_visual_evidence_mode_override
            is True
        )

    def test_dual_mode_explicit_values(self) -> None:
        config = AppConfigSchema(
            **{
                "providers": {"vision_clip": "anthropic"},
                "pipeline": {
                    "visual_evidence_mode": "hybrid",
                    "clip_window_ms": 5000,
                    "clip_ring_buffer_seconds": 30,
                    "clip_trigger_kinds": ["rom", "gait"],
                },
            }
        )
        assert config.providers.vision_clip == VisionProviderKey.ANTHROPIC
        assert config.pipeline.visual_evidence_mode == VisualEvidenceMode.HYBRID
        assert config.pipeline.clip_window_ms == 5000
        assert config.pipeline.clip_ring_buffer_seconds == 30
        assert config.pipeline.clip_trigger_kinds == ["rom", "gait"]


# ── VisionProvider ABC contract ─────────────────────────────────────────


class TestVisionProviderCaptionClipAbstract:
    """AC-5: every concrete `VisionProvider` subclass MUST implement
    `caption_clip`. The ABC contract is enforced at instantiation time
    for any subclass that omits it.
    """

    def test_caption_clip_is_abstract(self) -> None:
        # The base class advertises `caption_clip` in __abstractmethods__.
        # Removing it from the ABC would silently let frame-only
        # subclasses ship without clip support.
        assert "caption_clip" in VisionProvider.__abstractmethods__

    def test_subclass_without_caption_clip_cannot_instantiate(self) -> None:
        # Dynamic subclass that omits `caption_clip` — Python's ABC
        # machinery refuses to instantiate it. Proves the abstractmethod
        # is load-bearing.
        class PartialProvider(VisionProvider):
            async def caption_frame(self, frame, anchor):  # type: ignore[override]
                raise NotImplementedError

        with pytest.raises(TypeError):
            PartialProvider()  # type: ignore[abstract]

    def test_subclass_with_both_methods_instantiates(self) -> None:
        class FullProvider(VisionProvider):
            async def caption_frame(self, frame, anchor):  # type: ignore[override]
                raise NotImplementedError

            async def caption_clip(self, clip, anchor):  # type: ignore[override]
                raise NotImplementedError

        # Should not raise.
        FullProvider()


# ── Concrete providers stub `caption_clip` ──────────────────────────────


class TestConcreteProvidersClipStubs:
    """Every concrete provider lands the interface stub. P1-2 ships
    real implementations; today the stubs raise `NotImplementedError`
    so the Stage 2 dispatch can't accidentally call into them without
    failing loudly.
    """

    @pytest.fixture
    def clip(self) -> MaskedClip:
        return MaskedClip(
            s3_key="clips/sess-1/14500.mp4",
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
    def anchor(self) -> TranscriptSegment:
        return TranscriptSegment(
            id="seg_001",
            start_ms=14000,
            end_ms=15000,
            text="abducting the right shoulder",
        )

    @pytest.mark.asyncio
    async def test_openai_raises_not_implemented(self, clip, anchor) -> None:
        with pytest.raises(NotImplementedError, match="P1-2"):
            await OpenAIVisionProvider().caption_clip(clip, anchor)

    @pytest.mark.asyncio
    async def test_anthropic_raises_not_implemented(self, clip, anchor) -> None:
        with pytest.raises(NotImplementedError, match="P1-2"):
            await AnthropicVisionProvider().caption_clip(clip, anchor)

    @pytest.mark.asyncio
    async def test_gemini_raises_not_implemented(self, clip, anchor) -> None:
        with pytest.raises(NotImplementedError, match="P1-2"):
            await GeminiVisionProvider().caption_clip(clip, anchor)


# ── MaskedClip / ClipMaskingMetadata Pydantic ───────────────────────────


class TestMaskedClipValidation:
    """AC-6: the new clip schema validates the documented field set."""

    def test_valid_clip(self) -> None:
        clip = MaskedClip(
            s3_key="clips/sess-1/14500.mp4",
            timestamp_ms=14500,
            duration_ms=7000,
            trigger_segment_id="seg_001",
            masking_metadata=ClipMaskingMetadata(
                frames_total=210,
                frames_with_faces=120,
                faces_blurred=120,
            ),
        )
        assert clip.duration_ms == 7000
        assert clip.masking_metadata.faces_blurred == 120

    def test_negative_duration_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MaskedClip(
                s3_key="clips/sess-1/x.mp4",
                timestamp_ms=0,
                duration_ms=-1,
                trigger_segment_id="seg_001",
                masking_metadata=ClipMaskingMetadata(
                    frames_total=0, frames_with_faces=0, faces_blurred=0
                ),
            )

    def test_negative_face_counts_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ClipMaskingMetadata(
                frames_total=10, frames_with_faces=-1, faces_blurred=0
            )

    def test_required_fields_enforced(self) -> None:
        # Missing trigger_segment_id should fail.
        with pytest.raises(ValidationError):
            MaskedClip(  # type: ignore[call-arg]
                s3_key="x",
                timestamp_ms=0,
                duration_ms=0,
                masking_metadata=ClipMaskingMetadata(
                    frames_total=0, frames_with_faces=0, faces_blurred=0
                ),
            )


# ── FrameCaption backward-compat ────────────────────────────────────────


class TestFrameCaptionAdditiveFields:
    """AC-7: today's call sites stay byte-identical. `evidence_kind`
    defaults to `"frame"` and `duration_ms` defaults to None.
    """

    def test_existing_call_site_unchanged(self) -> None:
        caption = FrameCaption(
            frame_id="frame_001",
            session_id="sess_1",
            timestamp_ms=14500,
            audio_anchor_id="seg_001",
            provider_used="openai",
            visual_description="patient is seated facing the camera",
            confidence="high",
            integration_status="ENRICHES",
        )
        # Defaults preserve frame-only behavior.
        assert caption.evidence_kind == "frame"
        assert caption.duration_ms is None

    def test_clip_caption_carries_kind_and_duration(self) -> None:
        caption = FrameCaption(
            frame_id="clip_001",
            session_id="sess_1",
            timestamp_ms=14500,
            audio_anchor_id="seg_001",
            provider_used="gemini",
            visual_description="patient abducted right shoulder to ~140°",
            confidence="high",
            integration_status="ENRICHES",
            evidence_kind="clip",
            duration_ms=7000,
        )
        assert caption.evidence_kind == "clip"
        assert caption.duration_ms == 7000

    def test_evidence_kind_literal_locked(self) -> None:
        # The Literal type only accepts "frame" or "clip" — invalid
        # values fail at validation time, not silently coerced.
        with pytest.raises(ValidationError):
            FrameCaption(
                frame_id="x",
                session_id="s",
                timestamp_ms=0,
                audio_anchor_id="a",
                provider_used="p",
                visual_description="d",
                confidence="high",
                integration_status="ENRICHES",
                evidence_kind="video",  # type: ignore[arg-type]
            )

    def test_existing_masked_frame_unchanged(self) -> None:
        # MaskedFrame is untouched — proves we didn't accidentally
        # touch the frame upload path.
        frame = MaskedFrame(
            frame_id="f1",
            session_id="s",
            timestamp_ms=0,
            s3_key="frames/s/0.jpg",
        )
        assert frame.masking_confirmed is False


# ── Audit event values + whitelist ──────────────────────────────────────


class TestClipAuditEvents:
    """AC-8: the three new event values match exact strings and have
    whitelist entries so `enforce_audit_kwargs` doesn't warn-loop on
    correctly-named kwargs.
    """

    def test_clip_uploaded_value(self) -> None:
        assert AuditEventType.CLIP_UPLOADED.value == "clip_uploaded"

    def test_clip_masked_value(self) -> None:
        assert AuditEventType.CLIP_MASKED.value == "clip_masked"

    def test_clip_discarded_value(self) -> None:
        assert AuditEventType.CLIP_DISCARDED.value == "clip_discarded"

    def test_clip_events_in_kwarg_whitelist(self) -> None:
        # Every new event must have an explicit whitelist entry; if
        # someone adds the enum member but forgets the whitelist, the
        # Q-03 invariant test (`test_every_audit_event_has_whitelist_entry`)
        # in test_audit_events.py would also fail — this is a focused
        # double-check for the clip events.
        assert AuditEventType.CLIP_UPLOADED in ALLOWED_AUDIT_KWARGS
        assert AuditEventType.CLIP_MASKED in ALLOWED_AUDIT_KWARGS
        assert AuditEventType.CLIP_DISCARDED in ALLOWED_AUDIT_KWARGS

    def test_clip_uploaded_whitelist_includes_masking_proof(self) -> None:
        # Same fields as FRAME_UPLOADED plus the clip-specific extras.
        # The audit row needs masking_status + face counts + duration
        # so the compliance officer can prove 100% on-device masking.
        wl = ALLOWED_AUDIT_KWARGS[AuditEventType.CLIP_UPLOADED]
        assert "masking_status" in wl
        assert "duration_ms" in wl
        assert "trigger_segment_id" in wl
        assert "frames_with_faces" in wl
        assert "faces_blurred" in wl

    def test_clip_masked_whitelist_empty(self) -> None:
        # iOS-emitted, server never writes via write_audit (matches the
        # MASKING_CONFIRMED pattern).
        assert ALLOWED_AUDIT_KWARGS[AuditEventType.CLIP_MASKED] == frozenset()

    def test_clip_discarded_whitelist(self) -> None:
        wl = ALLOWED_AUDIT_KWARGS[AuditEventType.CLIP_DISCARDED]
        assert "s3_key" in wl
        assert "confidence" in wl


# ── Sanity: FrameCaption literal options stay locked ───────────────────


def test_frame_caption_evidence_kind_literal_options() -> None:
    """If someone adds a third evidence kind without consciously updating
    every dispatch site, this fails loudly."""
    field = FrameCaption.model_fields["evidence_kind"]
    assert set(get_args(field.annotation)) == {"frame", "clip"}
