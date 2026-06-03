"""AI Prompts transparency registry.

A single source-of-truth catalog of every LLM system prompt the
encounter-analysis pipeline uses. Powers the read-only
``/portal/prompts`` Transparency page in the web portal.

The registry IMPORTS the existing prompt constants from their
provider / service modules — it never copies the text. That keeps
the displayed text exactly identical to what the LLM actually
receives, and means a future change to a prompt automatically
flows to the Transparency page without a sync step.

Phase A is read-only. The response schema carries forward-compatible
``override_text`` / ``is_overridden`` fields (currently ``None`` /
``False``) so Phase B can add per-physician overlays without a
breaking change.
"""

from app.modules.prompts.registry import PROMPTS, PromptDefinition

__all__ = ["PROMPTS", "PromptDefinition"]
