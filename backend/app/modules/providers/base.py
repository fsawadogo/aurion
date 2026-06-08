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
    MaskedClip,
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
        system_prompt: str | None = None,
        prior_context_text: str | None = None,
        participants: list[dict] | None = None,
    ) -> Note:
        """Generate a structured SOAP note from a transcript and template.

        ``output_language`` (e.g. "en", "fr") selects the language of the
        generated note content. Defaults to English.

        ``system_prompt`` (AI-PROMPTS-B) — when set, used as the system
        instruction instead of the provider's default ``NOTE_GEN_SYSTEM_PROMPT``
        constant. The service layer selects either the calling
        physician's saved user prompt (replacement) or the registry
        default via :func:`app.modules.prompts.assemble_prompt` and
        passes it down so providers stay stateless and DB-free. ``None``
        preserves the pre-Phase-B behaviour for callers that don't (yet)
        need per-physician customisation. Liskov: additive optional kwarg.

        ``prior_context_text`` (#61, full slice) — when set, the
        deterministic block produced by
        :func:`app.modules.longitudinal_context.render_prior_context_block`
        is appended to the USER message just above the transcript.
        Empty / ``None`` skips the prior-context section entirely so
        cold-start sessions render unchanged. Additive optional kwarg
        on the base — every concrete provider forwards it into
        ``build_user_prompt``.

        ``participants`` (#275) — encounter participant chips
        ({name, role, source, is_persistent}). When non-empty an
        ENCOUNTER PARTICIPANTS block is rendered into the user prompt so
        the model can attribute statements by role/name. ``None`` / empty
        renders unchanged. Additive optional kwarg; every concrete
        provider forwards it into ``build_user_prompt``.
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
        self,
        frame: MaskedFrame,
        anchor: TranscriptSegment,
        system_prompt: str | None = None,
    ) -> FrameCaption:
        """Generate a descriptive caption for a masked clinical frame.

        ``system_prompt`` (AI-PROMPTS-B) — when set, used as the system
        instruction instead of the default ``VISION_SYSTEM_PROMPT``
        constant. ``None`` preserves the pre-Phase-B behaviour. Liskov:
        additive optional kwarg, same semantic as NoteGenerationProvider.
        """
        ...

    @abstractmethod
    async def caption_clip(
        self,
        clip: MaskedClip,
        anchor: TranscriptSegment,
        system_prompt: str | None = None,
    ) -> FrameCaption:
        """Generate a descriptive caption for a masked clinical clip.

        Dual-mode visual evidence (see docs/plans/p1-1-clip-evidence-schema.md).
        Every concrete subclass MUST implement this — even frame-only
        providers, which fall back to extracting a representative still
        and calling `caption_frame` under the hood (P1-2, tagged with
        `degraded_to_frame=true` on the citation). Native-video providers
        (Gemini today, others as they ship) send the actual MP4 bytes.

        Liskov: the return type is `FrameCaption` (same as `caption_frame`)
        so the Stage 2 dispatch and conflict-detection logic stays
        evidence-kind-agnostic. The returned caption's `evidence_kind`
        field is `"clip"` and `duration_ms` is the clip window.

        This is the interface only; concrete implementations land in P1-2.
        Subclasses in this PR raise `NotImplementedError` so the abstract
        contract is enforced today and the real plumbing layers on next.
        """
        ...
