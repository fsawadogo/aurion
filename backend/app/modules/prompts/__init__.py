"""AI Prompts transparency registry + per-physician overlay assembly.

A single source-of-truth catalog of every LLM system prompt the
encounter-analysis pipeline uses, plus the append-only overlay
machinery that lets a physician customise each prompt without
modifying the descriptive-mode base.

The registry IMPORTS the existing prompt constants from their
provider / service modules — it never copies the text. That keeps the
displayed text exactly identical to what the LLM actually receives,
and means a future change to a prompt automatically flows to the
Transparency page without a sync step.

Phase A (read-only) shipped first. Phase B (AI-PROMPTS-B) added:

  * ``PromptOverrideModel`` row per (owner_id, prompt_id)
  * :func:`assemble_prompt` — the single DRY function every consumer
    site calls to get the physician-customized prompt text
  * :func:`validate_overlay` — the structural safety check the API
    layer runs before saving a new overlay

The base prompt is NEVER modified at runtime. Overlay text is
appended below a clear separator at assembly time.
"""

from app.modules.prompts.assembly import (
    OVERLAY_SEPARATOR,
    assemble_preview,
    assemble_prompt,
)
from app.modules.prompts.registry import PROMPTS, PromptDefinition
from app.modules.prompts.safety import (
    BANNED_PHRASES,
    OVERLAY_MAX_LENGTH,
    ValidationCode,
    ValidationResult,
    validate_overlay,
)

__all__ = [
    "PROMPTS",
    "PromptDefinition",
    "BANNED_PHRASES",
    "OVERLAY_MAX_LENGTH",
    "OVERLAY_SEPARATOR",
    "ValidationCode",
    "ValidationResult",
    "assemble_preview",
    "assemble_prompt",
    "validate_overlay",
]
