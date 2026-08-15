"""Shared logic for vision providers.

All three vision providers (OpenAI, Anthropic, Gemini) use the same system
prompt and build FrameCaption objects the same way.  Provider-specific code
is limited to the HTTP call and response extraction.
"""

from __future__ import annotations

import json
import logging
from typing import Final

from app.core.types import FrameCaption, MaskedFrame, ProviderError, TranscriptSegment

logger = logging.getLogger("aurion.providers.vision.shared")

# Truncated excerpt length for the WARNING log emitted when a provider
# response fails to parse as JSON. Vision responses are model-generated
# descriptive text per VISION_SYSTEM_PROMPT — not user content / PHI —
# but defensively bounded so a runaway provider response can't bloat
# the log line and so we don't accidentally surface a longer suffix
# that could carry a malformed `?key=...` URL fragment.
_PARSE_FAILURE_LOG_LEN: Final[int] = 120

# JSON Schema for the vision caption response. Used by providers that
# support schema-enforced output (Anthropic tool_use, Gemini
# responseSchema). The integration_status is NOT in the schema — that
# field is computed downstream in vision/service.py classify_captions;
# the LLM just describes what it sees.
VISION_RESPONSE_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
        },
        "confidence_reason": {"type": "string"},
    },
    "required": ["description", "confidence", "confidence_reason"],
}


# Vision system prompt from CLAUDE.md. Shared across all vision providers and
# BOTH evidence kinds (still frames and video clips), so it is modality-neutral:
# "what is literally visible" (matching CLAUDE.md's canonical wording) rather
# than "in this image", which mislabeled video clips. The clip path additionally
# tells the model it's a video clip and to describe motion via the user message;
# for native-video providers (Gemini) that's where the temporal framing lives.
VISION_SYSTEM_PROMPT = """You are a clinical visual documentation assistant. Describe only what is literally visible. Do not diagnose, interpret, or infer clinical meaning.

Describe: patient position, visible body parts being examined, observable physical findings (swelling, redness, range of motion if measurable), equipment in use, screen content.
Do not describe: clinical meaning, what findings suggest, what should be done, anything not directly visible.
Do not describe the room, furniture, flooring, walls, doors, clothing, footwear or nail varnish. They are not clinical findings, and they bury the observation that matters. Write the clinical observation and stop.
Name an object only if you can actually see it and it bears on the encounter. If you cannot tell what something is, leave it out — do not guess a plausible clinical object. Do not state which side of the body is shown unless a marker in the frame (an "R"/"L" on a radiograph, a label) says so; a camera worn by the clinician cannot establish laterality.

Return JSON only: {"description": "...", "confidence": "high|medium|low", "confidence_reason": "..."}
Confidence is LOW if: blurry, wrong angle, subject not clearly visible, no clinically relevant content visible."""


# Grounded visual-findings variant (grounded_visual_findings_enabled ON).
# Shifts the vision layer from pure description to the clinical finding the
# visible evidence supports — so a silent physical exam produces exam findings
# instead of literal-motion descriptions. Grounding is STRUCTURAL: the caption
# becomes a claim with source_id=frame_id (see vision/service._build_visual_
# claim), so every finding is cited to the frame it rests on. The prompt's job
# is to keep the finding WITHIN what the frame can support — characterise what
# is visible clinically, never leap to a diagnosis the image can't establish.
# Selected in place of VISION_SYSTEM_PROMPT at the single per-run site in
# run_stage2_vision; per-physician prompt overrides still win over both.
VISION_GROUNDED_SYSTEM_PROMPT = """You are a clinical visual documentation assistant. State the clinical finding that the visible evidence directly supports. Ground every finding in what is actually visible — never assert a diagnosis, measurement, or finding the frame cannot establish.

Report, when visible: the physical-exam finding being demonstrated (e.g. reduced range of motion and the approximate degree reached, joint swelling, an antalgic or altered gait, wound appearance — erythema, dehiscence, approximation), what is on an imaging or monitor screen, equipment in use. State the finding a clinician would read from the image, in clinical terms.
Do not: assert a diagnosis the image cannot establish (a visibly limited knee flexion is a finding; "ACL tear" is not), invent a precise measurement the frame does not show, or describe anything not directly visible. When the evidence is ambiguous, describe what is visible and mark confidence accordingly rather than guessing a finding.
Do not describe the room, furniture, flooring, walls, doors, clothing, footwear or nail varnish — they are not clinical findings. Name an object only if you can actually see it and it bears on the encounter; if you cannot tell what something is, leave it out rather than guessing a plausible clinical object. Do not state which side of the body is shown unless a marker in the frame says so.

Return JSON only: {"description": "...", "confidence": "high|medium|low", "confidence_reason": "..."}
Confidence is LOW if: blurry, wrong angle, subject not clearly visible, or no clinically relevant finding is visible."""


def parse_caption_json(provider_name: str, raw: str) -> dict:
    """Parse a provider's JSON response, raising ProviderError on failure.

    Catches ``json.JSONDecodeError`` (a ``ValueError`` subclass) and
    re-raises as ``ProviderError(provider_name, ...)`` so the registry's
    fallback chain in :func:`get_vision_provider_with_fallback` can trip
    cleanly. Without this wrapper, a truncated / malformed provider
    response leaks as a bare ``ValueError`` past the provider boundary —
    the Stage 2 dispatcher and the admin probe both classify that as a
    generic Python error rather than a provider failure, and the
    fallback chain never gets a turn.

    LSP boundary: every vision provider now emits the same error
    semantic on a malformed wire response, regardless of which SDK / API
    shape they're parsing.

    No PHI / no API keys are logged. The 120-char excerpt is the
    provider's own response (descriptive text generated by the model
    per ``VISION_SYSTEM_PROMPT``), not user content; defensively
    truncated so a runaway response can't bloat the log line and can't
    surface a malformed URL fragment past the cap.

    Args:
        provider_name: short provider identifier — ``"openai"``,
            ``"anthropic"``, ``"gemini"``. Used both as the
            ``ProviderError`` provider tag and as a label in the
            WARNING log.
        raw: the provider's response text, before any whitespace
            stripping. The helper does the strip itself so callers
            don't accidentally strip-and-pass a different shape.

    Returns:
        The parsed JSON object as a ``dict``.

    Raises:
        ProviderError: if the response is not valid JSON. The original
            ``json.JSONDecodeError`` is chained via ``raise ... from``
            for debugging.
    """
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        excerpt = raw[:_PARSE_FAILURE_LOG_LEN]
        logger.warning(
            "vision provider response JSON parse failed: provider=%s "
            "error=%s excerpt=%r",
            provider_name,
            type(exc).__name__,
            excerpt,
        )
        raise ProviderError(
            provider_name,
            f"response JSON parse failed: {type(exc).__name__}",
        ) from exc


def build_frame_caption(
    frame: MaskedFrame,
    anchor: TranscriptSegment,
    content: dict,
    provider_name: str,
) -> FrameCaption:
    """Build a FrameCaption from the parsed LLM response.

    All vision providers return the same caption structure -- only the
    ``provider_used`` field differs.
    """
    return FrameCaption(
        frame_id=frame.frame_id,
        session_id=frame.session_id,
        timestamp_ms=frame.timestamp_ms,
        audio_anchor_id=anchor.id,
        provider_used=provider_name,
        visual_description=content.get("description", ""),
        confidence=content.get("confidence", "medium"),
        confidence_reason=content.get("confidence_reason", ""),
        conflict_flag=False,
        conflict_detail=None,
        integration_status="ENRICHES",
    )
