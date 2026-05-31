"""Abstract provider interfaces.

The application never calls any AI model directly — always through
these interfaces via the provider registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from app.core.types import (
    FrameCaption,
    MaskedFrame,
    Note,
    Template,
    Transcript,
    TranscriptSegment,
)


@dataclass(frozen=True)
class ChatMessage:
    """One turn in a structural chat (template authoring, etc.).

    Kept deliberately minimal — `role` + `content`, no tool calls, no
    function results. Anything richer should live in a dedicated
    provider method, not on this base type.
    """

    role: Literal["user", "assistant"]
    content: str


class TranscriptionProvider(ABC):
    """Abstract interface for transcription providers (Whisper, AssemblyAI)."""

    @abstractmethod
    async def transcribe(self, audio: bytes, session_id: str) -> Transcript:
        """Transcribe audio bytes into a timestamped transcript."""
        ...


class NoteGenerationProvider(ABC):
    """Abstract interface for note generation providers (OpenAI, Anthropic, Gemini)."""

    @abstractmethod
    async def generate_note(
        self,
        transcript: Transcript,
        template: Template,
        stage: int,
        output_language: str = "en",
    ) -> Note:
        """Generate a structured SOAP note from a transcript and template.

        ``output_language`` (e.g. "en", "fr") selects the language of the
        generated note content. Defaults to English.
        """
        ...

    async def generate_text(
        self, system: str, messages: list[ChatMessage]
    ) -> str:
        """Open-ended text generation for non-clinical structural use cases.

        Today's only caller is the conversational template authoring
        service (`modules/template_authoring/service.py`), where the
        physician chats with the LLM to design a custom specialty
        template and we need plain text replies plus fenced-JSON drafts.

        Implemented optionally on the same provider class that
        implements `generate_note` so the registry's note_generation
        switch (AppConfig / per-call override) routes both. Subclasses
        that don't implement it raise NotImplementedError; callers
        should fall back or surface a 503.

        ``system`` is the system prompt (no descriptive-mode rules apply
        — this path is structural, not clinical). ``messages`` is the
        running conversation history; the provider must preserve order
        and not collapse adjacent same-role turns.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement generate_text"
        )


class VisionProvider(ABC):
    """Abstract interface for vision providers (OpenAI, Anthropic, Gemini)."""

    @abstractmethod
    async def caption_frame(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> FrameCaption:
        """Generate a descriptive caption for a masked clinical frame."""
        ...
