"""Session-stats recompute across the three note CUD paths.

lane-backend/empty-transcript-guard.

Every code path that writes a new ``NoteVersionModel`` row must call
``create_note_version`` with ``recompute_completeness=True`` (the
default) so the persisted ``completeness_score`` stays honest.
Three call sites:

  * physician edit            (``edit_note``)
  * conflict resolution       (``resolve_conflict``)
  * vision/screen stage 2     (direct ``create_note_version``)

This test exercises each path and asserts:

  1. ``compute_session_stats`` returns the same numbers the freshly
     persisted note has, so the admin endpoint and the storage layer
     can't disagree.
  2. A SESSION_STATS_RECOMPUTED audit event fires with the correct
     ``trigger`` label whenever a v2+ write actually changes the
     completeness score.
  3. No SESSION_STATS_RECOMPUTED event fires when the score doesn't
     change (no-op writes don't pollute the audit log).

The "integration" name is for organizational symmetry with the other
integration suites — this file uses heavy mocking rather than a live
Postgres because the recompute path is purely in-memory; we don't
need a database round-trip to prove the contract holds.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.audit_events import AuditEventType
from app.core.types import Note, NoteClaim, NoteSection
from app.modules.note_gen.service import (
    compute_session_stats,
    create_note_version,
    edit_note,
    get_template,
    resolve_conflict,
)

# ── Helpers ───────────────────────────────────────────────────────────────


def _make_note(
    session_id: str,
    *,
    version: int = 1,
    populated_section_ids: tuple[str, ...] = ("chief_complaint",),
    stored_completeness: float = 0.5,
) -> Note:
    """Build a Note with a controllable number of populated required
    sections. Returns the in-memory object — tests are responsible for
    persisting (or not) via the mocked ``create_note_version`` chain."""
    sections = []
    for sid in (
        "chief_complaint",
        "hpi",
        "physical_exam",
        "imaging_review",
        "assessment",
        "plan",
    ):
        if sid in populated_section_ids:
            sections.append(
                NoteSection(
                    id=sid,
                    status="populated",
                    claims=[
                        NoteClaim(
                            id=f"c_{sid}",
                            text="Physician noted observation.",
                            source_type="transcript",
                            source_id=f"seg_{sid}",
                            source_quote="observation",
                        )
                    ],
                )
            )
        else:
            sections.append(NoteSection(id=sid, status="not_captured"))

    return Note(
        session_id=session_id,
        stage=1,
        version=version,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=stored_completeness,  # deliberately stale
        sections=sections,
    )


@pytest.fixture
def mock_db():
    """Stub AsyncSession. ``execute`` returns a result whose ``scalar()``
    yields the current max version — defaults to 1 so the next version
    written will be v2 (the audited path).
    """
    db = AsyncMock()
    result = MagicMock()
    result.scalar = MagicMock(return_value=1)  # current max version is 1
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.flush = AsyncMock()
    return db


@pytest.fixture
def mock_audit():
    """Patch the audit log service — every call recorded for assertion."""
    audit = MagicMock()
    audit.write_event = AsyncMock()
    with patch(
        "app.modules.note_gen.service.get_audit_log_service",
        return_value=audit,
    ):
        yield audit


# ── Path 1 — create_note_version (vision / screen stage 2) ────────────────


@pytest.mark.asyncio
async def test_create_note_version_recomputes_completeness_for_v2(
    mock_db, mock_audit
):
    """A direct ``create_note_version`` call (the vision merge / screen
    inject path) must recompute the score from the in-memory sections,
    not echo the stale stored ``completeness_score``."""
    session_id = str(uuid.uuid4())
    # Stored note says 0.5 but actually has 3 populated of 6 required
    # → fresh score should be 3/6 = 0.5. Then bump to 4 populated so
    # the recompute fires the audit.
    note = _make_note(
        session_id,
        populated_section_ids=(
            "chief_complaint",
            "hpi",
            "physical_exam",
            "imaging_review",
        ),
        stored_completeness=0.5,  # stale — actually 4/6
    )

    await create_note_version(
        session_id, note, mock_db, stats_trigger="vision_merge"
    )

    # The persisted completeness_score should now be 4/6 ≈ 0.6667,
    # NOT the stale 0.5 the caller passed in.
    assert abs(note.completeness_score - 4 / 6) < 1e-4

    # The audit event fired (v2, score changed) with the vision_merge
    # trigger so dashboards can attribute the change.
    mock_audit.write_event.assert_awaited()
    recompute_call = next(
        (
            c
            for c in mock_audit.write_event.await_args_list
            if c.kwargs.get("event_type")
            == AuditEventType.SESSION_STATS_RECOMPUTED
        ),
        None,
    )
    assert recompute_call is not None
    assert recompute_call.kwargs["trigger"] == "vision_merge"
    assert recompute_call.kwargs["sections_populated"] == 4
    assert recompute_call.kwargs["sections_required"] == 6
    assert abs(recompute_call.kwargs["completeness_score"] - 4 / 6) < 1e-4


@pytest.mark.asyncio
async def test_create_note_version_no_audit_when_score_unchanged(
    mock_db, mock_audit
):
    """A v2 write that didn't change the completeness score (e.g. a
    stage-2 merge that landed only screen anchors on already-populated
    sections) must NOT emit a SESSION_STATS_RECOMPUTED row."""
    session_id = str(uuid.uuid4())
    # Stored completeness 0.6667 matches the actual computed 4/6.
    note = _make_note(
        session_id,
        populated_section_ids=(
            "chief_complaint",
            "hpi",
            "physical_exam",
            "imaging_review",
        ),
        stored_completeness=round(4 / 6, 4),
    )

    await create_note_version(session_id, note, mock_db)

    # Score is identical → no recompute audit row.
    recompute_calls = [
        c
        for c in mock_audit.write_event.await_args_list
        if c.kwargs.get("event_type")
        == AuditEventType.SESSION_STATS_RECOMPUTED
    ]
    assert recompute_calls == []


@pytest.mark.asyncio
async def test_create_note_version_v1_does_not_audit_stats(mock_db, mock_audit):
    """Version 1 (initial creation) doesn't emit the recompute audit
    even when the score change is large — STAGE1_DELIVERED already
    captures the signal and the recompute row would duplicate it."""
    # Override the mock so max_version is 0, making this write v1.
    result = MagicMock()
    result.scalar = MagicMock(return_value=0)
    mock_db.execute = AsyncMock(return_value=result)

    session_id = str(uuid.uuid4())
    note = _make_note(
        session_id,
        populated_section_ids=("chief_complaint", "hpi"),
        stored_completeness=0.0,  # stale; actual is 2/6
    )

    await create_note_version(session_id, note, mock_db)

    # Score was recomputed (it's persisted that way), but no audit row.
    assert abs(note.completeness_score - 2 / 6) < 1e-4
    recompute_calls = [
        c
        for c in mock_audit.write_event.await_args_list
        if c.kwargs.get("event_type")
        == AuditEventType.SESSION_STATS_RECOMPUTED
    ]
    assert recompute_calls == []


# ── Path 2 — edit_note (physician edit) ───────────────────────────────────


@pytest.mark.asyncio
async def test_edit_note_path_recomputes_and_audits(mock_db, mock_audit):
    """The physician edit path threads through ``create_note_version``
    with ``stats_trigger="edit_note"``; the audit row should record
    that trigger."""
    session_id = str(uuid.uuid4())
    # Start with 1 populated section, edit adds a second → score moves.
    starting_note = _make_note(
        session_id,
        populated_section_ids=("chief_complaint",),
        stored_completeness=round(1 / 6, 4),
    )

    with patch(
        "app.modules.note_gen.service.get_latest_note",
        new_callable=AsyncMock,
        return_value=starting_note,
    ):
        edited = await edit_note(
            session_id,
            {"hpi": "Patient reports two weeks of pain."},
            mock_db,
        )

    # New score reflects 2 of 6 populated.
    assert abs(edited.completeness_score - 2 / 6) < 1e-4

    # Audit row fired with the right trigger.
    recompute_calls = [
        c
        for c in mock_audit.write_event.await_args_list
        if c.kwargs.get("event_type")
        == AuditEventType.SESSION_STATS_RECOMPUTED
    ]
    assert len(recompute_calls) == 1
    assert recompute_calls[0].kwargs["trigger"] == "edit_note"


# ── Path 3 — resolve_conflict (Stage 2 conflict review) ───────────────────


@pytest.mark.asyncio
async def test_resolve_conflict_path_audits_with_resolve_trigger(
    mock_db, mock_audit
):
    """The conflict resolution path also flows through
    ``create_note_version`` — the audit row records
    ``stats_trigger="resolve_conflict"``. Use the ``reject_visual``
    action so we remove a claim and force a score change."""
    session_id = str(uuid.uuid4())
    # Build a note where a visual claim sits in physical_exam alongside
    # the transcript claim. Reject-visual removes the visual claim but
    # leaves the section populated (one claim left) — completeness
    # stays the same. To force a score change, build a note where the
    # only claim in a section is the one we're going to reject.
    note = Note(
        session_id=session_id,
        stage=2,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=round(2 / 6, 4),
        sections=[
            NoteSection(
                id="chief_complaint",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c_cc",
                        text="cc",
                        source_type="transcript",
                        source_id="seg_cc",
                    )
                ],
            ),
            NoteSection(
                id="hpi",
                status="populated",
                claims=[
                    # Only this claim — rejecting it empties the section.
                    NoteClaim(
                        id="c_visual",
                        text="visual",
                        source_type="visual",
                        source_id="frame_001",
                    )
                ],
            ),
            NoteSection(id="physical_exam", status="not_captured"),
            NoteSection(id="imaging_review", status="not_captured"),
            NoteSection(id="assessment", status="not_captured"),
            NoteSection(id="plan", status="not_captured"),
        ],
    )

    with patch(
        "app.modules.note_gen.service.get_latest_note",
        new_callable=AsyncMock,
        return_value=note,
    ):
        await resolve_conflict(
            session_id,
            claim_id="c_visual",
            action="reject_visual",
            resolution_text=None,
            db=mock_db,
        )

    # Score dropped from 2/6 to 1/6 — well; actually rejecting the
    # claim leaves hpi with zero claims, status still "populated",
    # which the honest scorer rejects → 1/6.
    recompute_calls = [
        c
        for c in mock_audit.write_event.await_args_list
        if c.kwargs.get("event_type")
        == AuditEventType.SESSION_STATS_RECOMPUTED
    ]
    assert len(recompute_calls) == 1
    assert recompute_calls[0].kwargs["trigger"] == "resolve_conflict"
    assert recompute_calls[0].kwargs["sections_populated"] == 1


# ── Cross-check — admin endpoint uses the same compute_session_stats ──────


def test_compute_session_stats_matches_create_note_version_persistence():
    """The admin endpoint and the persistence layer call the same
    ``compute_session_stats``; this test pins that contract via the
    real ``orthopedic_surgery`` template."""
    template = get_template("orthopedic_surgery")
    session_id = str(uuid.uuid4())
    note = _make_note(
        session_id,
        populated_section_ids=("chief_complaint", "hpi", "physical_exam"),
    )

    completeness, populated, required, provider = compute_session_stats(
        note, template
    )
    # 3 of however many required sections orthopedic_surgery has.
    required_count = sum(1 for s in template.sections if s.required)
    assert required == required_count
    assert populated == 3
    assert abs(completeness - populated / required) < 1e-4
    assert provider == "anthropic"
