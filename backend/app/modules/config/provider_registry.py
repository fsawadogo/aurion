"""Provider registry — maps config keys to provider implementations.

The application never instantiates providers directly. Always call
registry.get_*_provider() to get the active implementation.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.types import ProviderError
from app.modules.config.appconfig_client import get_config
from app.modules.config.provider_overrides import get_override
from app.modules.config.schema import (
    NoteGenerationProviderKey,
    TranscriptionProviderKey,
    VisionProviderKey,
)
from app.modules.providers.base import (
    NoteGenerationProvider,
    TranscriptionProvider,
    VisionProvider,
)

# ── Note generation providers ──────────────────────────────────────────────
from app.modules.providers.note_gen.anthropic import (
    AnthropicNoteGenerationProvider,
)
from app.modules.providers.note_gen.gemini import (
    GeminiNoteGenerationProvider,
)
from app.modules.providers.note_gen.openai import (
    OpenAINoteGenerationProvider,
)

# ── Transcription providers ────────────────────────────────────────────────
from app.modules.providers.transcription.assemblyai import (
    AssemblyAITranscriptionProvider,
)
from app.modules.providers.transcription.whisper import (
    WhisperTranscriptionProvider,
)

# ── Vision providers ───────────────────────────────────────────────────────
from app.modules.providers.vision.anthropic import AnthropicVisionProvider
from app.modules.providers.vision.gemini import GeminiVisionProvider
from app.modules.providers.vision.openai import OpenAIVisionProvider

logger = logging.getLogger("aurion.registry")

# ── Provider Maps ──────────────────────────────────────────────────────────

_TRANSCRIPTION_PROVIDERS: dict[TranscriptionProviderKey, type[TranscriptionProvider]] = {
    TranscriptionProviderKey.WHISPER: WhisperTranscriptionProvider,
    TranscriptionProviderKey.ASSEMBLYAI: AssemblyAITranscriptionProvider,
}

_NOTE_GEN_PROVIDERS: dict[NoteGenerationProviderKey, type[NoteGenerationProvider]] = {
    NoteGenerationProviderKey.OPENAI: OpenAINoteGenerationProvider,
    NoteGenerationProviderKey.ANTHROPIC: AnthropicNoteGenerationProvider,
    NoteGenerationProviderKey.GEMINI: GeminiNoteGenerationProvider,
}

_VISION_PROVIDERS: dict[VisionProviderKey, type[VisionProvider]] = {
    VisionProviderKey.OPENAI: OpenAIVisionProvider,
    VisionProviderKey.ANTHROPIC: AnthropicVisionProvider,
    VisionProviderKey.GEMINI: GeminiVisionProvider,
}

# ── Fallback Order ─────────────────────────────────────────────────────────

_NOTE_GEN_FALLBACK_ORDER: list[NoteGenerationProviderKey] = [
    NoteGenerationProviderKey.ANTHROPIC,
    NoteGenerationProviderKey.OPENAI,
    NoteGenerationProviderKey.GEMINI,
]

_VISION_FALLBACK_ORDER: list[VisionProviderKey] = [
    VisionProviderKey.OPENAI,
    VisionProviderKey.ANTHROPIC,
    VisionProviderKey.GEMINI,
]


# ── Registry ───────────────────────────────────────────────────────────────


class ProviderRegistry:
    """Maps AppConfig provider keys to implementations.

    Reads the current config on every call — picks up AppConfig changes
    without restart.
    """

    def get_transcription_provider(self, override: Optional[str] = None) -> TranscriptionProvider:
        config = get_config()
        # Precedence: per-call override > DB override store > AppConfig.
        if override:
            key = TranscriptionProviderKey(override)
        elif (store := get_override("transcription")) is not None:
            key = TranscriptionProviderKey(store)
            logger.info("transcription provider overridden via admin store: %s", key.value)
        else:
            key = config.providers.transcription
        cls = _TRANSCRIPTION_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No transcription provider registered for key: {key}")
        logger.info("Resolved transcription provider: %s", key.value)
        return cls()

    def get_note_provider(self, override: Optional[str] = None) -> NoteGenerationProvider:
        config = get_config()
        # Precedence: per-call override > DB override store > AppConfig.
        if override:
            key = NoteGenerationProviderKey(override)
        elif (store := get_override("note_generation")) is not None:
            key = NoteGenerationProviderKey(store)
            logger.info("note_generation provider overridden via admin store: %s", key.value)
        else:
            key = config.providers.note_generation
        cls = _NOTE_GEN_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No note generation provider registered for key: {key}")
        logger.info("Resolved note generation provider: %s", key.value)
        return cls()

    def get_vision_provider(self, override: Optional[str] = None) -> VisionProvider:
        config = get_config()
        # Precedence: per-call override > DB override store > AppConfig.
        if override:
            key = VisionProviderKey(override)
        elif (store := get_override("vision")) is not None:
            key = VisionProviderKey(store)
            logger.info("vision provider overridden via admin store: %s", key.value)
        else:
            key = config.providers.vision
        cls = _VISION_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No vision provider registered for key: {key}")
        logger.info("Resolved vision provider: %s", key.value)
        return cls()

    def get_note_provider_chain(self) -> list[NoteGenerationProvider]:
        """Return the ordered, duplicate-free note-provider chain.

        The DB override store (if set) takes precedence over AppConfig as
        the primary, matching :meth:`get_note_provider`'s precedence.
        Mirrors :meth:`get_vision_provider_chain_for_kind`: returning the
        whole chain lets the caller advance to the next distinct provider
        after a runtime ``ProviderError`` instead of resolving the same
        configured primary again.
        """
        config = get_config()
        if (store := get_override("note_generation")) is not None:
            primary = NoteGenerationProviderKey(store)
            logger.info(
                "note_generation provider overridden via admin store: %s",
                primary.value,
            )
        else:
            primary = config.providers.note_generation
        order = list(dict.fromkeys([primary, *_NOTE_GEN_FALLBACK_ORDER]))
        providers: list[NoteGenerationProvider] = []
        for key in order:
            provider_class = _NOTE_GEN_PROVIDERS.get(key)
            if provider_class is not None:
                providers.append(provider_class())
        if not providers:
            raise ProviderError("note_generation", "All note generation providers unavailable")
        return providers

    def get_note_provider_with_fallback(self) -> NoteGenerationProvider:
        """Return the first provider in the ordered note-provider chain.

        Kept for callers that only need the resolved primary. Runtime
        fallback belongs to the caller: use :meth:`get_note_provider_chain`
        when a provider error needs to advance to the next distinct
        implementation — the old behaviour of calling this method again
        after a failure just re-resolved the same configured primary.
        """
        return self.get_note_provider_chain()[0]

    def get_vision_provider_with_fallback(self) -> VisionProvider:
        """Return the first provider in the ordered frame-provider chain.

        Kept for backward compatibility with frame-only call sites. Runtime
        fallback belongs to the caller: use
        :meth:`get_vision_provider_chain_for_kind` when provider errors need to
        advance to the next distinct implementation.
        """
        return self.get_vision_provider_chain_for_kind("frame")[0]

    # ── Dual-mode visual evidence (P1-3) ──────────────────────────────────
    #
    # The Stage 2 dispatcher routes per-evidence by `evidence_kind`. Frame
    # evidence keeps the existing `config.providers.vision` resolution;
    # clip evidence resolves through `config.providers.vision_clip`
    # (defaults to Gemini, the only native-video model today). Both kinds
    # share the same fallback chain — if the clip-primary is unavailable
    # we still fall through to OpenAI/Anthropic, which implement
    # `caption_clip` via midpoint-still extraction (P1-2,
    # `degraded_to_frame=True` on the citation).
    #
    # OCP: adding a new evidence kind in the future doesn't mean a new
    # method on the registry — extend `_VISION_KIND_CONFIG` to map the
    # new kind to the right config attribute. The dispatch in
    # `vision/service.py` keeps a single switch on `evidence_kind`.

    def get_vision_provider_for_kind(self, kind: str, override: Optional[str] = None) -> VisionProvider:
        """Resolve the active vision provider for an evidence kind.

        `kind="frame"` reads `config.providers.vision`; `kind="clip"`
        reads `config.providers.vision_clip`. Anything else raises
        `ProviderError("vision_kind", ...)`.

        Mirrors `get_vision_provider`'s override + DB-store precedence
        for the frame kind (the existing override store applies to
        frames-only — clip overrides are a follow-up if the eval team
        ever needs them; for the pilot, AppConfig is the only knob).
        """
        if kind == "frame":
            return self.get_vision_provider(override=override)
        if kind == "clip":
            config = get_config()
            if override:
                key = VisionProviderKey(override)
            else:
                key = config.providers.vision_clip
            cls = _VISION_PROVIDERS.get(key)
            if not cls:
                raise ProviderError(
                    key.value,
                    f"No vision provider registered for clip key: {key}",
                )
            logger.info("Resolved vision_clip provider: %s", key.value)
            return cls()
        raise ProviderError("vision_kind", f"Unknown visual evidence kind: {kind!r}")

    def get_vision_provider_chain_for_kind(self, kind: str, override: Optional[str] = None) -> list[VisionProvider]:
        """Return the ordered, duplicate-free provider chain for ``kind``.

        Primary precedence is explicit per-call override, then the admin
        override store for frame evidence, then the kind-specific AppConfig
        value. Clip evidence intentionally has no admin-store key today and
        therefore resolves from ``providers.vision_clip`` when no explicit
        override is supplied.

        Returning the whole chain lets callers advance after a provider error
        without resolving the same configured primary again. OpenAI and
        Anthropic implement ``caption_clip`` through midpoint-still
        degradation, so this chain is valid for both evidence kinds.
        """
        config = get_config()
        if kind not in {"frame", "clip"}:
            raise ProviderError("vision_kind", f"Unknown visual evidence kind: {kind!r}")
        if override:
            primary = VisionProviderKey(override)
        elif kind == "clip":
            primary = config.providers.vision_clip
        else:
            if (store := get_override("vision")) is not None:
                primary = VisionProviderKey(store)
                logger.info(
                    "vision provider overridden via admin store: %s",
                    primary.value,
                )
            else:
                primary = config.providers.vision

        order = list(dict.fromkeys([primary, *_VISION_FALLBACK_ORDER]))
        providers: list[VisionProvider] = []
        for key in order:
            provider_class = _VISION_PROVIDERS.get(key)
            if provider_class is not None:
                providers.append(provider_class())
        if not providers:
            raise ProviderError("vision", "All vision providers unavailable")
        return providers

    def get_vision_provider_for_kind_with_fallback(self, kind: str, override: Optional[str] = None) -> VisionProvider:
        """Return the first provider from the kind-specific ordered chain.

        Same fallback chain as `get_vision_provider_with_fallback` for
        either kind — OpenAI/Anthropic implement `caption_clip` via the
        midpoint-still extraction so the chain stays evidence-kind-
        agnostic at the abstract-method level (LSP).
        """
        return self.get_vision_provider_chain_for_kind(kind, override=override)[0]


# ── Module-level singleton ─────────────────────────────────────────────────

_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
