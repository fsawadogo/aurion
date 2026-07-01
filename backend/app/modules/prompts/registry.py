"""Registry of every LLM system prompt the encounter-analysis pipeline uses.

The registry is the single catalog the read-only Transparency page reads
from. It IMPORTS each prompt constant from its owning module — never
copies the text — so the physician-facing surface stays byte-identical
to the string the LLM actually receives.

Categories:
  * note      — drafting / auditing the SOAP note
  * vision    — captioning frames and clips
  * extraction— pulling structured rows (orders, codes) out of the note
  * preview   — the live in-encounter draft

Add a new prompt = add one entry to ``PROMPTS``. No code-branching. OCP
holds.
"""

from __future__ import annotations

from typing import Final, Literal

from pydantic import BaseModel, Field

from app.modules.coding.system_prompt import SYSTEM_PROMPT as CODING_SYSTEM_PROMPT
from app.modules.orders.system_prompt import SYSTEM_PROMPT as ORDERS_SYSTEM_PROMPT
from app.modules.patient_summary.system_prompt import (
    SYSTEM_PROMPT as PATIENT_SUMMARY_SYSTEM_PROMPT,
)
from app.modules.providers.note_gen.shared import NOTE_GEN_SYSTEM_PROMPT
from app.modules.providers.vision.shared import VISION_SYSTEM_PROMPT
from app.modules.surgery_quote.system_prompt import (
    SYSTEM_PROMPT as SURGERY_QUOTE_SYSTEM_PROMPT,
)
from app.modules.vision.reconcile import RECONCILE_SYSTEM_PROMPT

PromptCategory = Literal["note", "vision", "extraction", "preview"]


class PromptDefinition(BaseModel):
    """Metadata + text for a single LLM system prompt.

    The fields are designed to answer the three questions a physician
    asks when they tap a card on the Transparency page:

      1. What does this prompt do?              → ``purpose``
      2. When does it run during an encounter?  → ``runs_when``
      3. What exactly is the AI told?           → ``system_prompt``

    ``provider_field`` ties the prompt back to the AppConfig provider
    key that controls which LLM receives this prompt, so the portal can
    show "Powered by: anthropic" or similar without a separate lookup
    table.

    Phase B will add per-physician overlays — the response schema
    already carries those fields as ``None`` / ``False`` so iOS / web
    don't need a second migration.
    """

    id: str = Field(
        description="Stable identifier (snake_case). Becomes the URL "
        "fragment on the Transparency page; do not rename without a "
        "migration plan."
    )
    name: str = Field(
        description="Display name shown on the prompt card header."
    )
    purpose: str = Field(
        description="Plain-English answer to 'what does this prompt do?' "
        "— one sentence, no jargon."
    )
    category: PromptCategory = Field(
        description="UI grouping. Note / Vision / Extraction / Preview."
    )
    runs_when: str = Field(
        description="Plain-English answer to 'when does this prompt fire "
        "during an encounter?' — one sentence."
    )
    provider_field: str = Field(
        description="AppConfig.providers key that selects the LLM "
        "receiving this prompt. Used by the UI to show which provider "
        "is currently configured (e.g. 'note_generation', 'vision')."
    )
    system_prompt: str = Field(
        description="The EXACT system prompt string sent to the LLM. "
        "Sourced via direct import from the owning module."
    )
    schema_note: str | None = Field(
        default=None,
        description="Optional human-readable note about the expected "
        "output shape (e.g. 'JSON Note schema', 'fenced JSON array').",
    )


# Plain-English descriptions for the physician audience. Keep these
# under ~25 words each — the card layout assumes a short purpose line.
# These are NOT prompts the LLM ever sees; they're metadata for the UI.
PROMPTS: Final[dict[str, PromptDefinition]] = {
    "note_generation": PromptDefinition(
        id="note_generation",
        name="Note generation",
        purpose=(
            "Drafts the SOAP note from the audio transcript, anchoring "
            "every claim to a transcript segment."
        ),
        category="note",
        runs_when=(
            "After the recording stops, before you see the Stage 1 "
            "note for review."
        ),
        provider_field="note_generation",
        system_prompt=NOTE_GEN_SYSTEM_PROMPT,
        schema_note=(
            "Output: strict JSON matching the Note schema (sections + "
            "claims with source IDs)."
        ),
    ),
    "vision_frame": PromptDefinition(
        id="vision_frame",
        name="Vision (still frame)",
        purpose=(
            "Describes what is literally visible in a still video frame "
            "captured at a clinically-relevant moment."
        ),
        category="vision",
        runs_when=(
            "During Stage 2, on each frame the trigger classifier "
            "extracted from your video stream."
        ),
        provider_field="vision",
        system_prompt=VISION_SYSTEM_PROMPT,
        schema_note=(
            "Output: JSON with description + confidence + reason. "
            "Visual descriptions only, no clinical interpretation."
        ),
    ),
    "vision_clip": PromptDefinition(
        id="vision_clip",
        name="Vision (video clip)",
        purpose=(
            "Describes what is observable across a short video clip, "
            "including motion (range-of-motion exams, gait, etc.)."
        ),
        category="vision",
        runs_when=(
            "During Stage 2, on each clip when per-session visual "
            "evidence mode is set to 'clip'."
        ),
        provider_field="vision",
        system_prompt=VISION_SYSTEM_PROMPT,
        schema_note=(
            "Same JSON shape as still-frame vision. The clip-specific "
            "context (duration, 'describe motion') is added in the user "
            "prompt, not the system prompt — so the system instruction "
            "stays a single string both paths share."
        ),
    ),
    "conflict_reconciliation": PromptDefinition(
        id="conflict_reconciliation",
        name="Conflict reconciliation",
        purpose=(
            "Compares each visual observation against the audio claim "
            "at the same moment and flags REPEATS / ENRICHES / CONFLICTS."
        ),
        category="vision",
        runs_when=(
            "During Stage 2, after frame / clip captioning, before the "
            "merged note is delivered."
        ),
        provider_field="vision",
        system_prompt=RECONCILE_SYSTEM_PROMPT,
        schema_note=(
            "Output: JSON list of per-frame decisions with status + "
            "(if CONFLICTS) a one-line conflict_detail."
        ),
    ),
    "patient_summary": PromptDefinition(
        id="patient_summary",
        name="Patient after-visit summary",
        purpose=(
            "Rewrites the approved SOAP note as a plain-language "
            "summary for the patient to take home."
        ),
        category="extraction",
        runs_when=(
            "After you approve the final note, when you request a "
            "patient handout."
        ),
        provider_field="note_generation",
        schema_note=(
            "Output: single paragraph of plain text (≤ 600 chars). "
            "Grade-8 reading level, no diagnoses the note doesn't "
            "already record."
        ),
        system_prompt=PATIENT_SUMMARY_SYSTEM_PROMPT,
    ),
    "surgery_quote": PromptDefinition(
        id="surgery_quote",
        name="Surgery quote",
        purpose=(
            "Extracts the procedures the approved note records as "
            "discussed into editable quote line items (no prices — the "
            "physician fills the fees)."
        ),
        category="extraction",
        runs_when=(
            "After you approve the final note, when you request a "
            "surgical cost quote for the patient."
        ),
        provider_field="note_generation",
        schema_note=(
            "Output: a JSON array of {procedure, description}. No fees, "
            "no procedures the note doesn't record."
        ),
        system_prompt=SURGERY_QUOTE_SYSTEM_PROMPT,
    ),
    "orders_extraction": PromptDefinition(
        id="orders_extraction",
        name="Orders extraction",
        purpose=(
            "Pulls structured imaging / lab / referral / prescription "
            "orders out of an approved note."
        ),
        category="extraction",
        runs_when=(
            "After you approve the final note, when orders are drafted "
            "for review."
        ),
        provider_field="note_generation",
        system_prompt=ORDERS_SYSTEM_PROMPT,
        schema_note=(
            "Output: fenced JSON array of order objects. Empty array "
            "is valid when the note records no orderable actions."
        ),
    ),
    "coding_suggestions": PromptDefinition(
        id="coding_suggestions",
        name="Coding & billing suggestions",
        purpose=(
            "Suggests billing codes (E/M, ICD-10, CPT) anchored to "
            "specific claims in the approved note."
        ),
        category="extraction",
        runs_when=(
            "After you approve the final note, on a separate billing "
            "surface — does not modify the clinical note."
        ),
        provider_field="note_generation",
        system_prompt=CODING_SYSTEM_PROMPT,
        schema_note=(
            "Output: fenced JSON array of code suggestions, each with "
            "a justification + source claim IDs + confidence."
        ),
    ),
    "live_preview": PromptDefinition(
        id="live_preview",
        name="Live note preview",
        purpose=(
            "Drafts a rolling preview of the note while you're still "
            "recording, using the partial transcript so far."
        ),
        category="preview",
        runs_when=(
            "Every few seconds during an active recording, in parallel "
            "with the encounter."
        ),
        provider_field="note_generation",
        system_prompt=NOTE_GEN_SYSTEM_PROMPT,
        schema_note=(
            "Same Note JSON shape as Stage 1 — uses the same system "
            "prompt with stage=0, which the prompt treats as a draft "
            "(looser citation requirements). The preview never "
            "replaces the canonical Stage 1 note."
        ),
    ),
}
