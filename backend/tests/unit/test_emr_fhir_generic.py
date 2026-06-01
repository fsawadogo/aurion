"""Unit tests for the generic FHIR EMR connector (#57 follow-up).

Locks:
  * `from_env` returns None when endpoint is not set; concrete
    instance when it is
  * Bearer header is set when token present, omitted when absent
  * 201 + body with `id` → EmrSendResult(external_id=id)
  * 201 + Location header (no body id) → id extracted from header
  * 2xx but no id anywhere → synthetic placeholder, never raises
  * 401/403 → terminal EmrConnectorError
  * 400/404/422 → terminal EmrConnectorError
  * 500/503 → retryable EmrConnectorError
  * Connection error → retryable
  * Timeout → retryable
  * Auth token is never logged (defensive check)
  * Endpoint trailing slash is normalized

We use httpx's MockTransport for in-process mocking — no live HTTP
calls, no respx dependency.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from unittest import mock

import httpx
import pytest

from app.modules.emr.base import EmrConnectorError
from app.modules.emr.fhir_generic import GenericFhirConnector

# ── Test helpers ─────────────────────────────────────────────────────────


def _mock_client(
    handler,
) -> httpx.AsyncClient:
    """Build an httpx.AsyncClient backed by a MockTransport. `handler`
    receives the request and returns an httpx.Response."""
    transport = httpx.MockTransport(handler)
    return httpx.AsyncClient(transport=transport)


@pytest.fixture
def clear_env() -> Iterator[None]:
    """Strip FHIR env vars for the duration of one test so env reads
    are deterministic."""
    keys = (
        "AURION_EMR_FHIR_ENDPOINT",
        "AURION_EMR_FHIR_AUTH_TOKEN",
        "AURION_EMR_FHIR_TIMEOUT_SECONDS",
    )
    snapshot = {k: os.environ.pop(k, None) for k in keys}
    try:
        yield
    finally:
        for k, v in snapshot.items():
            if v is not None:
                os.environ[k] = v


# ── from_env ─────────────────────────────────────────────────────────────


def test_from_env_returns_none_when_endpoint_missing(clear_env):
    """The signal that says "don't register me." Registry uses this
    to decide whether to wire the connector at all."""
    assert GenericFhirConnector.from_env() is None


def test_from_env_returns_none_when_endpoint_whitespace(clear_env):
    """Whitespace-only endpoint counts as unset."""
    os.environ["AURION_EMR_FHIR_ENDPOINT"] = "   "
    assert GenericFhirConnector.from_env() is None


def test_from_env_builds_concrete_when_endpoint_set(clear_env):
    os.environ["AURION_EMR_FHIR_ENDPOINT"] = "https://hapi.fhir.org/baseR4"
    c = GenericFhirConnector.from_env()
    assert c is not None
    assert c.endpoint == "https://hapi.fhir.org/baseR4"
    assert c.auth_token is None
    assert c.timeout_seconds == 15.0


def test_from_env_strips_trailing_slash(clear_env):
    os.environ["AURION_EMR_FHIR_ENDPOINT"] = "https://hapi.fhir.org/baseR4/"
    c = GenericFhirConnector.from_env()
    assert c is not None
    assert c.endpoint == "https://hapi.fhir.org/baseR4"


def test_from_env_picks_up_auth_token(clear_env):
    os.environ["AURION_EMR_FHIR_ENDPOINT"] = "https://x"
    os.environ["AURION_EMR_FHIR_AUTH_TOKEN"] = "abc123"
    c = GenericFhirConnector.from_env()
    assert c is not None
    assert c.auth_token == "abc123"


def test_from_env_custom_timeout(clear_env):
    os.environ["AURION_EMR_FHIR_ENDPOINT"] = "https://x"
    os.environ["AURION_EMR_FHIR_TIMEOUT_SECONDS"] = "30"
    c = GenericFhirConnector.from_env()
    assert c is not None
    assert c.timeout_seconds == 30.0


def test_from_env_falls_back_to_default_on_bad_timeout(clear_env):
    """Garbage timeout value → default; no crash."""
    os.environ["AURION_EMR_FHIR_ENDPOINT"] = "https://x"
    os.environ["AURION_EMR_FHIR_TIMEOUT_SECONDS"] = "not-a-number"
    c = GenericFhirConnector.from_env()
    assert c is not None
    assert c.timeout_seconds == 15.0


# ── _build_headers ───────────────────────────────────────────────────────


def test_headers_include_fhir_json_when_no_token():
    c = GenericFhirConnector("https://x")
    h = c._build_headers()
    assert h["Content-Type"] == "application/fhir+json"
    assert h["Accept"] == "application/fhir+json"
    assert "Authorization" not in h


def test_headers_include_bearer_when_token_set():
    c = GenericFhirConnector("https://x", auth_token="abc123")
    h = c._build_headers()
    assert h["Authorization"] == "Bearer abc123"


# ── _document_reference_url ──────────────────────────────────────────────


def test_url_clean_concat():
    c = GenericFhirConnector("https://hapi.fhir.org/baseR4")
    assert c._document_reference_url() == "https://hapi.fhir.org/baseR4/DocumentReference"


# ── _categorize_status ───────────────────────────────────────────────────


def test_categorize_401_terminal():
    retryable, msg = GenericFhirConnector._categorize_status(401)
    assert retryable is False
    assert "auth" in msg.lower()


def test_categorize_403_terminal():
    retryable, _ = GenericFhirConnector._categorize_status(403)
    assert retryable is False


def test_categorize_400_terminal():
    retryable, _ = GenericFhirConnector._categorize_status(400)
    assert retryable is False


def test_categorize_404_terminal():
    """A 404 on the endpoint URL is a config issue — re-running won't
    help. Treat as terminal."""
    retryable, _ = GenericFhirConnector._categorize_status(404)
    assert retryable is False


def test_categorize_422_terminal():
    """422 — FHIR validation failure. Payload-level rejection; the
    physician needs to fix something. Terminal."""
    retryable, _ = GenericFhirConnector._categorize_status(422)
    assert retryable is False


def test_categorize_500_retryable():
    retryable, msg = GenericFhirConnector._categorize_status(500)
    assert retryable is True
    assert "server" in msg.lower()


def test_categorize_503_retryable():
    retryable, _ = GenericFhirConnector._categorize_status(503)
    assert retryable is True


# ── _extract_external_id ─────────────────────────────────────────────────


def test_extract_id_from_body():
    body = json.dumps({"resourceType": "DocumentReference", "id": "abc-123"}).encode()
    assert GenericFhirConnector._extract_external_id(body) == "abc-123"


def test_extract_id_missing_returns_none():
    body = json.dumps({"resourceType": "DocumentReference"}).encode()
    assert GenericFhirConnector._extract_external_id(body) is None


def test_extract_id_malformed_body_returns_none():
    assert GenericFhirConnector._extract_external_id(b"{not valid json") is None


def test_extract_id_empty_body_returns_none():
    assert GenericFhirConnector._extract_external_id(b"") is None


def test_extract_id_non_object_body_returns_none():
    """`[1,2,3]` is valid JSON but not a FHIR resource."""
    assert GenericFhirConnector._extract_external_id(b"[1,2,3]") is None


def test_extract_id_coerces_to_string():
    """Some FHIR servers return integer ids (legacy). Coerce."""
    body = json.dumps({"id": 12345}).encode()
    assert GenericFhirConnector._extract_external_id(body) == "12345"


# ── _extract_id_from_location ────────────────────────────────────────────


def test_location_extract_basic():
    loc = "https://hapi.fhir.org/baseR4/DocumentReference/abc-123/_history/1"
    assert GenericFhirConnector._extract_id_from_location(loc) == "abc-123"


def test_location_extract_no_history():
    loc = "https://hapi.fhir.org/baseR4/DocumentReference/abc-123"
    assert GenericFhirConnector._extract_id_from_location(loc) == "abc-123"


def test_location_extract_no_documentreference_path_returns_none():
    """Server returned a Location pointing at something else."""
    loc = "https://hapi.fhir.org/baseR4/Bundle/xyz"
    assert GenericFhirConnector._extract_id_from_location(loc) is None


def test_location_extract_none_input_returns_none():
    assert GenericFhirConnector._extract_id_from_location(None) is None


# ── send — success paths ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_201_with_id_in_body():
    def handler(request: httpx.Request) -> httpx.Response:
        # Verify the request was shaped correctly while we're here.
        assert request.method == "POST"
        assert request.url.path.endswith("/DocumentReference")
        assert request.headers["Content-Type"] == "application/fhir+json"
        body = json.dumps({
            "resourceType": "DocumentReference",
            "id": "doc-abc",
        }).encode()
        return httpx.Response(201, content=body)

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://example.com/fhir", client=client)
        result = await c.send("sess-1", b'{"test":1}')
        assert result.external_id == "doc-abc"
        assert "HTTP 201" in result.raw_response_summary


@pytest.mark.asyncio
async def test_send_201_with_location_header_fallback():
    """Body has no id but server set Location — extract from there."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            201,
            content=b"{}",
            headers={
                "Location": "https://x/DocumentReference/loc-id/_history/1",
            },
        )

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        result = await c.send("sess-1", b'{}')
        assert result.external_id == "loc-id"


@pytest.mark.asyncio
async def test_send_2xx_no_id_anywhere_uses_placeholder():
    """Server returned success but no id and no Location. We don't
    fail (the send did succeed) — synthesize a placeholder so the
    audit row pin is preserved."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"{}")

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        result = await c.send("sess-xyz", b'{}')
        assert result.external_id == "unknown-sess-xyz"


@pytest.mark.asyncio
async def test_send_includes_bearer_when_token_set():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(
            201, content=json.dumps({"id": "x"}).encode(),
        )

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", auth_token="tok", client=client)
        await c.send("sess-1", b'{}')
        assert captured["auth"] == "Bearer tok"


@pytest.mark.asyncio
async def test_send_omits_auth_header_when_no_token():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("Authorization", "")
        return httpx.Response(
            201, content=json.dumps({"id": "x"}).encode(),
        )

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        await c.send("sess-1", b'{}')
        assert captured["auth"] == ""


# ── send — error paths ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_401_terminal_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, content=b"unauthorized")

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", auth_token="bad", client=client)
        with pytest.raises(EmrConnectorError) as exc_info:
            await c.send("sess-1", b'{}')
        assert exc_info.value.retryable is False
        assert "401" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_403_terminal_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, content=b"forbidden")

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        with pytest.raises(EmrConnectorError) as exc_info:
            await c.send("sess-1", b'{}')
        assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_send_422_terminal_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, content=b'{"resourceType":"OperationOutcome"}')

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        with pytest.raises(EmrConnectorError) as exc_info:
            await c.send("sess-1", b'{}')
        assert exc_info.value.retryable is False


@pytest.mark.asyncio
async def test_send_500_retryable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"server error")

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        with pytest.raises(EmrConnectorError) as exc_info:
            await c.send("sess-1", b'{}')
        assert exc_info.value.retryable is True
        assert "500" in str(exc_info.value)


@pytest.mark.asyncio
async def test_send_503_retryable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"")

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        with pytest.raises(EmrConnectorError) as exc_info:
            await c.send("sess-1", b'{}')
        assert exc_info.value.retryable is True


@pytest.mark.asyncio
async def test_send_connect_error_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        with pytest.raises(EmrConnectorError) as exc_info:
            await c.send("sess-1", b'{}')
        assert exc_info.value.retryable is True
        assert "connect" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_send_timeout_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("slow")

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        with pytest.raises(EmrConnectorError) as exc_info:
            await c.send("sess-1", b'{}')
        assert exc_info.value.retryable is True
        assert "timed out" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_send_phi_not_in_error_message():
    """Error messages must not echo payload bytes — defensive check."""
    payload_with_phi = b'{"resourceType":"DocumentReference","subject":{"identifier":{"value":"MRN-SECRET-12345"}}}'

    def handler(request: httpx.Request) -> httpx.Response:
        # Server echoes the payload in its 422 response body —
        # connector must NOT include the body in its error message.
        return httpx.Response(422, content=payload_with_phi)

    async with _mock_client(handler) as client:
        c = GenericFhirConnector("https://x", client=client)
        with pytest.raises(EmrConnectorError) as exc_info:
            await c.send("sess-1", payload_with_phi)
        # The error string must not echo the MRN value
        assert "MRN-SECRET-12345" not in str(exc_info.value)


# ── Registry env-driven registration ─────────────────────────────────────


def test_registry_does_not_register_fhir_when_env_unset(clear_env):
    """No endpoint env → fhir_generic stays out of the registry."""
    # Force a fresh bootstrap with env cleared.
    from app.modules.emr import registry as reg

    reg.reset_registry_for_tests()
    assert "fhir_generic" not in reg.list_connector_keys()
    assert "stub" in reg.list_connector_keys()


def test_registry_registers_fhir_when_env_set(clear_env):
    os.environ["AURION_EMR_FHIR_ENDPOINT"] = "https://example.com/fhir"
    from app.modules.emr import registry as reg

    reg.reset_registry_for_tests()
    try:
        assert "fhir_generic" in reg.list_connector_keys()
        connector = reg.get_connector("fhir_generic")
        assert isinstance(connector, GenericFhirConnector)
        assert connector.endpoint == "https://example.com/fhir"
    finally:
        # Restore registry for the rest of the suite.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("AURION_EMR_FHIR_ENDPOINT", None)
            reg.reset_registry_for_tests()
