"""Focused coverage for Anthropic's compact parallel Stage 1 path."""

from __future__ import annotations

import asyncio
from collections import Counter, defaultdict
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.types import ProviderError, Template, TemplateSection, Transcript, TranscriptSegment
from app.modules.providers.note_gen.compact_stage1 import (
    hydrate_compact_stage1_shards,
    partition_stage1_template,
)
from app.modules.providers.usage_context import consume_call_usage


def _template() -> Template:
    return Template(
        key="orthopedic_surgery",
        display_name="Orthopedic Surgery",
        sections=[
            TemplateSection(
                id="hpi",
                title="History of Present Illness",
                required=True,
                description="History, symptoms, and activity.",
            ),
            TemplateSection(
                id="physical_exam",
                title="Physical Examination",
                required=True,
                description="Named examination manoeuvres and laterality.",
                visual_trigger_keywords=["exam"],
            ),
            TemplateSection(
                id="assessment",
                title="Assessment",
                required=True,
                description="Grounded working assessment.",
            ),
        ],
    )


def _transcript() -> Transcript:
    return Transcript(
        session_id="00000000-0000-0000-0000-000000000001",
        provider_used="assemblyai",
        segments=[
            TranscriptSegment(
                id="seg_001",
                start_ms=0,
                end_ms=1_000,
                text="Pain is on the medial side of the left knee.",
            ),
            TranscriptSegment(
                id="seg_002",
                start_ms=1_000,
                end_ms=2_000,
                text="McMurray is positive on the left.",
            ),
            TranscriptSegment(
                id="seg_003",
                start_ms=2_000,
                end_ms=3_000,
                text="The working assessment is a possible meniscal tear.",
            ),
        ],
    )


def _config(max_tokens: int = 8_000):
    return SimpleNamespace(
        model_params=SimpleNamespace(
            note_generation=SimpleNamespace(
                max_tokens=max_tokens,
                temperature=0.1,
            )
        )
    )


def _response(
    payload: dict,
    *,
    stop_reason: str = "tool_use",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> MagicMock:
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(
        return_value={
            "stop_reason": stop_reason,
            "usage": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            },
            "content": [
                {
                    "type": "tool_use",
                    "name": "emit_clinical_note",
                    "input": payload,
                }
            ],
        }
    )
    return response


def _client(post_side_effect) -> AsyncMock:
    client = AsyncMock()
    client.post = AsyncMock(side_effect=post_side_effect)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _allowed_ids(request_body: dict) -> tuple[str, ...]:
    schema = request_body["tools"][0]["input_schema"]
    return tuple(schema["properties"]["sections"]["items"]["properties"]["id"]["enum"])


def _payload_for(allowed: tuple[str, ...]) -> dict:
    if "hpi" in allowed:
        return {
            "sections": [
                {
                    "id": "hpi",
                    "status": "populated",
                    "claims": [
                        {
                            "text": "Medial left knee pain.",
                            "source_ids": ["seg_001"],
                            # Hydration must ignore any unexpected model quote.
                            "source_quote": "not the canonical transcript",
                        }
                    ],
                }
            ]
        }
    if "physical_exam" in allowed:
        return {
            "sections": [
                {
                    "id": "physical_exam",
                    "status": "populated",
                    "claims": [
                        {
                            "text": "McMurray positive on the left.",
                            "source_ids": ["seg_002"],
                        }
                    ],
                }
            ]
        }
    return {
        "sections": [
            {
                "id": "assessment",
                "status": "populated",
                "claims": [
                    {
                        "text": "Working assessment: possible meniscal tear.",
                        "source_ids": ["seg_002", "seg_003"],
                    }
                ],
            }
        ]
    }


def _full_payload() -> dict:
    return {
        "sections": [
            {
                "id": "hpi",
                "title": "History of Present Illness",
                "status": "populated",
                "claims": [
                    {
                        "id": "provider_hpi",
                        "text": "Medial left knee pain.",
                        "source_type": "transcript",
                        "source_id": "seg_001",
                        "source_quote": "Pain is on the medial side of the left knee.",
                    }
                ],
            },
            {
                "id": "physical_exam",
                "title": "Physical Examination",
                "status": "populated",
                "claims": [
                    {
                        "id": "provider_exam",
                        "text": "McMurray positive on the left.",
                        "source_type": "transcript",
                        "source_id": "seg_002",
                        "source_quote": "McMurray is positive on the left.",
                    }
                ],
            },
            {
                "id": "assessment",
                "title": "Assessment",
                "status": "populated",
                "claims": [
                    {
                        "id": "provider_assessment",
                        "text": "Working assessment: possible meniscal tear.",
                        "source_type": "transcript",
                        "source_id": "seg_003",
                        "source_quote": "The working assessment is a possible meniscal tear.",
                    }
                ],
            },
        ]
    }


def test_partition_is_three_disjoint_semantic_groups_in_template_order() -> None:
    template = Template(
        key="orthopedic_surgery",
        display_name="Orthopedic Surgery",
        sections=[
            TemplateSection(id="chief_complaint", title="Chief Complaint"),
            TemplateSection(id="hpi", title="HPI"),
            TemplateSection(id="physical_exam", title="Physical Exam"),
            TemplateSection(id="imaging_review", title="Imaging"),
            TemplateSection(id="assessment", title="Assessment"),
            TemplateSection(id="plan", title="Plan"),
        ],
    )

    shards = partition_stage1_template(template)

    assert [(shard.name, shard.section_ids) for shard in shards] == [
        ("history", ("chief_complaint", "hpi")),
        ("objective", ("physical_exam", "imaging_review")),
        ("assessment_plan", ("assessment", "plan")),
    ]
    flattened = [section_id for shard in shards for section_id in shard.section_ids]
    assert Counter(flattened) == Counter(section.id for section in template.sections)


def test_hydration_uses_canonical_quotes_and_rejects_any_unknown_anchor() -> None:
    template = _template()
    transcript = _transcript()
    shards = partition_stage1_template(template)
    by_name = {shard.name: shard for shard in shards}

    note = hydrate_compact_stage1_shards(
        [
            (by_name["history"], _payload_for(by_name["history"].section_ids)),
            (
                by_name["objective"],
                {
                    "sections": [
                        {
                            "id": "physical_exam",
                            "status": "populated",
                            "claims": [
                                {
                                    "text": "Must be dropped as partly ungrounded.",
                                    "source_ids": ["seg_002", "seg_404"],
                                }
                            ],
                        },
                    ]
                },
            ),
            (
                by_name["assessment_plan"],
                _payload_for(by_name["assessment_plan"].section_ids),
            ),
        ],
        transcript,
        template,
    )

    assert [section.id for section in note.sections] == [
        "hpi",
        "physical_exam",
        "assessment",
    ]
    hpi = note.get_section("hpi")
    assert hpi is not None
    assert hpi.claims[0].source_quote == transcript.segments[0].text
    assert hpi.claims[0].id == "claim_001"

    exam = note.get_section("physical_exam")
    assert exam is not None
    assert exam.status == "not_captured"
    assert exam.claims == []

    assessment = note.get_section("assessment")
    assert assessment is not None
    claim = assessment.claims[0]
    assert claim.id == "claim_002"
    assert claim.source_quote == transcript.segments[1].text
    assert [source.source_id for source in claim.additional_sources] == ["seg_003"]
    assert claim.additional_sources[0].source_quote == transcript.segments[2].text


@pytest.mark.parametrize(
    "sections",
    [
        [],
        [{"id": "hpi", "status": "not_captured", "claims": []}],
        [
            {"id": "hpi", "status": "not_captured", "claims": []},
            {"id": "hpi", "status": "not_captured", "claims": []},
        ],
    ],
    ids=["empty", "partial", "duplicate"],
)
def test_multi_section_shard_requires_exactly_one_row_per_section(sections: list[dict]) -> None:
    template = Template(
        key="history_only",
        display_name="History",
        sections=[
            TemplateSection(id="chief_complaint", title="Chief Complaint"),
            TemplateSection(id="hpi", title="History of Present Illness"),
        ],
    )
    shard = partition_stage1_template(template)[0]

    with pytest.raises(ProviderError, match="contract violation"):
        hydrate_compact_stage1_shards(
            [(shard, {"sections": sections})],
            _transcript(),
            template,
        )


@pytest.mark.parametrize(
    ("model_status", "expected_status"),
    [("populated", "not_captured"), ("pending_video", "pending_video")],
)
def test_empty_keyworded_history_section_uses_only_explicit_pending_video(
    model_status: str,
    expected_status: str,
) -> None:
    template = Template(
        key="family_medicine",
        display_name="Family Medicine",
        sections=[
            TemplateSection(
                id="past_medical_history",
                title="Past Medical History",
                visual_trigger_keywords=["history of", "diagnosed with"],
            )
        ],
    )
    shard = partition_stage1_template(template)[0]

    note = hydrate_compact_stage1_shards(
        [
            (
                shard,
                {
                    "sections": [
                        {
                            "id": "past_medical_history",
                            "status": model_status,
                            "claims": [],
                        }
                    ]
                },
            )
        ],
        _transcript(),
        template,
    )

    section = note.get_section("past_medical_history")
    assert section is not None
    assert section.status == expected_status


@pytest.mark.asyncio
async def test_stage1_starts_all_three_shards_concurrently_and_sums_usage(
    monkeypatch,
) -> None:
    from app.modules.providers.note_gen import anthropic as module

    monkeypatch.setattr(module, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(module, "get_config", lambda: _config())
    consume_call_usage()

    started: set[tuple[str, ...]] = set()
    all_started = asyncio.Event()

    async def post(_url: str, **kwargs):
        allowed = _allowed_ids(kwargs["json"])
        started.add(allowed)
        if len(started) == 3:
            all_started.set()
        # A sequential implementation deadlocks here and fails the test.
        await asyncio.wait_for(all_started.wait(), timeout=0.25)
        await asyncio.sleep(0.01)
        return _response(_payload_for(allowed))

    client = _client(post)
    with patch("httpx.AsyncClient", return_value=client):
        note = await module.AnthropicNoteGenerationProvider().generate_note(_transcript(), _template(), stage=1)

    assert client.post.await_count == 3
    assert [section.id for section in note.sections] == [
        "hpi",
        "physical_exam",
        "assessment",
    ]
    assert note.completeness_score == 1.0
    assessment = note.get_section("assessment")
    assert assessment is not None
    assert assessment.claims[0].source_quote == _transcript().segments[1].text
    assert assessment.claims[0].additional_sources[0].source_quote == (_transcript().segments[2].text)

    usage = consume_call_usage()
    assert usage is not None
    assert usage.input_tokens == 30
    assert usage.output_tokens == 15


@pytest.mark.asyncio
async def test_truncation_retries_only_the_affected_shard(monkeypatch) -> None:
    from app.modules.providers.note_gen import anthropic as module

    monkeypatch.setattr(module, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(module, "get_config", lambda: _config())
    consume_call_usage()
    calls: defaultdict[tuple[str, ...], list[int]] = defaultdict(list)

    async def post(_url: str, **kwargs):
        body = kwargs["json"]
        allowed = _allowed_ids(body)
        calls[allowed].append(body["max_tokens"])
        if "physical_exam" in allowed and len(calls[allowed]) == 1:
            return _response({}, stop_reason="max_tokens")
        return _response(_payload_for(allowed))

    client = _client(post)
    with patch("httpx.AsyncClient", return_value=client):
        note = await module.AnthropicNoteGenerationProvider().generate_note(_transcript(), _template(), stage=1)

    assert note.completeness_score == 1.0
    assert client.post.await_count == 4
    # The configured full-note budget is shared across first attempts so three
    # concurrent requests reserve ~8k total, not 24k. Only the truncated shard
    # retries at the full configured ceiling.
    assert calls[("hpi",)] == [2_667]
    assert calls[("physical_exam",)] == [2_667, 8_000]
    assert calls[("assessment",)] == [2_667]
    usage = consume_call_usage()
    assert usage is not None
    assert usage.input_tokens == 40
    assert usage.output_tokens == 20


@pytest.mark.asyncio
async def test_truncated_shard_retains_escalated_final_ceiling(monkeypatch) -> None:
    from app.modules.providers.note_gen import anthropic as module

    monkeypatch.setattr(module, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(module, "get_config", lambda: _config())
    consume_call_usage()
    calls: defaultdict[tuple[str, ...], list[int]] = defaultdict(list)

    async def post(_url: str, **kwargs):
        body = kwargs["json"]
        allowed = _allowed_ids(body)
        calls[allowed].append(body["max_tokens"])
        if "physical_exam" in allowed and len(calls[allowed]) < 3:
            return _response({}, stop_reason="max_tokens")
        return _response(_payload_for(allowed))

    client = _client(post)
    with patch("httpx.AsyncClient", return_value=client):
        note = await module.AnthropicNoteGenerationProvider().generate_note(
            _transcript(),
            _template(),
            stage=1,
        )

    assert note.completeness_score == 1.0
    assert calls[("physical_exam",)] == [2_667, 8_000, 32_000]


@pytest.mark.asyncio
async def test_owner_deadline_cancels_and_joins_all_compact_shards(monkeypatch) -> None:
    from app.modules.note_gen.service import (
        Stage1DeadlineExceededError,
        _await_with_stage1_deadline,
    )
    from app.modules.providers.note_gen import anthropic as module

    monkeypatch.setattr(module, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(module, "get_config", lambda: _config())
    all_started = asyncio.Event()
    all_cancelled = asyncio.Event()
    started: set[tuple[str, ...]] = set()
    cancelled: set[tuple[str, ...]] = set()

    async def post(_url: str, **kwargs):
        allowed = _allowed_ids(kwargs["json"])
        started.add(allowed)
        if len(started) == 3:
            all_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.add(allowed)
            if len(cancelled) == 3:
                all_cancelled.set()

    client = _client(post)
    with patch("httpx.AsyncClient", return_value=client):
        operation = module.AnthropicNoteGenerationProvider().generate_note(
            _transcript(),
            _template(),
            stage=1,
        )
        with pytest.raises(Stage1DeadlineExceededError):
            await _await_with_stage1_deadline(
                operation,
                deadline_at=asyncio.get_running_loop().time() + 0.1,
            )

    assert all_started.is_set()
    assert all_cancelled.is_set()
    assert len(cancelled) == 3


@pytest.mark.asyncio
async def test_stage1_with_prior_context_uses_one_full_schema_call(monkeypatch) -> None:
    from app.modules.providers.note_gen import anthropic as module

    monkeypatch.setattr(module, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(module, "get_config", lambda: _config())
    prior_context = "Prior visits with this patient: 2026-08-01 follow-up."

    async def post(_url: str, **_kwargs):
        return _response(_full_payload())

    client = _client(post)
    with patch("httpx.AsyncClient", return_value=client):
        note = await module.AnthropicNoteGenerationProvider().generate_note(
            _transcript(),
            _template(),
            stage=1,
            prior_context_text=prior_context,
        )

    assert client.post.await_count == 1
    body = client.post.await_args.kwargs["json"]
    section_schema = body["tools"][0]["input_schema"]["properties"]["sections"]["items"]
    claim_schema = section_schema["properties"]["claims"]["items"]
    assert "title" in section_schema["properties"]
    assert "source_id" in claim_schema["properties"]
    assert "source_ids" not in claim_schema["properties"]
    assert prior_context in body["messages"][0]["content"]
    assert "COMPACT STAGE 1 RESPONSE CONTRACT" not in body["messages"][0]["content"]
    assert note.stage == 1


@pytest.mark.asyncio
async def test_stage2_keeps_single_full_schema_call(monkeypatch) -> None:
    from app.modules.providers.note_gen import anthropic as module

    monkeypatch.setattr(module, "_ANTHROPIC_API_KEY", "key")
    monkeypatch.setattr(module, "get_config", lambda: _config())
    async def post(_url: str, **_kwargs):
        return _response(_full_payload())

    client = _client(post)
    with patch("httpx.AsyncClient", return_value=client):
        note = await module.AnthropicNoteGenerationProvider().generate_note(_transcript(), _template(), stage=2)

    assert client.post.await_count == 1
    body = client.post.await_args.kwargs["json"]
    claim_schema = body["tools"][0]["input_schema"]["properties"]["sections"]["items"]["properties"]["claims"]["items"]
    assert "source_quote" in claim_schema["properties"]
    assert "COMPACT STAGE 1 RESPONSE CONTRACT" not in body["messages"][0]["content"]
    assert note.stage == 2
    assert note.get_section("hpi").claims[0].source_quote == (
        "Pain is on the medial side of the left knee."
    )
