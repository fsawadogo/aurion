"""Stub EMR connector — records the send attempt to a local log
without making a network call.

Used in development and during the CREOQ pilot (where the clinic
already manages its own EMR side; we don't write back yet). Real
connectors implement the same `EmrConnector` interface and route
through the registry.

The stub is the safety floor: the FHIR serializer + audit trail get
exercised on every send, even when no upstream EMR is wired.
"""

from __future__ import annotations

import logging

from app.modules.emr.base import EmrConnector, EmrSendResult
from app.modules.emr.fhir import synthetic_external_id

logger = logging.getLogger("aurion.emr.stub")


class StubEmrConnector(EmrConnector):
    """No-op connector that records the attempt and returns a
    synthetic external id. Never raises — useful as the default
    connector when none is configured."""

    key = "stub"

    async def send(
        self,
        session_id: str,
        payload: bytes,
    ) -> EmrSendResult:
        # Log structural facts ONLY — payload bytes are PHI-bound.
        logger.info(
            "stub emr connector: session=%s bytes=%d",
            session_id, len(payload),
        )
        return EmrSendResult(
            external_id=synthetic_external_id(session_id),
            raw_response_summary=(
                f"Stub connector recorded {len(payload)} bytes; no "
                "external EMR was contacted."
            ),
        )
