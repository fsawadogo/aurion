"""Unit tests for the EMR write-back orchestration + connector
abstraction (#57).

Covers:
  * stub connector returns a synthetic external id; never raises
  * registry maps `stub` correctly + lists known keys
  * orchestration service persists a row, transitions queued →
    sending → sent on success
  * connector raising `EmrConnectorError` → row.status = failed +
    error_reason set (no exception bubbles)
  * unexpected non-Error connector exception → defensive failed state
  * fingerprint = sha256 of the payload bytes
  * audit-event whitelists refuse PHI-bearing fields
"""

from __future__ import annotations

import hashlib
import uuid

import pytest

from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType
from app.modules.emr import service as emr_service
from app.modules.emr.base import (
    EmrConnector,
    EmrConnectorError,
    EmrSendResult,
)
from app.modules.emr.registry import (
    get_connector,
    get_default_connector,
    list_connector_keys,
    register_connector,
)
from app.modules.emr.stub import StubEmrConnector

# ── Registry ─────────────────────────────────────────────────────────────


def test_registry_has_stub():
    assert "stub" in list_connector_keys()


def test_registry_get_stub_returns_stub():
    c = get_connector("stub")
    assert isinstance(c, StubEmrConnector)
    assert c.key == "stub"


def test_registry_get_unknown_raises_keyerror():
    with pytest.raises(KeyError):
        get_connector("nonexistent_emr")


def test_registry_default_is_stub():
    c = get_default_connector()
    assert c.key == "stub"


def test_registry_register_replaces_or_adds():
    class _Fake(EmrConnector):
        key = "_test_fake"

        async def send(self, session_id: str, payload: bytes):
            return EmrSendResult(external_id="x")

    register_connector(_Fake())
    assert "_test_fake" in list_connector_keys()


# ── StubEmrConnector ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stub_returns_synthetic_external_id():
    c = StubEmrConnector()
    res = await c.send("session-abc", b"hello world")
    assert res.external_id.startswith("stub-session-abc-")
    assert res.raw_response_summary is not None
    assert "11 bytes" in res.raw_response_summary


@pytest.mark.asyncio
async def test_stub_never_raises_on_arbitrary_payload():
    """Stub is the safety floor — must not raise regardless of payload."""
    c = StubEmrConnector()
    for body in (b"", b"\x00\x01\x02", b"a" * 100_000):
        res = await c.send("s", body)
        assert res.external_id


# ── _fingerprint ─────────────────────────────────────────────────────────


def test_fingerprint_is_sha256_hex():
    payload = b"hello aurion"
    expected = hashlib.sha256(payload).hexdigest()
    assert emr_service._fingerprint(payload) == expected


def test_fingerprint_differs_per_payload():
    a = emr_service._fingerprint(b"a")
    b = emr_service._fingerprint(b"b")
    assert a != b


# ── _sanitize_error ──────────────────────────────────────────────────────


def test_sanitize_error_truncates_long_messages():
    long = "x" * 1000
    out = emr_service._sanitize_error(long)
    assert len(out) <= 520  # 500 + " …(truncated)"
    assert out.endswith("…(truncated)")


def test_sanitize_error_passthrough_short_messages():
    short = "Network timeout"
    assert emr_service._sanitize_error(short) == short


# ── EmrConnectorError ────────────────────────────────────────────────────


def test_connector_error_default_retryable():
    e = EmrConnectorError("network down")
    assert e.retryable is True


def test_connector_error_terminal_when_set():
    e = EmrConnectorError("bad payload", retryable=False)
    assert e.retryable is False


# ── Audit whitelists ─────────────────────────────────────────────────────


def test_audit_queued_refuses_payload_contents():
    """The audit row must NEVER carry the payload itself — only its
    fingerprint. The whole point of the design."""
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.EMR_WRITE_BACK_QUEUED]
    assert "payload" not in allowed
    assert "payload_fingerprint" in allowed
    # Connector identity is the trail anchor
    assert "connector" in allowed


def test_audit_sent_carries_external_id():
    """The EMR-side identifier IS audit-worthy (it's the chart link)."""
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.EMR_WRITE_BACK_SENT]
    assert "external_id" in allowed
    assert "attempt_count" in allowed
    assert "payload" not in allowed


def test_audit_failed_carries_error_reason_not_payload():
    """error_reason is the sanitized connector message; payload bytes
    must never end up in the audit row."""
    allowed = ALLOWED_AUDIT_KWARGS[AuditEventType.EMR_WRITE_BACK_FAILED]
    assert "error_reason" in allowed
    assert "payload" not in allowed


def test_audit_enum_values_are_stable():
    """Regression guard — locked strings for DynamoDB compatibility."""
    assert (
        AuditEventType.EMR_WRITE_BACK_QUEUED.value
        == "emr_write_back_queued"
    )
    assert (
        AuditEventType.EMR_WRITE_BACK_SENT.value == "emr_write_back_sent"
    )
    assert (
        AuditEventType.EMR_WRITE_BACK_FAILED.value
        == "emr_write_back_failed"
    )


# ── send_to_emr orchestration ────────────────────────────────────────────


class _FakeRow:
    """Minimal stand-in for EmrWriteBackModel used in unit tests.

    Mimics enough of the SQLAlchemy attribute behavior that the
    service can set attributes on it without a real session.
    """

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class _MockSession:
    """Minimal AsyncSession stand-in: capture .add()'d rows + no-op
    flush. The orchestration service only does add + flush + attribute
    set — no select against this session in send_to_emr."""

    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None


class _SuccessConnector(EmrConnector):
    key = "_test_success"

    async def send(self, session_id, payload):
        return EmrSendResult(external_id=f"ok-{session_id}")


class _RetryableFailConnector(EmrConnector):
    key = "_test_fail_retry"

    async def send(self, session_id, payload):
        raise EmrConnectorError("temporary network blip", retryable=True)


class _TerminalFailConnector(EmrConnector):
    key = "_test_fail_term"

    async def send(self, session_id, payload):
        raise EmrConnectorError("invalid auth", retryable=False)


class _UnexpectedExceptionConnector(EmrConnector):
    key = "_test_unexpected"

    async def send(self, session_id, payload):
        raise RuntimeError("connector did the wrong thing")


def _note_fixture():
    """Reuse the FHIR test fixture pattern."""
    from app.core.types import Note, NoteClaim, NoteSection

    return Note(
        session_id="22222222-2222-2222-2222-222222222222",
        stage=2,
        version=1,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        completeness_score=0.8,
        sections=[
            NoteSection(
                id="hpi",
                title="HPI",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c001",
                        text="Pain three weeks.",
                        source_type="transcript",
                        source_id="seg_1",
                    )
                ],
            ),
        ],
    )


@pytest.mark.asyncio
async def test_send_to_emr_success_path(monkeypatch):
    """Happy path: row.status flows queued → sending → sent;
    external_id set; sent_at set; attempt_count = 1."""
    register_connector(_SuccessConnector())
    db = _MockSession()
    session_id = uuid.uuid4()

    row = await emr_service.send_to_emr(
        session_id,
        _note_fixture(),
        author_user_id="user-1",
        external_reference_id=None,
        connector_key="_test_success",
        db=db,  # type: ignore[arg-type]
    )

    assert row.status == "sent"
    assert row.external_id == f"ok-{session_id}"
    assert row.sent_at is not None
    assert row.attempt_count == 1
    assert row.error_reason is None
    # Fingerprint is set and shaped like a sha256 hex digest
    assert len(row.payload_fingerprint) == 64
    assert all(c in "0123456789abcdef" for c in row.payload_fingerprint)


@pytest.mark.asyncio
async def test_send_to_emr_retryable_failure(monkeypatch):
    """Retryable connector error → row.status = failed; error_reason
    set; the orchestration function does NOT raise."""
    register_connector(_RetryableFailConnector())
    db = _MockSession()
    row = await emr_service.send_to_emr(
        uuid.uuid4(),
        _note_fixture(),
        author_user_id="user-1",
        external_reference_id=None,
        connector_key="_test_fail_retry",
        db=db,  # type: ignore[arg-type]
    )
    assert row.status == "failed"
    assert "temporary network blip" in row.error_reason
    assert row.sent_at is None


@pytest.mark.asyncio
async def test_send_to_emr_terminal_failure(monkeypatch):
    register_connector(_TerminalFailConnector())
    db = _MockSession()
    row = await emr_service.send_to_emr(
        uuid.uuid4(),
        _note_fixture(),
        author_user_id="user-1",
        external_reference_id=None,
        connector_key="_test_fail_term",
        db=db,  # type: ignore[arg-type]
    )
    assert row.status == "failed"
    assert "invalid auth" in row.error_reason


@pytest.mark.asyncio
async def test_send_to_emr_unknown_connector_raises_keyerror():
    db = _MockSession()
    with pytest.raises(KeyError):
        await emr_service.send_to_emr(
            uuid.uuid4(),
            _note_fixture(),
            author_user_id="user-1",
            external_reference_id=None,
            connector_key="not_a_real_connector",
            db=db,  # type: ignore[arg-type]
        )


@pytest.mark.asyncio
async def test_send_to_emr_unexpected_exception_lands_as_failed():
    """Connector contract is to raise EmrConnectorError; if it raises
    something else, we don't loop — we surface a sanitized
    failed-row."""
    register_connector(_UnexpectedExceptionConnector())
    db = _MockSession()
    row = await emr_service.send_to_emr(
        uuid.uuid4(),
        _note_fixture(),
        author_user_id="user-1",
        external_reference_id=None,
        connector_key="_test_unexpected",
        db=db,  # type: ignore[arg-type]
    )
    assert row.status == "failed"
    # Sanitized message — generic type, not the raw exception text
    assert "RuntimeError" in row.error_reason


@pytest.mark.asyncio
async def test_send_to_emr_uses_default_connector_when_key_none():
    """Connector key=None → falls back to the default (`stub`)."""
    db = _MockSession()
    row = await emr_service.send_to_emr(
        uuid.uuid4(),
        _note_fixture(),
        author_user_id="user-1",
        external_reference_id=None,
        connector_key=None,
        db=db,  # type: ignore[arg-type]
    )
    assert row.connector == "stub"
    assert row.status == "sent"  # stub never fails
