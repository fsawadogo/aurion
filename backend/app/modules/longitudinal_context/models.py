"""Dataclasses shared across the longitudinal_context module + its
consumers.

Kept as standalone dataclasses (not Pydantic) because they never cross
the API wire as bare objects — they live entirely inside the backend:

  * ``PriorEncounterSummary`` rolls one DB row into a model-input shape
  * ``PriorContextBlock`` is the rendered batch
  * ``PriorContextUsed`` is the lightweight count-only summary that
    Stage 1 attaches to ``Note.prior_context_used`` so the iOS badge
    and web chip can render without re-running the lookup

The fields are chosen carefully to keep PHI out of side channels:

  * ``chief_complaint_excerpt`` is truncated to ~200 chars at render
    time, never logged in full
  * ``key_claims`` is sourced from ``physical_exam`` + ``plan`` ONLY.
    Assessment text is deliberately dropped — it carries the prior
    physician's diagnostic impression, and feeding that into the next
    visit's LLM input lets the model echo the diagnosis back as if it
    reached it itself. Descriptive mode requires the model only state
    what was observed, not what was concluded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional
from uuid import UUID


@dataclass(frozen=True)
class PriorEncounterSummary:
    """One prior encounter's renderable summary.

    Frozen because every consumer treats these as immutable snapshots;
    accidental mutation in the renderer would be a latent contract bug.

    Field rationale:
      * ``session_id`` carried so audit / debug traces can locate the
        prior row without leaking PHI in the rendered block.
      * ``date`` is the calendar date of ``session.created_at`` —
        physicians think in dates, not timestamps. Used in both the
        rendered block ("2026-05-14") and the audit row
        (``last_encounter_date``).
      * ``specialty`` from the session row. Useful for cross-specialty
        physicians where the same patient sees both their ortho and
        their plastic-surg practices.
      * ``chief_complaint_excerpt`` is the chief complaint from the
        prior note, truncated. Optional so a prior session whose note
        never reached Stage 1 still produces a summary (the dated
        specialty line alone is still useful context).
      * ``key_claims`` is the prose paragraphs from
        ``physical_exam`` + ``plan``, each shortened to a single line.
        Deliberately NOT from ``assessment`` (see module docstring).
    """

    session_id: UUID
    date: date
    specialty: str
    chief_complaint_excerpt: Optional[str]
    key_claims: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PriorContextBlock:
    """The rendered batch passed to the note-gen prompt builder.

    ``encounters`` is newest-first and capped at the AppConfig limit
    (``pipeline.longitudinal_context_max_encounters``). ``total_seen``
    is the count BEFORE the cap so the iOS chip and web badge can
    honestly say "Context: 3 of 7 prior visits" if we ever want that
    UX (today they only render the referenced count, but the data is
    there for tomorrow).

    ``total_seen == 0`` with a non-None block is the "identifier set
    but no prior found" signal; ``get_prior_context`` distinguishes
    this from "no identifier" (which returns ``None`` outright) so
    audit + telemetry can tell the difference.
    """

    encounters: list[PriorEncounterSummary]
    total_seen: int


@dataclass(frozen=True)
class PriorContextUsed:
    """The slim count-only snapshot that gets attached to
    ``Note.prior_context_used`` after Stage 1 returns.

    By design this carries NO PHI:
      * ``encounters_referenced`` — integer count of rows actually
        baked into the LLM prompt
      * ``last_encounter_date`` — calendar date of the most recent
        prior visit, or ``None`` when no prior was found

    The iOS badge reads ``encounters_referenced > 0`` to decide
    whether to show the "Context-aware" chip; the web badge does the
    same. Neither side ever sees the prior session ids or any
    clinical content through this attribute — they re-fetch the rail
    via the existing ``/me/patients/{identifier}/sessions`` endpoint
    if the physician taps through.
    """

    encounters_referenced: int
    last_encounter_date: Optional[date]

    def to_dict(self) -> dict[str, Optional[str | int]]:
        """JSON-serializable shape. ``last_encounter_date`` becomes an
        ISO-8601 string for the wire so iOS / web decode it
        deterministically without timezone surprises."""
        return {
            "encounters_referenced": self.encounters_referenced,
            "last_encounter_date": (
                self.last_encounter_date.isoformat()
                if self.last_encounter_date is not None
                else None
            ),
        }
