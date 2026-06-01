"""Unit tests for the coding & billing suggestion service (#69).

Locks the parsing contract — LLM emission is fenced JSON with strict
shape requirements. Also locks the audit-event whitelists against
carrying PHI-adjacent fields (description, justification).

This is the only inference surface in Aurion; the safety property is
that we drop malformed entries individually rather than failing the
whole extraction, AND that we never let `description` or
`justification` end up in the immutable audit log.
"""

from __future__ import annotations

from app.core.audit_events import (
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
)
from app.modules.coding import service as coding

# ── _parse_extraction ────────────────────────────────────────────────────


def test_parse_valid_em_suggestion():
    reply = """
Here's the extraction:

```json
[
  {
    "code_system": "em",
    "code": "99213",
    "description": "Office/outpatient visit, est patient, low MDM",
    "justification": "HPI documents focused history; exam covers two systems; assessment lists one stable problem.",
    "source_claim_ids": ["c001", "c004"],
    "confidence": "high"
  }
]
```
"""
    out = coding._parse_extraction(reply)
    assert len(out) == 1
    entry = out[0]
    assert entry["code_system"] == "em"
    assert entry["code"] == "99213"
    assert entry["confidence"] == "high"
    assert entry["source_claim_ids"] == ["c001", "c004"]


def test_parse_empty_array_ok():
    """`[]` is a valid signal — note too sparse for billing."""
    assert coding._parse_extraction("```json\n[]\n```") == []


def test_parse_no_fenced_block_returns_empty():
    assert coding._parse_extraction("Just plain text") == []


def test_parse_malformed_json_returns_empty():
    assert coding._parse_extraction("```json\n[{not valid}]\n```") == []


def test_parse_drops_unknown_system():
    """Only em / icd10 / cpt are recognized."""
    reply = """
```json
[
  {"code_system": "hcpcs", "code": "G0438",
   "description": "x", "justification": "y"}
]
```
"""
    assert coding._parse_extraction(reply) == []


def test_parse_drops_bad_code_format():
    """Code with whitespace / special chars — drop."""
    reply = """
```json
[
  {"code_system": "icd10", "code": "M25 561",
   "description": "x", "justification": "y"}
]
```
"""
    assert coding._parse_extraction(reply) == []


def test_parse_drops_missing_required_keys():
    """Missing `justification` → drop the entry, keep the rest."""
    reply = """
```json
[
  {"code_system": "icd10", "code": "M25.561", "description": "x"},
  {"code_system": "em", "code": "99213", "description": "x",
   "justification": "y"}
]
```
"""
    out = coding._parse_extraction(reply)
    assert len(out) == 1
    assert out[0]["code_system"] == "em"


def test_parse_dedupes_within_batch():
    """Same (system, code) twice — keep the first, drop the second."""
    reply = """
```json
[
  {"code_system": "icd10", "code": "M25.561",
   "description": "Pain right knee", "justification": "claim c1"},
  {"code_system": "icd10", "code": "m25.561",
   "description": "Pain right knee (dup)", "justification": "claim c1"}
]
```
"""
    out = coding._parse_extraction(reply)
    assert len(out) == 1
    assert out[0]["description"] == "Pain right knee"


def test_parse_uppercases_code():
    """Codes are case-insensitive for matching but stored uppercase."""
    reply = """
```json
[
  {"code_system": "icd10", "code": "m25.561",
   "description": "x", "justification": "y"}
]
```
"""
    out = coding._parse_extraction(reply)
    assert out[0]["code"] == "M25.561"


def test_parse_defaults_confidence_when_missing():
    reply = """
```json
[
  {"code_system": "em", "code": "99213",
   "description": "x", "justification": "y"}
]
```
"""
    assert coding._parse_extraction(reply)[0]["confidence"] == "medium"


def test_parse_defaults_confidence_when_unknown():
    """Unknown confidence value falls back to medium, not dropped."""
    reply = """
```json
[
  {"code_system": "em", "code": "99213",
   "description": "x", "justification": "y", "confidence": "ultra"}
]
```
"""
    assert coding._parse_extraction(reply)[0]["confidence"] == "medium"


def test_parse_truncates_long_description():
    """Description capped at 200 chars to bound storage + UI render."""
    long_desc = "x" * 500
    reply = f"""
```json
[
  {{"code_system": "em", "code": "99213",
   "description": "{long_desc}", "justification": "y"}}
]
```
"""
    out = coding._parse_extraction(reply)
    assert len(out[0]["description"]) == 200


def test_parse_coerces_source_claim_ids_to_strings():
    """LLM may emit numeric ids by accident; coerce predictably."""
    reply = """
```json
[
  {"code_system": "cpt", "code": "73721",
   "description": "MRI knee w/o contrast", "justification": "y",
   "source_claim_ids": [1, 2, "c3"]}
]
```
"""
    out = coding._parse_extraction(reply)
    assert out[0]["source_claim_ids"] == ["1", "2", "c3"]


def test_parse_object_instead_of_array_returns_empty():
    """LLM emits `{}` instead of `[]` — drop, don't crash."""
    reply = '```json\n{"oops":"not an array"}\n```'
    assert coding._parse_extraction(reply) == []


def test_parse_empty_description_dropped():
    """Empty description string is not a valid suggestion."""
    reply = """
```json
[
  {"code_system": "em", "code": "99213",
   "description": "", "justification": "y"}
]
```
"""
    assert coding._parse_extraction(reply) == []


# ── Audit whitelists ─────────────────────────────────────────────────────


def test_audit_whitelists_refuse_phi_text():
    """`description` and `justification` paraphrase PHI from the note;
    the audit log must never carry them. The code itself IS allowed
    in the audit row (it's the whole point of the trail)."""
    forbidden = {"description", "justification"}
    for event in (
        AuditEventType.CODING_SUGGESTIONS_EXTRACTED,
        AuditEventType.CODING_SUGGESTION_CONFIRMED,
        AuditEventType.CODING_SUGGESTION_REJECTED,
        AuditEventType.CODING_SUGGESTION_EDITED,
    ):
        allowed = ALLOWED_AUDIT_KWARGS.get(event)
        assert allowed is not None, f"No whitelist entry for {event}"
        assert not (forbidden & allowed), (
            f"{event} whitelist must refuse {forbidden & allowed}"
        )


def test_audit_confirmed_allows_code():
    """Confirm/reject/edit allow the `code` field (billing-trail value)."""
    for event in (
        AuditEventType.CODING_SUGGESTION_CONFIRMED,
        AuditEventType.CODING_SUGGESTION_REJECTED,
    ):
        assert "code" in ALLOWED_AUDIT_KWARGS[event]
        assert "code_system" in ALLOWED_AUDIT_KWARGS[event]


def test_audit_edit_carries_both_codes():
    """Edit captures previous_code + new_code so the audit row tells
    the override story without joining row history."""
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.CODING_SUGGESTION_EDITED]
    assert "previous_code" in allowed
    assert "new_code" in allowed
    # And NOT the raw `code` field (would be ambiguous which it refers to).
    assert "code" not in allowed


def test_audit_extracted_does_not_carry_codes():
    """The extraction event is a batch-level row — kind / count /
    provider only. Per-code rows fire on subsequent confirm/reject."""
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.CODING_SUGGESTIONS_EXTRACTED]
    assert "code" not in allowed
    assert "suggestion_id" not in allowed


def test_audit_enum_values_are_stable():
    """Regression guard — locked strings for DynamoDB compatibility."""
    assert (
        AuditEventType.CODING_SUGGESTIONS_EXTRACTED.value
        == "coding_suggestions_extracted"
    )
    assert (
        AuditEventType.CODING_SUGGESTION_CONFIRMED.value
        == "coding_suggestion_confirmed"
    )
    assert (
        AuditEventType.CODING_SUGGESTION_REJECTED.value
        == "coding_suggestion_rejected"
    )
    assert (
        AuditEventType.CODING_SUGGESTION_EDITED.value
        == "coding_suggestion_edited"
    )


# ── Catalog validation integration (#69 follow-up) ───────────────────────


def test_validate_code_helper_imported():
    """Sanity — the validate_code import is wired into the service
    module. A future refactor that drops it would surface here."""
    from app.modules.coding import service as svc

    assert hasattr(svc, "validate_code")


def test_known_em_code_validates_true():
    """The exemplar case: 99213 is in our curated catalog."""
    from app.modules.coding.catalog import validate_code

    assert validate_code("em", "99213") is True


def test_unknown_em_code_validates_false():
    """Bogus code → False (actively not in catalog)."""
    from app.modules.coding.catalog import validate_code

    assert validate_code("em", "99999") is False


def test_catalog_validation_distinguishes_false_from_none():
    """The False / None distinction is the audit-story difference
    between 'checked and not found' and 'never checked'."""
    from app.modules.coding.catalog import validate_code

    # In-catalog: True
    assert validate_code("icd10", "M25.561") is True
    # Out-of-catalog but valid system: False (caution-worthy)
    assert validate_code("icd10", "Q99.999") is False
    # Unknown system: None (defensive)
    assert validate_code("hcpcs", "G0438") is None
