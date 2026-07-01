"""Unit tests for the surgery-quote generator (note-Options phase 3).

Pure-function coverage (no DB): the LLM-output parser, the physician-edit
validator, the descriptive-mode prompt guardrails, and the audit whitelist
(no procedure / fee / notes text ever reaches the append-only audit log).
Mirrors test_patient_summary.py.
"""

from __future__ import annotations

import pytest

from app.core.types import Note, NoteClaim, NoteSection
from app.modules.surgery_quote import service as sq
from app.modules.surgery_quote.system_prompt import SYSTEM_PROMPT

# ── LLM output parser ────────────────────────────────────────────────────


def test_parse_line_items_happy_path() -> None:
    raw = (
        '[{"procedure": "Breast augmentation", "description": "Implants"},'
        ' {"procedure": "Liposuction", "description": "Flanks"}]'
    )
    items = sq._parse_line_items(raw)
    assert [i["procedure"] for i in items] == ["Breast augmentation", "Liposuction"]
    # Every item gets an id + an EMPTY fee (physician fills it).
    assert all(i["id"].startswith("li_") for i in items)
    assert all(i["fee_cents"] is None for i in items)


def test_parse_line_items_strips_markdown_fence() -> None:
    raw = '```json\n[{"procedure": "Rhinoplasty", "description": "Nose"}]\n```'
    items = sq._parse_line_items(raw)
    assert len(items) == 1
    assert items[0]["procedure"] == "Rhinoplasty"


def test_parse_line_items_tolerates_wrapper_object() -> None:
    raw = '{"procedures": [{"procedure": "Facelift", "description": ""}]}'
    items = sq._parse_line_items(raw)
    assert len(items) == 1 and items[0]["procedure"] == "Facelift"


def test_parse_line_items_ignores_model_supplied_fee() -> None:
    """Even if the model disobeys and returns a fee, it is NEVER stored —
    fees are physician-entered only."""
    raw = '[{"procedure": "Blepharoplasty", "description": "Eyelids", "fee_cents": 500000}]'
    items = sq._parse_line_items(raw)
    assert items[0]["fee_cents"] is None


def test_parse_line_items_bad_json_returns_empty() -> None:
    assert sq._parse_line_items("not json at all") == []
    assert sq._parse_line_items("") == []


def test_parse_line_items_drops_malformed_and_caps_count() -> None:
    entries = [{"procedure": f"P{i}", "description": ""} for i in range(40)]
    entries.append({"no_procedure": "x"})  # dropped
    import json

    items = sq._parse_line_items(json.dumps(entries))
    assert len(items) == sq._MAX_LINE_ITEMS


# ── Physician-edit validator ─────────────────────────────────────────────


def test_validate_edit_requires_procedure() -> None:
    with pytest.raises(ValueError):
        sq._validate_edit_line_items([{"procedure": "  ", "fee_cents": 100}])


def test_validate_edit_rejects_negative_or_non_int_fee() -> None:
    with pytest.raises(ValueError):
        sq._validate_edit_line_items([{"procedure": "P", "fee_cents": -1}])
    with pytest.raises(ValueError):
        sq._validate_edit_line_items([{"procedure": "P", "fee_cents": 9.99}])
    with pytest.raises(ValueError):
        sq._validate_edit_line_items([{"procedure": "P", "fee_cents": True}])


def test_validate_edit_accepts_and_preserves_fee_and_id() -> None:
    cleaned = sq._validate_edit_line_items(
        [{"id": "li_0a1b2c3d", "procedure": "Breast aug", "fee_cents": 850000}]
    )
    assert cleaned[0]["fee_cents"] == 850000
    assert cleaned[0]["id"] == "li_0a1b2c3d"


def test_validate_edit_mints_id_when_malformed() -> None:
    cleaned = sq._validate_edit_line_items([{"id": "bogus", "procedure": "P"}])
    assert cleaned[0]["id"].startswith("li_")
    assert cleaned[0]["id"] != "bogus"


def test_validate_edit_caps_count() -> None:
    with pytest.raises(ValueError):
        sq._validate_edit_line_items(
            [{"procedure": "P"} for _ in range(sq._MAX_LINE_ITEMS + 1)]
        )


# ── Note rendering ───────────────────────────────────────────────────────


def test_render_note_skips_unpopulated_sections() -> None:
    note = Note(
        session_id="s", stage=1, version=1, provider_used="anthropic",
        specialty="plastic_surgery", completeness_score=0.5,
        sections=[
            NoteSection(id="plan", title="Plan", status="populated", claims=[
                NoteClaim(id="c1", text="Discussed breast augmentation.",
                          source_type="transcript", source_id="seg_1",
                          source_quote="breast aug"),
            ]),
            NoteSection(id="imaging", title="Imaging", status="not_captured", claims=[]),
        ],
    )
    rendered = sq._render_note_for_prompt(note)
    assert "Plan" in rendered and "breast augmentation" in rendered
    assert "Imaging" not in rendered


# ── Descriptive-mode prompt guardrails ───────────────────────────────────


def test_system_prompt_forbids_fabricated_prices_and_procedures() -> None:
    lowered = SYSTEM_PROMPT.lower()
    assert "do not invent" in lowered
    # Never fabricate a fee.
    assert "fee" in lowered and "fabricate" in lowered
    # Only procedures the note records.
    assert "explicitly records" in lowered or "explicitly" in lowered


# ── Audit whitelist (no PHI in the append-only log) ──────────────────────


def test_surgery_quote_audit_whitelists_carry_no_phi() -> None:
    from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType

    for evt in (
        AuditEventType.SURGERY_QUOTE_GENERATED,
        AuditEventType.SURGERY_QUOTE_EDITED,
    ):
        allowed = ALLOWED_AUDIT_KWARGS[evt]
        for banned in ("line_items", "procedure", "fee_cents", "notes", "description"):
            assert banned not in allowed, f"{evt.value} must not carry {banned}"


def test_surgery_quote_audit_enum_values_stable() -> None:
    from app.core.audit_events import AuditEventType

    assert AuditEventType.SURGERY_QUOTE_GENERATED.value == "surgery_quote_generated"
    assert AuditEventType.SURGERY_QUOTE_EDITED.value == "surgery_quote_edited"
