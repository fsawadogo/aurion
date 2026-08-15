"""The vision prompt's descriptive-mode guardrails, pinned.

CLAUDE.md publishes this prompt under "System Prompts — Use Exactly These", so
the wording is a spec artefact, not an implementation detail. These tests pin
the constraints that were added after session `f3a8e35d` and keep the code and
the spec from silently diverging on them.

What the captions actually did on that session, against a video I watched
frame-by-frame to check:

* **Invented objects.** "The second individual's other hand appears to be
  holding a small instrument or tool. A small round metal bowl/dish is visible
  on the floor near the patient's foot … an indoor clinical or salon
  environment." No instrument, no bowl; both of the clinician's hands are bare
  and the objects on the floor are the patient's trainers.
* **Scene padding.** Clothing, flooring, wall colour and furniture, at 4–6× the
  length of the audio claims sitting beside them in the same section.
* **Laterality from a head-worn camera**, which cannot establish it. Notably
  the model read laterality CORRECTLY where the radiograph carried its own "R"
  marker — so the rule is "only from a marker in the frame", not "never".

Deliberately NOT asserted here: exact prompt equality with CLAUDE.md. The two
already differ in abbreviation ("visible body parts" vs "visible body parts
being examined") and collapsing that is a separate change. These tests pin the
BEHAVIOURAL rules, which is what must not drift.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.modules.providers.vision.shared import (
    VISION_GROUNDED_SYSTEM_PROMPT,
    VISION_SYSTEM_PROMPT,
)

_CLAUDE_MD = Path(__file__).resolve().parents[3] / "CLAUDE.md"

#: (label, matcher) for each guardrail. Matched case-insensitively against the
#: prompt so a reword that keeps the rule keeps the test passing — the point is
#: the constraint, not the phrasing.
_GUARDRAILS = [
    ("no scene furniture", r"do not describe the room, furniture, flooring"),
    ("no guessed objects", r"if you cannot tell what something is, leave it out"),
    ("no unmarked laterality", r"which side of the body .*unless a marker"),
]


@pytest.mark.parametrize("label,pattern", _GUARDRAILS, ids=[g[0] for g in _GUARDRAILS])
class TestDescriptivePromptGuardrails:
    def test_present_in_the_descriptive_prompt(self, label, pattern):
        assert re.search(pattern, VISION_SYSTEM_PROMPT, re.I | re.S), (
            f"{label} guardrail missing from VISION_SYSTEM_PROMPT"
        )

    def test_present_in_the_grounded_prompt(self, label, pattern):
        """Grounded captions become claims directly, so they need it MORE.

        `grounded_visual_findings_enabled` turns a caption into a NoteClaim
        cited to its frame. A fabricated object there is a fabricated clinical
        claim with a citation pointing at a frame that does not contain it.
        """
        assert re.search(pattern, VISION_GROUNDED_SYSTEM_PROMPT, re.I | re.S), (
            f"{label} guardrail missing from VISION_GROUNDED_SYSTEM_PROMPT"
        )

    def test_published_in_claude_md(self, label, pattern):
        """CLAUDE.md is the spec; a guardrail only in code is undocumented."""
        assert re.search(pattern, _CLAUDE_MD.read_text(encoding="utf-8"), re.I | re.S), (
            f"{label} guardrail missing from CLAUDE.md's pinned vision prompt"
        )


class TestDescriptiveModeNotLoosened:
    """The additions are corrective. They must not have relaxed anything."""

    @pytest.mark.parametrize(
        "prompt", [VISION_SYSTEM_PROMPT, VISION_GROUNDED_SYSTEM_PROMPT]
    )
    def test_the_no_invention_floor_survives(self, prompt):
        assert re.search(r"not directly visible", prompt, re.I)

    def test_descriptive_prompt_still_forbids_interpretation(self):
        assert re.search(
            r"do not diagnose, interpret, or infer clinical meaning",
            VISION_SYSTEM_PROMPT,
            re.I,
        )

    def test_grounded_prompt_still_forbids_unsupported_diagnosis(self):
        assert re.search(
            r"never assert a diagnosis.*the frame cannot establish",
            VISION_GROUNDED_SYSTEM_PROMPT,
            re.I | re.S,
        )

    def test_low_confidence_rule_is_intact(self):
        """The discard path depends on this; #749 regressed when it was aimed."""
        for prompt in (VISION_SYSTEM_PROMPT, VISION_GROUNDED_SYSTEM_PROMPT):
            assert re.search(r"confidence is low if", prompt, re.I)

    def test_no_section_specific_relevance_test_was_reintroduced(self):
        """The VIS-02 regression, guarded.

        A "report low if nothing relevant to THIS SECTION is visible" clause in
        the BASE prompt would discard cadence frames wholesale — that is what
        took 180 of 182 frames on session 01ce3561. The section-focus block may
        say it; the base prompt must not.
        """
        for prompt in (VISION_SYSTEM_PROMPT, VISION_GROUNDED_SYSTEM_PROMPT):
            assert "this section" not in prompt.lower()
