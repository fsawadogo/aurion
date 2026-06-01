"""Generic FHIR R4 EMR connector (#57 follow-up).

First real connector backend after the stub. POSTs a serialized
DocumentReference to a configurable FHIR endpoint with Bearer auth.
Works against any FHIR-compliant server — HAPI FHIR test sandbox
(`hapi.fhir.org/baseR4`), Aidbox dev, a clinic's own FHIR proxy.

Real EMR-vendor connectors (Oscar, Epic SMART, Cerner) get their own
modules and inherit the same EmrConnector contract; the differences
they layer on are auth flow (SMART-on-FHIR for Epic), payload
shape (CDA vs FHIR), and result extraction.

## Configuration

Reads two environment variables at connector instantiation:

  AURION_EMR_FHIR_ENDPOINT — base URL of the FHIR server (the
    DocumentReference resource path is appended). Example:
    `https://hapi.fhir.org/baseR4`. No trailing slash required.
  AURION_EMR_FHIR_AUTH_TOKEN — Bearer token. Some sandbox servers
    accept no auth at all; we still send the header when the env
    is set, omit it when missing.
  AURION_EMR_FHIR_TIMEOUT_SECONDS — request timeout. Default 15s.
    Beyond 30s and the user-facing portal will already have
    timed out the request anyway.

The registry only registers this connector when AURION_EMR_FHIR_ENDPOINT
is set. The deployment chooses to wire it; we don't auto-detect.

## Error categorization

We map HTTP outcomes to `EmrConnectorError(retryable=...)`:

  2xx        → success
  401 / 403  → terminal (auth won't fix on retry)
  4xx other  → terminal (bad payload; physician may need to fix
               and re-send)
  5xx        → retryable (server-side transient)
  Connection
  errors     → retryable (network blip)
  Timeout    → retryable (slow upstream)

## PHI handling

  * The payload IS PHI; we never log it.
  * Error messages from the server may echo payload fragments —
    we don't pass server error bodies through. The connector's
    EmrConnectorError message is structural only ("EMR returned
    409 conflict", "Connection refused", etc.).
  * The `Authorization` header is redacted from any log line that
    might include it.
"""

from __future__ import annotations

import logging
import os

import httpx

from app.modules.emr.base import EmrConnector, EmrConnectorError, EmrSendResult

logger = logging.getLogger("aurion.emr.fhir_generic")

_ENV_ENDPOINT = "AURION_EMR_FHIR_ENDPOINT"
_ENV_AUTH_TOKEN = "AURION_EMR_FHIR_AUTH_TOKEN"
_ENV_TIMEOUT = "AURION_EMR_FHIR_TIMEOUT_SECONDS"

_DEFAULT_TIMEOUT_SECONDS = 15.0


class GenericFhirConnector(EmrConnector):
    """POSTs DocumentReference to a configured FHIR R4 endpoint.

    Instantiate with explicit args for testing; in production the
    registry calls `from_env()` which reads the env vars."""

    key = "fhir_generic"

    def __init__(
        self,
        endpoint: str,
        *,
        auth_token: str | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # Strip trailing slash so we always concatenate cleanly.
        self.endpoint = endpoint.rstrip("/")
        self.auth_token = auth_token
        self.timeout_seconds = timeout_seconds
        # Allow injection for tests. In production we lazy-create a
        # client per send (default httpx behavior) — sessions are
        # already short-lived.
        self._client = client

    @classmethod
    def from_env(cls) -> "GenericFhirConnector | None":
        """Build from environment variables. Returns None when the
        required endpoint env isn't set — the registry uses that as
        a signal to NOT register this connector."""
        endpoint = os.getenv(_ENV_ENDPOINT, "").strip()
        if not endpoint:
            return None
        auth_token = os.getenv(_ENV_AUTH_TOKEN, "").strip() or None
        try:
            timeout = float(
                os.getenv(_ENV_TIMEOUT, str(_DEFAULT_TIMEOUT_SECONDS))
            )
        except ValueError:
            timeout = _DEFAULT_TIMEOUT_SECONDS
        return cls(
            endpoint, auth_token=auth_token, timeout_seconds=timeout,
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/fhir+json",
            "Accept": "application/fhir+json",
        }
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        return headers

    def _document_reference_url(self) -> str:
        return f"{self.endpoint}/DocumentReference"

    @staticmethod
    def _categorize_status(status_code: int) -> tuple[bool, str]:
        """Map an HTTP status to (retryable, sanitized_message).

        Auth failures (401/403) are TERMINAL — retrying the same token
        won't help. Other 4xx are also terminal (payload-level rejection).
        5xx are retryable (transient server-side)."""
        if 200 <= status_code < 300:
            # Caller doesn't hit this path; success is handled before
            # categorization. Keeping the branch for clarity.
            return (False, f"unexpected success-as-error: {status_code}")
        if status_code in (401, 403):
            return (False, f"EMR rejected request: auth ({status_code})")
        if 400 <= status_code < 500:
            return (False, f"EMR rejected payload ({status_code})")
        if 500 <= status_code < 600:
            return (True, f"EMR server error ({status_code})")
        return (True, f"unexpected EMR status ({status_code})")

    @staticmethod
    def _extract_external_id(body: bytes) -> str | None:
        """Parse the FHIR response and extract the `id` field.

        FHIR R4 servers respond to a POST /DocumentReference with the
        created resource (status 201) and the `id` populated. We
        don't full-validate — we want the id and the location header
        as fallback.
        """
        if not body:
            return None
        try:
            import json
            data = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        raw = data.get("id")
        return str(raw) if raw is not None else None

    @staticmethod
    def _extract_id_from_location(location: str | None) -> str | None:
        """Fallback: the FHIR-recommended `Location` header points at
        the created resource, in the form
        `<base>/DocumentReference/<id>/_history/<version>`. We pull
        out the `<id>` segment."""
        if not location:
            return None
        # Strip the version suffix if present.
        location = location.split("/_history/")[0]
        if "/DocumentReference/" not in location:
            return None
        return location.rsplit("/DocumentReference/", 1)[-1] or None

    async def send(
        self,
        session_id: str,
        payload: bytes,
    ) -> EmrSendResult:
        url = self._document_reference_url()
        headers = self._build_headers()

        logger.info(
            "fhir_generic emr connector: posting session=%s bytes=%d to %s",
            session_id, len(payload), url,
        )

        try:
            if self._client is not None:
                response = await self._client.post(
                    url,
                    content=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            else:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        url,
                        content=payload,
                        headers=headers,
                        timeout=self.timeout_seconds,
                    )
        except httpx.TimeoutException as exc:
            raise EmrConnectorError(
                f"EMR request timed out after {self.timeout_seconds}s",
                retryable=True,
            ) from exc
        except httpx.ConnectError as exc:
            raise EmrConnectorError(
                "Could not connect to EMR endpoint",
                retryable=True,
            ) from exc
        except httpx.HTTPError as exc:
            # Catch-all for the rest of httpx's exception tree (network
            # protocol errors, decode errors, etc.). Treated as
            # retryable defensively — re-runs usually succeed.
            raise EmrConnectorError(
                f"EMR transport error: {type(exc).__name__}",
                retryable=True,
            ) from exc

        if 200 <= response.status_code < 300:
            external_id = self._extract_external_id(response.content)
            if not external_id:
                external_id = self._extract_id_from_location(
                    response.headers.get("Location")
                )
            if not external_id:
                # The server returned 2xx but we can't find an id.
                # Don't fail — we did successfully send — but log the
                # ambiguity and synthesize a placeholder so the audit
                # row is still pinned to this attempt.
                logger.warning(
                    "fhir_generic emr: 2xx but no id in body or Location"
                )
                external_id = f"unknown-{session_id}"
            return EmrSendResult(
                external_id=external_id,
                raw_response_summary=(
                    f"Created at {url}/{external_id} (HTTP {response.status_code})"
                ),
            )

        retryable, message = self._categorize_status(response.status_code)
        raise EmrConnectorError(message, retryable=retryable)
