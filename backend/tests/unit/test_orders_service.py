"""Unit tests for the orders extraction service.

Locks the parsing contract — the LLM emission is fenced JSON and may
be partially malformed; the parser must drop bad entries without
crashing the extraction, and validate the per-kind required keys.
Also locks the audit-event whitelists against carrying any PHI-ish
fields.
"""

from __future__ import annotations

from app.core.audit_events import (
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
)
from app.modules.orders import service as orders

# ── _parse_extraction ────────────────────────────────────────────────────


def test_parse_extracts_valid_array():
    """Single fenced JSON array with one good imaging entry."""
    reply = """
Sure, here's the extraction:

```json
[
  {
    "kind": "imaging",
    "details": {
      "modality": "MRI",
      "body_part": "right knee",
      "laterality": "right",
      "indication": "rule out meniscus tear"
    },
    "source_claim_ids": ["c007"]
  }
]
```
"""
    out = orders._parse_extraction(reply)
    assert len(out) == 1
    assert out[0]["kind"] == "imaging"
    assert out[0]["details"]["modality"] == "MRI"
    assert out[0]["source_claim_ids"] == ["c007"]


def test_parse_empty_array_ok():
    """An empty `[]` is a valid signal — no orders in this note."""
    reply = "```json\n[]\n```"
    assert orders._parse_extraction(reply) == []


def test_parse_no_fenced_block_returns_empty():
    """LLM forgot the fence — we don't try to recover unsafely."""
    assert orders._parse_extraction("Just plain text") == []


def test_parse_malformed_json_returns_empty():
    assert orders._parse_extraction("```json\n[{not valid}]\n```") == []


def test_parse_drops_unknown_kind():
    """Backend rejects kinds outside the four supported types."""
    reply = """
```json
[
  {"kind": "consult", "details": {"specialty":"cards","reason":"x"}}
]
```
"""
    assert orders._parse_extraction(reply) == []


def test_parse_drops_imaging_missing_required_keys():
    """Imaging without `modality` → drop the entry, keep the others."""
    reply = """
```json
[
  {"kind":"imaging","details":{"body_part":"knee"}},
  {"kind":"lab","details":{"panel":"CBC","indication":"workup"}}
]
```
"""
    out = orders._parse_extraction(reply)
    assert len(out) == 1
    assert out[0]["kind"] == "lab"


def test_parse_drops_prescription_missing_dose():
    reply = """
```json
[
  {"kind":"prescription",
   "details":{"drug":"ibuprofen","frequency":"PRN","indication":"pain"}}
]
```
"""
    assert orders._parse_extraction(reply) == []


def test_parse_accepts_referral_without_urgency():
    """Urgency is documented in the prompt but not required — should
    pass through if specialty + reason are present."""
    reply = """
```json
[
  {"kind":"referral","details":{"specialty":"orthopedics","reason":"meniscus tear"}}
]
```
"""
    out = orders._parse_extraction(reply)
    assert len(out) == 1
    assert out[0]["kind"] == "referral"


def test_parse_coerces_source_claim_ids_to_strings():
    """LLM may emit numeric ids by accident; coerce so downstream JSON
    stays predictable."""
    reply = """
```json
[
  {"kind":"lab","details":{"panel":"CBC","indication":"x"},"source_claim_ids":[1,2,"c3"]}
]
```
"""
    out = orders._parse_extraction(reply)
    assert out[0]["source_claim_ids"] == ["1", "2", "c3"]


def test_parse_object_instead_of_array_returns_empty():
    """LLM emits {} instead of [] — drop, don't crash."""
    reply = '```json\n{"oops":"not an array"}\n```'
    assert orders._parse_extraction(reply) == []


# ── Audit whitelists ─────────────────────────────────────────────────────


def test_audit_whitelists_refuse_details():
    """`details` is PHI-adjacent (drug names, body parts). The audit
    log must never carry it — lock the kwargs whitelist."""
    for event in (
        AuditEventType.ORDERS_EXTRACTED,
        AuditEventType.ORDER_CONFIRMED,
        AuditEventType.ORDER_EDITED,
        AuditEventType.ORDER_CANCELLED,
    ):
        allowed = ALLOWED_AUDIT_KWARGS.get(event)
        assert allowed is not None, f"No whitelist entry for {event}"
        assert "details" not in allowed
        assert "drug" not in allowed
        assert "body_part" not in allowed
        assert "indication" not in allowed


def test_audit_enum_values_are_stable():
    """Regression guard — locked strings for DynamoDB compatibility."""
    assert AuditEventType.ORDERS_EXTRACTED.value == "orders_extracted"
    assert AuditEventType.ORDER_CONFIRMED.value == "order_confirmed"
    assert AuditEventType.ORDER_EDITED.value == "order_edited"
    assert AuditEventType.ORDER_CANCELLED.value == "order_cancelled"
