"""Abstract provider interfaces.

The application never calls any AI model directly — always through
these interfaces via the provider registry.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.core.types import (
    FrameCaption,
    MaskedFrame,
    Note,
    Template,
    Transcript,
    TranscriptSegment,
)


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


class VisionProvider(ABC):
    """Abstract interface for vision providers (OpenAI, Anthropic, Gemini)."""

    @abstractmethod
    async def caption_frame(
        self, frame: MaskedFrame, anchor: TranscriptSegment
    ) -> FrameCaption:
        """Generate a descriptive caption for a masked clinical frame."""
        ...
