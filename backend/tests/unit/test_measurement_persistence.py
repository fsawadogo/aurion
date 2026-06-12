"""#63 persistence slice — ingest/list endpoint + repository + erasure wiring.

Locks the load-bearing behaviour of the measurement-capture endpoint:
the feature gate (ships dark), the allowed-method + confidence-floor
guards, body/path session agreement, idempotent persistence (a retried
POST must not double-audit), PHI discipline in the audit kwargs (the
numeric *value* is never written), and that a measurement row is a
session child hard-deleted with its session.

Route handlers are exercised directly with mocked dependencies, matching
the project's other route tests (test_session_discard.py).
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import me_measurements as route
from app.core.audit_events import AuditEventType
from app.core.types import MeasurementCitation, Note, NoteSection

# ── helpers ──────────────────────────────────────────────────────────────────


def _note(session_id: uuid.UUID, specialty: str, *section_ids: str) -> Note:
    return Note(
        session_id=str(session_id), stage=1, provider_used="anthropic",
        specialty=specialty,
        sections=[NoteSection(id=sid, title=sid) for sid in section_ids],
    )


def _cfg(*, enabled: bool = True, methods=None, min_confidence: str = "medium"):
    """A config double exposing only what the endpoint reads."""
    return SimpleNamespace(
        feature_flags=SimpleNamespace(measurement_enabled=enabled),
        measurement=SimpleNamespace(
            methods_allowed=methods
            if methods is not None
            else ["arkit_lidar", "arkit_world", "ar_goniometer"],
            min_confidence=min_confidence,
        ),
    )


def _citation(session_id: str, *, method="arkit_lidar", confidence="high",
              confirmed=True, kind="wound_length", unit="mm",
              value=42.0) -> MeasurementCitation:
    return MeasurementCitation(
        measurement_id="meas_001", session_id=session_id, frame_id="frame_00214",
        kind=kind, value=value, unit=unit, method=method, confidence=confidence,
        confidence_reason="stable tracking", scale_source="lidar_depth",
        physician_confirmed=confirmed,
    )


def _row(session_id: uuid.UUID, *, confirmed=True) -> MagicMock:
    """A persisted-row double with exactly the attrs _to_citation reads."""
    return MagicMock(
        measurement_id="meas_001", session_id=session_id, frame_id="frame_00214",
        kind="wound_length", value=42.0, unit="mm", method="arkit_lidar",
        confidence="high", confidence_reason="stable tracking",
        scale_source="lidar_depth", masking_status="confirmed",
        physician_confirmed=confirmed, provider_used="on_device",
        model_version="meas-1.0",
    )


def _user() -> MagicMock:
    return MagicMock(user_id=uuid.uuid4())


# ── ingest: gating ────────────────────────────────────────────────────────────


class TestIngestGating:
    @pytest.mark.asyncio
    async def test_feature_disabled_403_no_persist_no_audit(self):
        sid = uuid.uuid4()
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config", return_value=_cfg(enabled=False)), \
             patch.object(route.measurement_repo, "persist", AsyncMock()) as persist, \
             patch.object(route, "write_audit", AsyncMock()) as audit:
            with pytest.raises(HTTPException) as exc:
                await route.ingest_measurement(
                    sid, _citation(str(sid)), user=_user(), db=AsyncMock()
                )
        assert exc.value.status_code == 403
        persist.assert_not_awaited()
        audit.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_disallowed_method_422(self):
        sid = uuid.uuid4()
        # ar_goniometer is a valid schema method but excluded from this config.
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config",
                          return_value=_cfg(methods=["arkit_lidar"])), \
             patch.object(route.measurement_repo, "persist", AsyncMock()) as persist:
            with pytest.raises(HTTPException) as exc:
                await route.ingest_measurement(
                    sid,
                    _citation(str(sid), method="ar_goniometer",
                              kind="rom_angle", unit="deg", value=35),
                    user=_user(), db=AsyncMock(),
                )
        assert exc.value.status_code == 422
        persist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confidence_below_floor_422(self):
        sid = uuid.uuid4()
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config",
                          return_value=_cfg(min_confidence="high")), \
             patch.object(route.measurement_repo, "persist", AsyncMock()) as persist:
            with pytest.raises(HTTPException) as exc:
                await route.ingest_measurement(
                    sid, _citation(str(sid), confidence="medium"),
                    user=_user(), db=AsyncMock(),
                )
        assert exc.value.status_code == 422
        persist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_body_path_session_mismatch_400(self):
        sid = uuid.uuid4()
        other = uuid.uuid4()
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config", return_value=_cfg()), \
             patch.object(route.measurement_repo, "persist", AsyncMock()) as persist:
            with pytest.raises(HTTPException) as exc:
                await route.ingest_measurement(
                    sid, _citation(str(other)), user=_user(), db=AsyncMock()
                )
        assert exc.value.status_code == 400
        persist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_non_owner_propagates_404_before_anything(self):
        sid = uuid.uuid4()
        with patch.object(route, "get_owned_session_or_404",
                          AsyncMock(side_effect=HTTPException(404, "nope"))), \
             patch.object(route, "get_config", return_value=_cfg()) as cfg, \
             patch.object(route.measurement_repo, "persist", AsyncMock()) as persist:
            with pytest.raises(HTTPException) as exc:
                await route.ingest_measurement(
                    sid, _citation(str(sid)), user=_user(), db=AsyncMock()
                )
        assert exc.value.status_code == 404
        cfg.assert_not_called()  # ownership is checked first
        persist.assert_not_awaited()


# ── ingest: happy path + idempotency ──────────────────────────────────────────


class TestIngestPersist:
    @pytest.mark.asyncio
    async def test_created_audits_generated_and_reviewed_and_commits(self):
        sid = uuid.uuid4()
        db = AsyncMock()
        row = _row(sid, confirmed=True)
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config", return_value=_cfg()), \
             patch.object(route.measurement_repo, "persist",
                          AsyncMock(return_value=(row, True))), \
             patch.object(route, "get_latest_note", AsyncMock(return_value=None)), \
             patch.object(route, "create_note_version", AsyncMock()) as version, \
             patch.object(route, "write_audit", AsyncMock()) as audit:
            result = await route.ingest_measurement(
                sid, _citation(str(sid)), user=_user(), db=db
            )

        assert isinstance(result, MeasurementCitation)
        assert result.measurement_id == "meas_001"
        db.commit.assert_awaited_once()
        # Two events: GENERATED, then REVIEWED (physician_confirmed=True).
        events = [c.args[1] for c in audit.call_args_list]
        assert events == [
            AuditEventType.MEASUREMENT_GENERATED,
            AuditEventType.MEASUREMENT_REVIEWED,
        ]
        # PHI guard: the numeric value is never an audit kwarg.
        for c in audit.call_args_list:
            assert "value" not in c.kwargs
        # No note yet → nothing to inject into, no version written.
        version.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_confirmed_with_note_injects_claim_and_writes_version(self):
        sid = uuid.uuid4()
        note = _note(sid, "plastic_surgery", "wound_assessment")
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config", return_value=_cfg()), \
             patch.object(route.measurement_repo, "persist",
                          AsyncMock(return_value=(_row(sid, confirmed=True), True))), \
             patch.object(route, "get_latest_note", AsyncMock(return_value=note)), \
             patch.object(route, "create_note_version", AsyncMock()) as version, \
             patch.object(route, "write_audit", AsyncMock()):
            await route.ingest_measurement(
                sid, _citation(str(sid)), user=_user(), db=AsyncMock()
            )

        # The real inject ran on the note: a measurement claim landed in the
        # routed section, and a new version was written.
        section = note.get_section("wound_assessment")
        assert len(section.claims) == 1
        assert section.claims[0].source_type == "measurement"
        assert section.claims[0].source_id == "meas_001"
        version.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_confirmed_with_note_but_no_target_section_skips_version(self):
        sid = uuid.uuid4()
        note = _note(sid, "general", "chief_complaint")
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config", return_value=_cfg()), \
             patch.object(route.measurement_repo, "persist",
                          AsyncMock(return_value=(_row(sid, confirmed=True), True))), \
             patch.object(route, "get_latest_note", AsyncMock(return_value=note)), \
             patch.object(route, "create_note_version", AsyncMock()) as version, \
             patch.object(route, "write_audit", AsyncMock()):
            await route.ingest_measurement(
                sid, _citation(str(sid)), user=_user(), db=AsyncMock()
            )

        assert note.get_section("chief_complaint").claims == []
        version.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unconfirmed_audits_generated_only(self):
        sid = uuid.uuid4()
        row = _row(sid, confirmed=False)
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config", return_value=_cfg()), \
             patch.object(route.measurement_repo, "persist",
                          AsyncMock(return_value=(row, True))), \
             patch.object(route, "write_audit", AsyncMock()) as audit:
            await route.ingest_measurement(
                sid, _citation(str(sid), confirmed=False), user=_user(), db=AsyncMock()
            )
        events = [c.args[1] for c in audit.call_args_list]
        assert events == [AuditEventType.MEASUREMENT_GENERATED]

    @pytest.mark.asyncio
    async def test_reingest_existing_does_not_double_audit_or_commit(self):
        sid = uuid.uuid4()
        db = AsyncMock()
        row = _row(sid)
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route, "get_config", return_value=_cfg()), \
             patch.object(route.measurement_repo, "persist",
                          AsyncMock(return_value=(row, False))), \
             patch.object(route, "write_audit", AsyncMock()) as audit:
            result = await route.ingest_measurement(
                sid, _citation(str(sid)), user=_user(), db=db
            )
        assert result.measurement_id == "meas_001"
        audit.assert_not_awaited()
        db.commit.assert_not_awaited()


# ── list ──────────────────────────────────────────────────────────────────────


class TestListMeasurements:
    @pytest.mark.asyncio
    async def test_lists_owned_session_measurements(self):
        sid = uuid.uuid4()
        rows = [_row(sid), _row(sid)]
        with patch.object(route, "get_owned_session_or_404", AsyncMock()), \
             patch.object(route.measurement_repo, "list_for_session",
                          AsyncMock(return_value=rows)):
            out = await route.list_measurements(sid, user=_user(), db=AsyncMock())
        assert len(out) == 2
        assert all(isinstance(c, MeasurementCitation) for c in out)

    @pytest.mark.asyncio
    async def test_list_non_owner_404(self):
        sid = uuid.uuid4()
        with patch.object(route, "get_owned_session_or_404",
                          AsyncMock(side_effect=HTTPException(404, "nope"))), \
             patch.object(route.measurement_repo, "list_for_session",
                          AsyncMock()) as lister:
            with pytest.raises(HTTPException) as exc:
                await route.list_measurements(sid, user=_user(), db=AsyncMock())
        assert exc.value.status_code == 404
        lister.assert_not_awaited()


# ── repository idempotency ────────────────────────────────────────────────────


class TestRepositoryPersist:
    @pytest.mark.asyncio
    async def test_persist_new_row_forces_certified_false(self):
        from app.modules.measurement import repository

        sid = uuid.uuid4()
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
        )
        added = {}
        db.add = MagicMock(side_effect=lambda row: added.setdefault("row", row))

        row, created = await repository.persist(db, sid, _citation(str(sid)))
        assert created is True
        db.flush.assert_awaited_once()
        assert added["row"].certified_measurement is False
        assert added["row"].session_id == sid

    @pytest.mark.asyncio
    async def test_persist_existing_returns_untouched(self):
        from app.modules.measurement import repository

        sid = uuid.uuid4()
        existing = _row(sid)
        db = AsyncMock()
        db.execute = AsyncMock(
            return_value=MagicMock(
                scalar_one_or_none=MagicMock(return_value=existing)
            )
        )
        db.add = MagicMock()

        row, created = await repository.persist(db, sid, _citation(str(sid)))
        assert created is False
        assert row is existing
        db.add.assert_not_called()
        db.flush.assert_not_awaited()


# ── erasure wiring ────────────────────────────────────────────────────────────


def test_measurement_rows_are_session_children_for_erasure():
    """A measurement row is derived PHI; deleting a session must delete it."""
    from app.core.models import MeasurementCitationModel
    from app.modules.session.service import _SESSION_CHILD_MODELS

    assert MeasurementCitationModel in _SESSION_CHILD_MODELS
