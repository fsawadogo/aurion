"""Note-completeness fix: the Stage-1 user prompt pushes exhaustive capture, and
the note-gen ``max_tokens`` fallback default has headroom for a full note.

The thin-note failure mode was the model summarizing the encounter (and, at the
old 2000-token fallback, risking truncation of a genuinely complete note). This
locks in the directive + the raised default so a regression is caught.
"""

from __future__ import annotations

import uuid

from app.core.types import (
    Template,
    TemplateSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.config.schema import NoteGenerationModelParams
from app.modules.providers.note_gen.shared import build_user_prompt


def _transcript() -> Transcript:
    return Transcript(
        session_id=str(uuid.uuid4()),
        provider_used="whisper",
        segments=[
            TranscriptSegment(id="seg_000", start_ms=0, end_ms=1000, text="hi"),
        ],
    )


def _template() -> Template:
    return Template(
        key="general",
        display_name="General",
        version="1.0",
        sections=[TemplateSection(id="hpi", title="HPI")],
    )


def test_user_prompt_demands_exhaustive_capture() -> None:
    prompt = build_user_prompt(_transcript(), _template(), stage=1)
    # The completeness directive must reach the model so it doesn't summarize
    # the encounter down to a handful of claims.
    assert "capture EVERY distinct point" in prompt
    assert "not a handful" in prompt


def test_note_gen_max_tokens_default_has_headroom() -> None:
    # The .env fallback default; the live value comes from AppConfig. 4000 gives
    # an exhaustive consult note room to land without truncation.
    assert NoteGenerationModelParams().max_tokens == 4000
