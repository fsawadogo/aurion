"""PHI audit — AWS Comprehend Medical entity detection.

Scans transcript text for PHI entities and logs results to the audit trail.
In local dev mode, returns mock results without calling Comprehend Medical.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from app.core.types import Transcript

logger = logging.getLogger("aurion.phi_audit")

_REGION = os.getenv("AWS_DEFAULT_REGION", "ca-central-1")
_ENDPOINT_URL = os.getenv("AWS_ENDPOINT_URL")
_APP_ENV = os.getenv("APP_ENV", "local")


class PHIAuditResult:
    """Result of a PHI audit scan."""

    def __init__(
        self,
        session_id: str,
        phi_detected: bool,
        entity_count: int,
        entities: list[dict[str, Any]],
    ):
        self.session_id = session_id
        self.phi_detected = phi_detected
        self.entity_count = entity_count
        self.entities = entities


async def scan_transcript_for_phi(
    transcript: Transcript,
) -> PHIAuditResult:
    """Scan transcript text for PHI using AWS Comprehend Medical.

    In local dev, returns mock results (Comprehend Medical not
    available in LocalStack Community).
    """
    session_id = transcript.session_id
    full_text = " ".join(seg.text for seg in transcript.segments)

    if _APP_ENV == "local":
        return _mock_phi_scan(session_id, full_text)

    return await _real_phi_scan(session_id, full_text)


def _mock_phi_scan(session_id: str, text: str) -> PHIAuditResult:
    """Mock PHI scan for local development."""
    # Simple heuristic — flag if common PHI patterns detected
    phi_patterns = ["mr.", "mrs.", "patient name", "dob:", "mrn:", "health card"]
    text_lower = text.lower()
    detected = any(pattern in text_lower for pattern in phi_patterns)

    logger.info(
        "PHI audit (mock): session=%s phi_detected=%s",
        session_id,
        detected,
    )
    return PHIAuditResult(
        session_id=session_id,
        phi_detected=detected,
        entity_count=0,
        entities=[],
    )


async def _real_phi_scan(session_id: str, text: str) -> PHIAuditResult:
    """Real PHI scan using AWS Comprehend Medical."""
    try:
        client = boto3.client(
            "comprehendmedical",
            region_name=_REGION,
        )

        # Comprehend Medical has a 20KB text limit per call
        # For longer transcripts, split into chunks
        chunks = _split_text(text, max_chars=19000)
        all_entities: list[dict[str, Any]] = []

        for chunk in chunks:
            response = client.detect_phi(Text=chunk)
            entities = response.get("Entities", [])
            all_entities.extend(
                {
                    "text": e.get("Text", ""),
                    "type": e.get("Type", ""),
                    "category": e.get("Category", ""),
                    "score": e.get("Score", 0.0),
                }
                for e in entities
            )

        phi_detected = len(all_entities) > 0

        logger.info(
            "PHI audit: session=%s phi_detected=%s entities=%d",
            session_id,
            phi_detected,
            len(all_entities),
        )
        return PHIAuditResult(
            session_id=session_id,
            phi_detected=phi_detected,
            entity_count=len(all_entities),
            entities=all_entities,
        )

    except (BotoCoreError, ClientError) as e:
        logger.error("PHI audit failed: session=%s error=%s", session_id, str(e))
        # Non-blocking — log failure but don't break the pipeline
        return PHIAuditResult(
            session_id=session_id,
            phi_detected=False,
            entity_count=0,
            entities=[],
        )


def _split_text(text: str, max_chars: int = 19000) -> list[str]:
    """Split text into chunks respecting word boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        # Find last space before max_chars
        split_at = text.rfind(" ", 0, max_chars)
        if split_at == -1:
            split_at = max_chars
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    return chunks
