"""Longitudinal patient context for Stage 1 note generation.

The rail on iOS NoteReviewView and the patient detail page on the web
portal already show physicians their prior visits with the same
identifier. This module is the **note-gen-time** counterpart: it builds
a small text block describing the last N encounters that goes INTO the
LLM call, so the generated note can reference prior visits factually
("patient reports continued pain since visit on 2026-05-14") instead of
being written cold.

See ``service.py`` for the public API surface. ``models.py`` holds the
shared dataclasses used by both this module and ``note_gen`` for the
rendered block.
"""

from app.modules.longitudinal_context.models import (
    PriorContextBlock,
    PriorContextUsed,
    PriorEncounterSummary,
)
from app.modules.longitudinal_context.service import (
    get_prior_context,
    render_prior_context_block,
)

__all__ = [
    "PriorContextBlock",
    "PriorContextUsed",
    "PriorEncounterSummary",
    "get_prior_context",
    "render_prior_context_block",
]
