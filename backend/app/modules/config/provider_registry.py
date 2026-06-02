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

    def get_transcription_provider(
        self, override: Optional[str] = None
    ) -> TranscriptionProvider:
        config = get_config()
        # Precedence: per-call override > DB override store > AppConfig.
        if override:
            key = TranscriptionProviderKey(override)
        elif (store := get_override("transcription")) is not None:
            key = TranscriptionProviderKey(store)
            logger.info(
                "transcription provider overridden via admin store: %s", key.value
            )
        else:
            key = config.providers.transcription
        cls = _TRANSCRIPTION_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No transcription provider registered for key: {key}")
        logger.info("Resolved transcription provider: %s", key.value)
        return cls()

    def get_note_provider(
        self, override: Optional[str] = None
    ) -> NoteGenerationProvider:
        config = get_config()
        # Precedence: per-call override > DB override store > AppConfig.
        if override:
            key = NoteGenerationProviderKey(override)
        elif (store := get_override("note_generation")) is not None:
            key = NoteGenerationProviderKey(store)
            logger.info(
                "note_generation provider overridden via admin store: %s", key.value
            )
        else:
            key = config.providers.note_generation
        cls = _NOTE_GEN_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No note generation provider registered for key: {key}")
        logger.info("Resolved note generation provider: %s", key.value)
        return cls()

    def get_vision_provider(
        self, override: Optional[str] = None
    ) -> VisionProvider:
        config = get_config()
        # Precedence: per-call override > DB override store > AppConfig.
        if override:
            key = VisionProviderKey(override)
        elif (store := get_override("vision")) is not None:
            key = VisionProviderKey(store)
            logger.info(
                "vision provider overridden via admin store: %s", key.value
            )
        else:
            key = config.providers.vision
        cls = _VISION_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No vision provider registered for key: {key}")
        logger.info("Resolved vision provider: %s", key.value)
        return cls()

    def get_note_provider_with_fallback(self) -> NoteGenerationProvider:
        """Try the configured provider first, then fall back through the ordered list.

        The DB override store (if set) takes precedence over AppConfig as
        the primary, matching :meth:`get_note_provider`'s precedence; the
        ordered fallback list still applies if the primary is unavailable.
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
        order = [primary] + [k for k in _NOTE_GEN_FALLBACK_ORDER if k != primary]

        for key in order:
            cls = _NOTE_GEN_PROVIDERS.get(key)
            if cls:
                if key != primary:
                    logger.warning("Falling back to note provider: %s", key.value)
                return cls()

        raise ProviderError("note_generation", "All note generation providers unavailable")

    def get_vision_provider_with_fallback(self) -> VisionProvider:
        """Try the configured provider first, then fall back through the ordered list."""
        config = get_config()
        primary = config.providers.vision
        order = [primary] + [k for k in _VISION_FALLBACK_ORDER if k != primary]

        for key in order:
            cls = _VISION_PROVIDERS.get(key)
            if cls:
                if key != primary:
                    logger.warning("Falling back to vision provider: %s", key.value)
                return cls()

        raise ProviderError("vision", "All vision providers unavailable")

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

    def get_vision_provider_for_kind(
        self, kind: str, override: Optional[str] = None
    ) -> VisionProvider:
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
        raise ProviderError(
            "vision_kind", f"Unknown visual evidence kind: {kind!r}"
        )

    def get_vision_provider_for_kind_with_fallback(self, kind: str) -> VisionProvider:
        """Try the kind-specific primary first, then fall back through
        the ordered list.

        Same fallback chain as `get_vision_provider_with_fallback` for
        either kind — OpenAI/Anthropic implement `caption_clip` via the
        midpoint-still extraction so the chain stays evidence-kind-
        agnostic at the abstract-method level (LSP).
        """
        config = get_config()
        if kind == "clip":
            primary = config.providers.vision_clip
        elif kind == "frame":
            primary = config.providers.vision
        else:
            raise ProviderError(
                "vision_kind", f"Unknown visual evidence kind: {kind!r}"
            )

        order = [primary] + [k for k in _VISION_FALLBACK_ORDER if k != primary]
        for key in order:
            cls = _VISION_PROVIDERS.get(key)
            if cls:
                if key != primary:
                    logger.warning(
                        "Falling back to vision provider (kind=%s): %s",
                        kind, key.value,
                    )
                return cls()
        raise ProviderError("vision", "All vision providers unavailable")


# ── Module-level singleton ─────────────────────────────────────────────────

_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
