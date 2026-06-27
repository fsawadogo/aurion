"""Unit tests for the admin shared/org templates surface (tpl-04).

Calls the route coroutines directly with a MagicMock admin + AsyncMock db and
patches the custom-templates service + audit, mirroring test_video_import_routes.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.v1.admin import shared_templates as st
from app.core.audit_events import AuditEventType


def _body() -> st.SharedTemplateCreateRequest:
    return st.SharedTemplateCreateRequest(
        template={
            "key": "org_ll",
            "display_name": "Org Lower Limb",
            "version": "1.0",
            "sections": [{"id": "cc", "title": "CC", "required": True}],
        }
    )


def _row(**over):
    base = dict(
        id=uuid.uuid4(),
        key="org_ll",
        display_name="Org Lower Limb",
        version="1.0",
        owner_id=uuid.uuid4(),
        is_shared=True,
        content='{"key":"org_ll","display_name":"Org Lower Limb","version":"1.0","sections":[]}',
        created_at=SimpleNamespace(isoformat=lambda: "2026-06-26T00:00:00Z"),
        updated_at=SimpleNamespace(isoformat=lambda: "2026-06-26T00:00:00Z"),
    )
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_create_marks_shared_and_audits() -> None:
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    audit = MagicMock()
    audit.write_event = AsyncMock()
    with patch.object(
        st.svc, "create_for_owner", AsyncMock(return_value=_row(owner_id=user.user_id))
    ) as create, patch.object(
        st, "get_audit_log_service", MagicMock(return_value=audit)
    ):
        resp = await st.create_shared_template(_body(), user=user, db=db)

    # is_shared=True is forwarded to the shared service path.
    assert create.call_args.kwargs["is_shared"] is True
    assert resp.is_shared is True
    ev = audit.write_event.call_args.kwargs
    assert ev["event_type"] == AuditEventType.CUSTOM_TEMPLATE_CREATED
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_rejects_bad_template_400() -> None:
    """The schema + descriptive-mode gate is reused — a rejected template → 400."""
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    with patch.object(
        st.svc,
        "create_for_owner",
        AsyncMock(side_effect=st.svc.CustomTemplateError("bad")),
    ):
        with pytest.raises(HTTPException) as exc:
            await st.create_shared_template(_body(), user=user, db=db)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_404_when_not_a_shared_row() -> None:
    """Delete only touches shared rows — a missing/non-shared id → 404, no delete
    (so this path can't reach a clinician's private template)."""
    user = SimpleNamespace(user_id=uuid.uuid4())
    db = AsyncMock()
    with patch.object(st.svc, "get_shared", AsyncMock(return_value=None)), patch.object(
        st.svc, "delete_owned", AsyncMock()
    ) as delete:
        with pytest.raises(HTTPException) as exc:
            await st.delete_shared_template(uuid.uuid4(), user=user, db=db)
    assert exc.value.status_code == 404
    delete.assert_not_awaited()
