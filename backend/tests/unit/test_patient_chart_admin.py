"""Tests for the cross-clinician Patient Chart admin routes (#604).

Elevated-role (CLINICAL_ADMIN/ADMIN), flag-dark surface:
  * GET  /admin/patients/{identifier}/encounters — aggregate ALL clinicians'
    sessions for a patient identifier, with attribution + note status.
  * POST /admin/patients/notes/{session_id}/validate — supervisory sign-off
    of any clinician's note, reusing approve_note (which since #606 refuses
    to sign off over unresolved Stage 2 conflicts).

DB + config + service calls are mocked (unit-level), matching the project's
other route tests. The flag gate and the cross-clinician query shape are the
load-bearing behaviours here.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1.admin import patient_chart
from app.core.audit_events import AuditEventType
from app.core.types import SessionState


def _flag(enabled: bool) -> MagicMock:
    cfg = MagicMock()
    cfg.feature_flags.cross_clinician_chart_enabled = enabled
    return cfg


def _session(
    state: SessionState = SessionState.PROCESSING_STAGE2,
    clinician_id: uuid.UUID | None = None,
) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.clinician_id = clinician_id or uuid.uuid4()
    s.state = state
    s.specialty = "orthopedic_surgery"
    s.created_at = MagicMock(isoformat=lambda: "2026-07-01T00:00:00")
    return s


# ── flag gate ──────────────────────────────────────────────────────────────


class TestFlagGate:
    @pytest.mark.asyncio
    async def test_encounters_404_when_flag_off(self):
        with patch.object(patient_chart, "get_config", return_value=_flag(False)):
            with pytest.raises(patient_chart.HTTPException) as exc:
                await patient_chart.list_patient_encounters(
                    "MRN-1", _user=MagicMock(), db=AsyncMock()
                )
        assert exc.value.status_code == 404

    @pytest.mark.asyncio
    async def test_validate_404_when_flag_off(self):
        with patch.object(patient_chart, "get_config", return_value=_flag(False)):
            with pytest.raises(patient_chart.HTTPException) as exc:
                await patient_chart.validate_note(
                    uuid.uuid4(), actor=MagicMock(user_id=uuid.uuid4()), db=AsyncMock()
                )
        assert exc.value.status_code == 404


# ── encounters query ─────────────────────────────────────────────────────────


class TestEncounters:
    @pytest.mark.asyncio
    async def test_aggregates_across_clinicians_with_attribution(self):
        clin_a, clin_b = uuid.uuid4(), uuid.uuid4()
        s1 = _session(clinician_id=clin_a)
        s2 = _session(clinician_id=clin_b)

        db = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = [s1, s2]
        db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: scalars))

        latest = MagicMock(version=3, stage=2, is_approved=True)
        with patch.object(patient_chart, "get_config", return_value=_flag(True)), \
             patch.object(patient_chart, "hash_identifier", return_value=b"hash"), \
             patch.object(patient_chart.note_repo, "get_latest_versions_by_session",
                          AsyncMock(return_value={s1.id: latest})), \
             patch.object(patient_chart, "resolve_clinician_names",
                          AsyncMock(return_value={
                              str(clin_a): "Dr. A", str(clin_b): "Dr. B"})):
            rows = await patient_chart.list_patient_encounters(
                "MRN-1", _user=MagicMock(), db=db
            )

        assert [r.clinician_name for r in rows] == ["Dr. A", "Dr. B"]
        # s1 has a note version; s2 has none → zeros.
        assert rows[0].note_version == 3 and rows[0].is_approved is True
        assert rows[1].note_version == 0 and rows[1].is_approved is False

    @pytest.mark.asyncio
    async def test_query_has_no_clinician_owner_filter(self):
        """The whole point of #604: the query filters on the identifier
        hash ONLY — no clinician_id predicate — so it spans all staff."""
        db = AsyncMock()
        scalars = MagicMock()
        scalars.all.return_value = []
        db.execute = AsyncMock(return_value=MagicMock(scalars=lambda: scalars))

        with patch.object(patient_chart, "get_config", return_value=_flag(True)), \
             patch.object(patient_chart, "hash_identifier", return_value=b"hash"):
            result = await patient_chart.list_patient_encounters(
                "MRN-1", _user=MagicMock(), db=db
            )

        assert result == []
        # Inspect the compiled WHERE clause ONLY (not the SELECT column list,
        # which lists every column incl. clinician_id): it must filter on the
        # identifier hash and carry NO clinician_id predicate.
        stmt = db.execute.call_args[0][0]
        where_sql = str(stmt.whereclause).lower()
        assert "external_reference_id_hash" in where_sql
        assert "clinician_id" not in where_sql

    @pytest.mark.asyncio
    async def test_blank_identifier_422(self):
        with patch.object(patient_chart, "get_config", return_value=_flag(True)):
            with pytest.raises(patient_chart.HTTPException) as exc:
                await patient_chart.list_patient_encounters(
                    "   ", _user=MagicMock(), db=AsyncMock()
                )
        assert exc.value.status_code == 422


# ── supervisory validate ─────────────────────────────────────────────────────


class TestValidate:
    @pytest.mark.asyncio
    async def test_validates_other_clinicians_note_and_audits(self):
        session = _session(state=SessionState.PROCESSING_STAGE2)
        actor = MagicMock(user_id=uuid.uuid4())  # NOT the session owner
        approved = MagicMock(version=2, stage=2)
        db = AsyncMock()

        with patch.object(patient_chart, "get_config", return_value=_flag(True)), \
             patch.object(patient_chart, "get_session_or_404",
                          AsyncMock(return_value=session)), \
             patch.object(patient_chart, "approve_note",
                          AsyncMock(return_value=approved)), \
             patch.object(patient_chart, "transition_session",
                          AsyncMock()) as trans, \
             patch.object(patient_chart, "write_audit", AsyncMock()) as audit:
            result = await patient_chart.validate_note(
                session.id, actor=actor, db=db
            )

        assert result.approved is True and result.version == 2
        trans.assert_awaited_once()  # → REVIEW_COMPLETE
        args, kwargs = audit.call_args
        assert args[1] == AuditEventType.NOTE_VALIDATED
        assert kwargs["actor_id"] == str(actor.user_id)
        assert kwargs["target_clinician_id"] == str(session.clinician_id)
        assert kwargs["version"] == 2

    @pytest.mark.asyncio
    async def test_unresolved_conflict_maps_to_409(self):
        session = _session(state=SessionState.PROCESSING_STAGE2)
        db = AsyncMock()
        err = patient_chart.UnresolvedConflictError(["physical_exam"], ["conflict_1"])

        with patch.object(patient_chart, "get_config", return_value=_flag(True)), \
             patch.object(patient_chart, "get_session_or_404",
                          AsyncMock(return_value=session)), \
             patch.object(patient_chart, "approve_note",
                          AsyncMock(side_effect=err)), \
             patch.object(patient_chart, "write_audit", AsyncMock()) as audit:
            with pytest.raises(patient_chart.HTTPException) as exc:
                await patient_chart.validate_note(
                    session.id, actor=MagicMock(user_id=uuid.uuid4()), db=db
                )

        assert exc.value.status_code == 409
        audit.assert_not_awaited()  # never audited a sign-off that didn't happen

    @pytest.mark.asyncio
    async def test_wrong_state_409_before_approve(self):
        session = _session(state=SessionState.RECORDING)
        db = AsyncMock()
        with patch.object(patient_chart, "get_config", return_value=_flag(True)), \
             patch.object(patient_chart, "get_session_or_404",
                          AsyncMock(return_value=session)), \
             patch.object(patient_chart, "approve_note",
                          AsyncMock()) as approve:
            with pytest.raises(patient_chart.HTTPException) as exc:
                await patient_chart.validate_note(
                    session.id, actor=MagicMock(user_id=uuid.uuid4()), db=db
                )
        assert exc.value.status_code == 409
        approve.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_already_review_complete_skips_transition(self):
        session = _session(state=SessionState.REVIEW_COMPLETE)
        approved = MagicMock(version=4, stage=2)
        db = AsyncMock()
        with patch.object(patient_chart, "get_config", return_value=_flag(True)), \
             patch.object(patient_chart, "get_session_or_404",
                          AsyncMock(return_value=session)), \
             patch.object(patient_chart, "approve_note",
                          AsyncMock(return_value=approved)), \
             patch.object(patient_chart, "transition_session",
                          AsyncMock()) as trans, \
             patch.object(patient_chart, "write_audit", AsyncMock()):
            result = await patient_chart.validate_note(
                session.id, actor=MagicMock(user_id=uuid.uuid4()), db=db
            )
        assert result.approved is True
        trans.assert_not_awaited()  # already terminal — no re-transition
