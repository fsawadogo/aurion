"""Provider registry — maps config keys to provider implementations.

The application never instantiates providers directly. Always call
registry.get_*_provider() to get the active implementation.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.core.types import ProviderError
from app.modules.config.appconfig_client import get_config
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

# ── Transcription providers ────────────────────────────────────────────────
from app.modules.providers.transcription.assemblyai import (
    AssemblyAITranscriptionProvider,
)
from app.modules.providers.transcription.whisper import (
    WhisperTranscriptionProvider,
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
        key = TranscriptionProviderKey(override) if override else config.providers.transcription
        cls = _TRANSCRIPTION_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No transcription provider registered for key: {key}")
        logger.info("Resolved transcription provider: %s", key.value)
        return cls()

    def get_note_provider(
        self, override: Optional[str] = None
    ) -> NoteGenerationProvider:
        config = get_config()
        key = NoteGenerationProviderKey(override) if override else config.providers.note_generation
        cls = _NOTE_GEN_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No note generation provider registered for key: {key}")
        logger.info("Resolved note generation provider: %s", key.value)
        return cls()

    def get_vision_provider(
        self, override: Optional[str] = None
    ) -> VisionProvider:
        config = get_config()
        key = VisionProviderKey(override) if override else config.providers.vision
        cls = _VISION_PROVIDERS.get(key)
        if not cls:
            raise ProviderError(key.value, f"No vision provider registered for key: {key}")
        logger.info("Resolved vision provider: %s", key.value)
        return cls()

    def get_note_provider_with_fallback(self) -> NoteGenerationProvider:
        """Try the configured provider first, then fall back through the ordered list."""
        config = get_config()
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


# ── Module-level singleton ─────────────────────────────────────────────────

_registry: Optional[ProviderRegistry] = None


def get_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        _registry = ProviderRegistry()
    return _registry
