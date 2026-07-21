"""TE-4d — the video-import create resolves the template through the visit
context, the same way iOS's /sessions does.

Before this, `create_import_session` only honoured an explicit
`custom_template_id` and never called `resolve_context_template_key`, so a
web-uploaded encounter bypassed the clinician/org visit-type→template mapping
that an iPad recording gets. These tests pin the new precedence AND the
iOS-safety invariant: the shared resolver is REUSED, not modified, and is
called with exactly the fields /sessions passes.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.v1 import video_import as vi


def _consent_ok(**over):
    body = dict(specialty="general", consent_attested=True)
    body.update(over)
    return vi.CreateVideoImportRequest(**body)


async def _run(body, *, resolver=None, owned=None):
    """Drive create_import_session with all side-effecting deps mocked, and
    return the kwargs that reached `create_session`."""
    uid = uuid.uuid4()
    session = SimpleNamespace(id=uuid.uuid4(), import_source=None)
    job = SimpleNamespace(id=uuid.uuid4())
    create_session = AsyncMock(return_value=session)

    resolver = resolver or AsyncMock(return_value=(None, None, False))

    stack = [
        patch.object(vi, "create_session", create_session),
        patch.object(vi, "confirm_consent", AsyncMock()),
        patch.object(vi, "write_audit", AsyncMock()),
        patch.object(vi.jobs, "create_job", AsyncMock(return_value=job)),
        patch.object(
            vi, "generate_presigned_evidence_url",
            MagicMock(return_value="https://put"),
        ),
        patch(
            "app.modules.session.service.resolve_context_template_key", resolver
        ),
        patch(
            "app.modules.custom_templates.service.get_owned_or_shared",
            AsyncMock(return_value=owned),
        ),
    ]
    for p in stack:
        p.start()
    try:
        await vi.create_import_session(
            AsyncMock(), clinician_id=uid, actor_id=uid, body=body
        )
    finally:
        for p in reversed(stack):
            p.stop()

    return create_session.await_args.kwargs, resolver


@pytest.mark.asyncio
async def test_resolves_template_from_context():
    """AC-1 — context set, no explicit template → the shared resolver runs and
    its result is snapshotted onto the session."""
    tk = "musculoskeletal"
    ctid = uuid.uuid4()
    resolver = AsyncMock(return_value=(tk, ctid, False))

    kwargs, resolver = await _run(
        _consent_ok(consultation_type="follow_up", context_id="ctx_1a2b3c4d"),
        resolver=resolver,
    )

    resolver.assert_awaited_once()
    # Called with exactly what /sessions passes — the iOS-shared contract.
    rk = resolver.await_args.kwargs
    assert rk["consultation_type"] == "follow_up"
    assert rk["context_id"] == "ctx_1a2b3c4d"
    # …and the resolved template is what lands on the session.
    assert kwargs["template_key"] == tk
    assert kwargs["custom_template_id"] == ctid
    assert kwargs["context_id"] == "ctx_1a2b3c4d"


@pytest.mark.asyncio
async def test_explicit_custom_template_overrides_context():
    """AC-2 — an explicit custom_template_id wins; the resolver is NOT called
    (Uzziel: keep the direct picker as an override)."""
    owned = SimpleNamespace(id=uuid.uuid4())
    resolver = AsyncMock(return_value=("should_not_be_used", None, False))

    kwargs, resolver = await _run(
        _consent_ok(
            consultation_type="follow_up",
            context_id="ctx_1a2b3c4d",
            custom_template_id=str(uuid.uuid4()),
        ),
        resolver=resolver,
        owned=owned,
    )

    resolver.assert_not_awaited()
    assert kwargs["custom_template_id"] == owned.id
    assert kwargs["template_key"] is None


@pytest.mark.asyncio
async def test_no_context_is_byte_identical():
    """AC-3 — neither context nor custom template → specialty default, and the
    resolver is NOT called (byte-identical to pre-TE-4d)."""
    resolver = AsyncMock(return_value=("x", None, False))

    kwargs, resolver = await _run(_consent_ok(), resolver=resolver)

    resolver.assert_not_awaited()
    assert kwargs["template_key"] is None
    assert kwargs["custom_template_id"] is None
    assert kwargs["context_id"] is None


@pytest.mark.asyncio
async def test_consultation_type_without_context_still_resolves():
    """A visit type with no specific context still resolves (the visit type's
    default context / org default), matching /sessions."""
    resolver = AsyncMock(return_value=("emergency_medicine", None, False))

    kwargs, resolver = await _run(
        _consent_ok(consultation_type="new_patient"), resolver=resolver
    )

    resolver.assert_awaited_once()
    assert kwargs["template_key"] == "emergency_medicine"
