"""Compact Anthropic Stage 1 wire contract.

This module is deliberately internal to the Anthropic provider.  The model
returns only clinical claim text plus transcript segment ids; the backend then
hydrates the public :class:`~app.core.types.Note` contract from canonical
server-side data.  Claim ids, section titles, source types, and exact source
quotes therefore cost no output tokens and cannot be fabricated by the model.

Stage 2 does not use this module.  Its visual/screen source types require the
existing full response contract.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from dataclasses import dataclass
from typing import Any, Sequence

from app.core.types import Note, ProviderError, Template, TemplateSection, Transcript
from app.modules.providers.note_gen.shared import parse_note_response

logger = logging.getLogger("aurion.providers.note_gen.compact_stage1")


@dataclass(frozen=True)
class Stage1ShardSpec:
    """One of at most three disjoint Stage 1 section groups."""

    name: str
    template: Template

    @property
    def section_ids(self) -> tuple[str, ...]:
        return tuple(section.id for section in self.template.sections)


_OBJECTIVE_HINTS = (
    "physical_exam",
    "exam",
    "imaging",
    "investigation",
    "vital",
    "wound_assessment",
    "functional_assessment",
    "procedure",
    "laboratory",
    "measurement",
)
_ASSESSMENT_PLAN_HINTS = (
    "assessment",
    "diagnosis",
    "impression",
    "plan",
    "disposition",
    "recommendation",
    "follow_up",
    "follow-up",
)

_OBJECTIVE_SECTION_IDS = {
    "physical_exam",
    "imaging_review",
    "investigations",
    "vital_signs",
    "wound_assessment",
    "functional_assessment",
}
_ASSESSMENT_PLAN_SECTION_IDS = {
    "assessment",
    "plan",
    "disposition",
    "follow_up",
}


def _section_group(section: TemplateSection) -> int:
    """Return history=0, objective=1, assessment/plan=2.

    Built-in templates use stable semantic ids. Title text is included as a
    defensive fallback for clinician-authored custom templates.
    Unknown sections stay in the history/general group rather than being
    guessed into Assessment & Plan.
    """

    if section.id in _OBJECTIVE_SECTION_IDS:
        return 1
    if section.id in _ASSESSMENT_PLAN_SECTION_IDS:
        return 2

    # Descriptions often mention downstream diagnosis/plan concepts while
    # describing a history field, so they are intentionally excluded from the
    # heuristic. Stable ids/titles are the semantic routing surface.
    semantic_text = " ".join((section.id, section.title)).lower().replace(" ", "_")
    if any(hint in semantic_text for hint in _OBJECTIVE_HINTS):
        return 1
    if any(hint in semantic_text for hint in _ASSESSMENT_PLAN_HINTS):
        return 2
    return 0


def partition_stage1_template(template: Template) -> list[Stage1ShardSpec]:
    """Partition ``template`` into at most three disjoint semantic shards.

    Section order is preserved within each shard.  Empty groups are omitted,
    so a small custom template does not create a pointless provider call.
    """

    grouped: list[list[TemplateSection]] = [[], [], []]
    for section in template.sections:
        grouped[_section_group(section)].append(section)

    names = ("history", "objective", "assessment_plan")
    return [
        Stage1ShardSpec(
            name=name,
            template=template.model_copy(update={"sections": sections}),
        )
        for name, sections in zip(names, grouped, strict=True)
        if sections
    ]


def compact_response_schema(section_ids: Sequence[str]) -> dict[str, Any]:
    """Anthropic tool schema for one compact Stage 1 shard."""

    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "sections": {
                "type": "array",
                "minItems": len(section_ids),
                "maxItems": len(section_ids),
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "enum": list(section_ids)},
                        "status": {
                            "type": "string",
                            "enum": [
                                "populated",
                                "pending_video",
                                "not_captured",
                            ],
                        },
                        "claims": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "properties": {
                                    "text": {"type": "string"},
                                    "source_ids": {
                                        "type": "array",
                                        "minItems": 1,
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["text", "source_ids"],
                            },
                        },
                    },
                    "required": ["id", "status", "claims"],
                },
            }
        },
        "required": ["sections"],
    }


def validate_compact_stage1_shard_payload(
    shard: Stage1ShardSpec,
    payload: dict[str, Any],
) -> None:
    """Require exactly one response row for every section in ``shard``.

    Prompt instructions and JSON-Schema array bounds cannot prove that each
    enum member appears exactly once. Reject the entire shard rather than
    silently synthesizing an omitted clinical section as ``not_captured``.
    """

    raw_sections = payload.get("sections") if isinstance(payload, dict) else None
    if not isinstance(raw_sections, list):
        raise ProviderError(
            "anthropic",
            f"Compact Stage 1 shard {shard.name} returned an invalid sections array",
        )

    allowed_ids = set(shard.section_ids)
    returned_ids = [
        raw_section.get("id")
        for raw_section in raw_sections
        if isinstance(raw_section, dict) and isinstance(raw_section.get("id"), str)
    ]
    counts = Counter(returned_ids)
    malformed_rows = len(raw_sections) - len(returned_ids)
    missing_count = sum(counts[section_id] == 0 for section_id in shard.section_ids)
    duplicate_count = sum(max(0, counts[section_id] - 1) for section_id in shard.section_ids)
    unexpected_count = sum(count for section_id, count in counts.items() if section_id not in allowed_ids)

    if (
        len(raw_sections) != len(shard.section_ids)
        or malformed_rows
        or missing_count
        or duplicate_count
        or unexpected_count
    ):
        raise ProviderError(
            "anthropic",
            "Compact Stage 1 shard contract violation: "
            f"shard={shard.name} expected={len(shard.section_ids)} "
            f"returned={len(raw_sections)} missing={missing_count} "
            f"duplicates={duplicate_count} unexpected={unexpected_count} "
            f"malformed={malformed_rows}",
        )


def hydrate_compact_stage1_shards(
    shard_payloads: Sequence[tuple[Stage1ShardSpec, dict[str, Any]]],
    transcript: Transcript,
    template: Template,
    *,
    provider_name: str = "anthropic",
) -> Note:
    """Hydrate compact shard payloads into the unchanged public ``Note``.

    Grounding is fail-closed: a claim is dropped if *any* cited source id is
    empty, malformed, or absent from the canonical transcript.  Keeping only
    the valid subset would be unsafe for a synthesized claim whose conclusion
    may depend on the rejected anchor.
    """

    source_text = {segment.id: segment.text for segment in transcript.segments}
    template_by_id = {section.id: section for section in template.sections}
    claims_by_section: dict[str, list[dict[str, Any]]] = {section.id: [] for section in template.sections}
    status_by_section = {section.id: "not_captured" for section in template.sections}

    rejected_claims = 0
    rejected_sections = 0

    for shard, payload in shard_payloads:
        validate_compact_stage1_shard_payload(shard, payload)
        allowed_ids = set(shard.section_ids)
        raw_sections = payload.get("sections", []) if isinstance(payload, dict) else []
        if not isinstance(raw_sections, list):
            raw_sections = []

        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                rejected_sections += 1
                continue
            section_id = raw_section.get("id")
            if section_id not in allowed_ids or section_id not in template_by_id:
                rejected_sections += 1
                continue

            raw_status = raw_section.get("status")
            if raw_status in {"pending_video", "not_captured"}:
                status_by_section[section_id] = raw_status

            raw_claims = raw_section.get("claims", [])
            if not isinstance(raw_claims, list):
                raw_claims = []
            for raw_claim in raw_claims:
                if not isinstance(raw_claim, dict):
                    rejected_claims += 1
                    continue
                text = raw_claim.get("text")
                raw_source_ids = raw_claim.get("source_ids")
                # Defensive rollout compatibility: older mocked/provider
                # payloads may still carry the full-contract primary
                # ``source_id``.  We accept only that id and still ignore the
                # model's quote/type/id in favour of canonical hydration.
                if raw_source_ids is None and isinstance(raw_claim.get("source_id"), str):
                    raw_source_ids = [raw_claim["source_id"]]
                if (
                    not isinstance(text, str)
                    or not text.strip()
                    or not isinstance(raw_source_ids, list)
                    or not raw_source_ids
                ):
                    rejected_claims += 1
                    continue

                source_ids: list[str] = []
                malformed_source = False
                for source_id in raw_source_ids:
                    if not isinstance(source_id, str) or not source_id or source_id not in source_text:
                        malformed_source = True
                        break
                    if source_id not in source_ids:
                        source_ids.append(source_id)
                if malformed_source or not source_ids:
                    rejected_claims += 1
                    continue

                primary = source_ids[0]
                claims_by_section[section_id].append(
                    {
                        # Assigned deterministically in final template order below.
                        "id": "",
                        "text": text.strip(),
                        "source_type": "transcript",
                        "source_id": primary,
                        "source_quote": source_text[primary],
                        "additional_sources": [
                            {
                                "source_id": source_id,
                                "source_quote": source_text[source_id],
                            }
                            for source_id in source_ids[1:]
                        ],
                    }
                )
                status_by_section[section_id] = "populated"

    full_sections: list[dict[str, Any]] = []
    next_claim = 1
    for section in template.sections:
        claims = claims_by_section[section.id]
        for claim in claims:
            claim["id"] = f"claim_{next_claim:03d}"
            next_claim += 1
        full_sections.append(
            {
                "id": section.id,
                "title": section.title,
                "status": "populated" if claims else status_by_section[section.id],
                "claims": claims,
            }
        )

    if rejected_claims or rejected_sections:
        logger.warning(
            "compact Stage 1 hydration rejected model output: session=%s claims=%d sections=%d",
            transcript.session_id,
            rejected_claims,
            rejected_sections,
        )

    return parse_note_response(
        json.dumps({"sections": full_sections}),
        transcript,
        template,
        stage=1,
        provider_name=provider_name,
    )
