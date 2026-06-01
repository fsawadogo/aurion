"""EMR connector abstraction (#57).

Mirrors the AI provider registry pattern: every concrete EMR backend
implements a small interface; routes/services only talk to the
interface, never to a concrete backend; the registry maps a connector
key (e.g. "stub", "oscar", "epic_smart", "fhir_generic") to a
concrete instance.

A connector takes a serialized payload + a session identifier and
returns either an `EmrSendResult` with `external_id` set (the EMR's
DocumentReference id, HL7 ACK id, etc.) or raises `EmrConnectorError`
with a sanitized message (no PHI). The service layer turns success /
error into the persisted state on `emr_write_backs`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class EmrSendResult:
    """Connector returned successfully."""

    external_id: str
    """The EMR's identifier for the posted document. FHIR connectors
    return `DocumentReference.id`; HL7 connectors return the ACK
    control id; the stub returns a synthetic UUID-shaped string."""

    raw_response_summary: Optional[str] = None
    """One-line free-text summary of the response (e.g. "Created at
    /DocumentReference/abc-123"). Connector must sanitize before
    returning — must NOT include PHI."""


class EmrConnectorError(Exception):
    """Connector failed to send.

    The `message` is sanitized for the audit trail — connectors must
    NOT include PHI in this string. `retryable` distinguishes
    transient (network blip, 5xx) from terminal (4xx auth, bad
    payload) failures; the service uses it to decide whether to
    schedule a retry.
    """

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class EmrConnector(ABC):
    """Abstract base for EMR write-back backends.

    Implementations live in `app.modules.emr.<connector_key>` and are
    registered through `app.modules.emr.registry`.

    Concrete connectors must:
      * accept a session UUID + a serialized payload (bytes)
      * push it to the upstream EMR
      * return `EmrSendResult` on 2xx-ish success
      * raise `EmrConnectorError(retryable=...)` on failure with a
        sanitized message
      * NEVER log the payload contents (PHI)
    """

    # The string used in `emr_write_backs.connector`. Concrete classes
    # override.
    key: str = "abstract"

    @abstractmethod
    async def send(
        self,
        session_id: str,
        payload: bytes,
    ) -> EmrSendResult:
        """Push the payload to the EMR.

        `payload` is the connector-format-specific bytes (FHIR JSON,
        HL7v2 ER7, etc.). The serializer producing it is the
        connector's matching pair — the service layer wires them up.
        """
        raise NotImplementedError
