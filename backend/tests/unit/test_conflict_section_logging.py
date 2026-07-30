"""Conflict-choice logging carries the note section (correction-memory seed).

The physician's audio-vs-video resolution was already audited; this locks the
added dimension — the section id — that makes the choice mineable per-physician
per-section for later auto-resolution ("for exam conflicts, she keeps visual").
The section id is a structural label, never PHI.
"""

from __future__ import annotations

from app.core.audit_events import (
    ALLOWED_AUDIT_KWARGS,
    AuditEventType,
    validate_audit_kwargs,
)


def test_section_id_is_allowed_on_conflict_resolved() -> None:
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.CONFLICT_RESOLVED]
    assert "section_id" in allowed
    # The pre-existing dimensions must survive.
    assert {"claim_id", "action", "new_version"} <= allowed


def test_full_mineable_event_has_no_unknown_kwargs() -> None:
    unknown = validate_audit_kwargs(
        AuditEventType.CONFLICT_RESOLVED,
        {"claim_id", "action", "new_version", "section_id"},
    )
    assert unknown == set()


def test_event_without_section_id_still_clean() -> None:
    # Best-effort: a lookup miss omits section_id; the event must still be
    # kwarg-clean so a resolution is never blocked on the optional dimension.
    unknown = validate_audit_kwargs(
        AuditEventType.CONFLICT_RESOLVED,
        {"claim_id", "action", "new_version"},
    )
    assert unknown == set()


def test_unknown_kwarg_still_flagged() -> None:
    # The allow-list stays a gate — section_id widened it by exactly one key,
    # not into a free-for-all (no PHI smuggling into the immutable log).
    unknown = validate_audit_kwargs(
        AuditEventType.CONFLICT_RESOLVED,
        {"claim_id", "action", "patient_name"},
    )
    assert unknown == {"patient_name"}
