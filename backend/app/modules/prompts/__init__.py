"""AI Prompts transparency registry + per-physician user-prompt selection.

A single source-of-truth catalog of every LLM system prompt the
encounter-analysis pipeline uses, plus the per-physician REPLACEMENT
machinery that lets a clinician save their own full prompt that
overrides the registry's default for their own sessions.

The registry IMPORTS the existing prompt constants from their
provider / service modules — it never copies the text. That keeps the
displayed text exactly identical to what the LLM actually receives,
and means a future change to a prompt automatically flows to the
Transparency page without a sync step.

Phase B (AI-PROMPTS-B), refactored to **replacement** semantics:

  * ``PromptOverrideModel`` row per ``(owner_id, prompt_id)`` stores
    the clinician's full standalone prompt as ``user_prompt_text``.
  * :func:`assemble_prompt` selects the user prompt when set, or the
    registry default as the fallback when not. **No concatenation.**
  * :func:`validate_user_prompt` is the structural safety gate the API
    layer runs before saving — banlist, 5000-char cap, AND required
    descriptive-mode anchor presence (so the descriptive-mode boundary
    survives replacement).
"""

from app.modules.prompts.assembly import (
    assemble_prompt,
    assemble_prompt_for_session,
    select_active_prompt,
)
from app.modules.prompts.registry import PROMPTS, PromptDefinition
from app.modules.prompts.safety import (
    BANNED_PHRASES,
    DESCRIPTIVE_ANCHORS_REQUIRED,
    USER_PROMPT_MAX_LENGTH,
    ValidationCode,
    ValidationResult,
    validate_user_prompt,
)

__all__ = [
    "PROMPTS",
    "PromptDefinition",
    "BANNED_PHRASES",
    "DESCRIPTIVE_ANCHORS_REQUIRED",
    "USER_PROMPT_MAX_LENGTH",
    "ValidationCode",
    "ValidationResult",
    "assemble_prompt",
    "assemble_prompt_for_session",
    "select_active_prompt",
    "validate_user_prompt",
]
