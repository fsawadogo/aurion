"""VID-02 — video-import route guards + create flow (no DB; mocked deps).

CI runs only tests/unit, so the flag gate, consent hard-gate, and status
mapping are exercised here with mocks. The end-to-end happy path (live PG +
moto) lives in tests/integration.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1 import video_import as vi
from app.core.audit_events import AuditEventType
from app.core.types import SessionState


def _cfg(enabled: bool) -> SimpleNamespace:
    return SimpleNamespace(feature_flags=SimpleNamespace(video_import_enabled=enabled))


def test_require_enabled_404_when_flag_off() -> None:
    with patch.object(vi, "get_config", return_value=_cfg(False)):
        with pytest.raises(HTTPException) as exc:
            vi._require_enabled()
    assert exc.value.status_code == 404


def test_require_enabled_passes_when_flag_on() -> None:
    with patch.object(vi, "get_config", return_value=_cfg(True)):
        assert vi._require_enabled() is None


@pytest.mark.asyncio
async def test_create_rejects_missing_consent_attestation() -> None:
    body = vi.CreateVideoImportRequest(specialty="general", consent_attested=False)
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        await vi.create_video_import(body, None, user, db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_create_sets_import_source_and_audits_attestation() -> None:
    body = vi.CreateVideoImportRequest(
        specialty="general", consent_attested=True, consent_method="written"
    )
    uid = uuid.uuid4()
    user = SimpleNamespace(user_id=uid)
    db = AsyncMock()
    session = SimpleNamespace(id=uuid.uuid4(), import_source=None)
    job = SimpleNamespace(id=uuid.uuid4())

    with patch.object(vi, "create_session", AsyncMock(return_value=session)), \
        patch.object(vi, "confirm_consent", AsyncMock()) as confirm, \
        patch.object(vi, "write_audit", AsyncMock()) as audit, \
        patch.object(vi.jobs, "create_job", AsyncMock(return_value=job)), \
        patch.object(
            vi, "generate_presigned_evidence_url", MagicMock(return_value="https://put")
        ):
        resp = await vi.create_video_import(body, None, user, db)

    assert session.import_source == "video_upload"
    confirm.assert_awaited_once()
    # Consent attestation is audited (the import substitute for the live gate).
    ev = audit.call_args
    assert ev.args[1] == AuditEventType.CONSENT_ATTESTED
    assert resp.session_id == str(session.id)
    assert resp.upload_url == "https://put"
    assert resp.s3_key.startswith(f"video-imports/{session.id}/")


@pytest.mark.asyncio
async def test_create_applies_owned_custom_template() -> None:
    """tpl-03: an owned custom_template_id is validated and forwarded to
    create_session (so the upload uses that template's structure + AI
    instructions)."""
    cid = uuid.uuid4()
    body = vi.CreateVideoImportRequest(
        specialty="general", consent_attested=True, custom_template_id=str(cid)
    )
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    session = SimpleNamespace(id=uuid.uuid4(), import_source=None)
    job = SimpleNamespace(id=uuid.uuid4())

    with patch.object(vi, "create_session", AsyncMock(return_value=session)) as create, \
        patch.object(vi, "confirm_consent", AsyncMock()), \
        patch.object(vi, "write_audit", AsyncMock()), \
        patch.object(vi.jobs, "create_job", AsyncMock(return_value=job)), \
        patch.object(
            vi, "generate_presigned_evidence_url", MagicMock(return_value="https://put")
        ), \
        patch(
            "app.modules.custom_templates.service.get_owned",
            AsyncMock(return_value=SimpleNamespace(id=cid)),
        ):
        await vi.create_video_import(body, None, user, db)

    assert create.call_args.kwargs["custom_template_id"] == cid


@pytest.mark.asyncio
async def test_create_rejects_unowned_custom_template() -> None:
    """tpl-03: a custom_template_id not owned by the clinician → 404, and no
    session is created."""
    body = vi.CreateVideoImportRequest(
        specialty="general", consent_attested=True, custom_template_id=str(uuid.uuid4())
    )
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    with patch.object(vi, "create_session", AsyncMock()) as create, \
        patch(
            "app.modules.custom_templates.service.get_owned",
            AsyncMock(return_value=None),
        ):
        with pytest.raises(HTTPException) as exc:
            await vi.create_video_import(body, None, user, db)
    assert exc.value.status_code == 404
    create.assert_not_awaited()


@pytest.mark.asyncio
async def test_admin_create_rejects_missing_consent() -> None:
    from app.api.v1.admin import video_import as avi

    body = avi.AdminCreateVideoImportRequest(specialty="general", consent_attested=False)
    actor = SimpleNamespace(user_id=uuid.uuid4())
    with pytest.raises(HTTPException) as exc:
        await avi.admin_create_video_import(body, None, actor, AsyncMock())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_admin_create_uses_on_behalf_and_auto_advance() -> None:
    from app.api.v1.admin import video_import as avi

    on_behalf = uuid.uuid4()
    actor = SimpleNamespace(user_id=uuid.uuid4())
    body = avi.AdminCreateVideoImportRequest(
        specialty="general", consent_attested=True,
        on_behalf_of_clinician_id=on_behalf,
    )
    db = AsyncMock()
    with patch.object(avi, "create_import_session", AsyncMock()) as create:
        await avi.admin_create_video_import(body, None, actor, db)

    _, kwargs = create.call_args
    assert kwargs["clinician_id"] == on_behalf
    assert kwargs["actor_id"] == actor.user_id
    assert kwargs["auto_advance_stage2"] is True


def test_status_response_maps_job_fields() -> None:
    session = SimpleNamespace(id=uuid.uuid4(), state=SessionState.AWAITING_REVIEW)
    job = SimpleNamespace(
        id=uuid.uuid4(), status="completed", frames_extracted=0, frames_masked=0,
        frames_dropped=0, raw_video_purged_at=object(), new_note_version=1,
        error_message=None,
    )
    resp = vi._status_response(session, job)
    assert resp.status == "completed"
    assert resp.session_state == SessionState.AWAITING_REVIEW.value
    assert resp.raw_video_purged is True
    assert resp.new_note_version == 1
