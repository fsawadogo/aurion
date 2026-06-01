"""FHIR DocumentReference serializer for Aurion notes.

Builds a minimal R4-shaped DocumentReference payload from an approved
note. The Bundle pattern (DocumentReference + Composition + Encounter
+ Patient) is the post-pilot enrichment; the foundation slice
produces just the DocumentReference with a base64-embedded plain-text
body so any FHIR-aware EMR can ingest it.

This serializer is connector-agnostic — both the stub connector and
future Epic/Oscar connectors share it. The HL7v2 path will have its
own serializer in a follow-up.

PHI awareness:
  * the output IS PHI (it's the note); the caller owns it and must
    not log it
  * logging in this module is intentionally minimal — counts and
    structural facts only, never claim text
"""

from __future__ import annotations

import base64
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.types import Note

logger = logging.getLogger("aurion.emr.fhir")

# Aurion's identifier system URN — used in DocumentReference.identifier
# to mark notes as "this came from Aurion session X." Lets downstream
# systems group by session without parsing the body.
_AURION_IDENTIFIER_SYSTEM = "urn:aurion:session"

# LOINC code for "Note" (generic clinical note). Specialty-specific
# codes are post-pilot; this is the conservative default that won't
# trip type validators on any FHIR-aware EMR.
_LOINC_CLINICAL_NOTE = "11506-3"

# DocumentReference.status — `current` is correct for an approved note;
# we don't emit `superseded` or `entered-in-error` from this path.
_STATUS_CURRENT = "current"


def render_note_plain_text(note: Note) -> str:
    """Render the note as plain text for embedding into the FHIR
    payload. Skips non-populated sections.

    Format:
      # Section Title
      claim text here.

      # Next Section
      ...

    Mirrors what the DOCX export produces — same content, no styling.
    """
    parts: list[str] = []
    for section in note.sections:
        if section.status != "populated":
            continue
        if not section.claims:
            continue
        title = section.title or section.id.replace("_", " ").title()
        parts.append(f"# {title}")
        for claim in section.claims:
            parts.append(claim.text)
        parts.append("")  # blank line between sections
    return "\n".join(parts).rstrip() + "\n"


def serialize_document_reference(
    session_id: str,
    note: Note,
    *,
    author_user_id: str,
    external_reference_id: str | None = None,
) -> dict[str, Any]:
    """Build a FHIR R4 DocumentReference resource as a dict.

    Caller serializes to JSON / bytes via `serialize_payload`. Kept
    separate so connectors that want to wrap it in a Bundle (Epic
    SMART) or extract fields for HL7v2 can reuse the structure.

    Parameters:
      session_id — the Aurion session UUID (becomes
        identifier.value; also embedded in the masterIdentifier system)
      note — the approved note
      author_user_id — the clinician's user UUID; appears in
        DocumentReference.author[].reference and as a contained
        Practitioner identifier
      external_reference_id — optional patient MRN / EMR identifier
        (the value from the #61 patient identifier feature). When
        present, surfaces as DocumentReference.subject.identifier
        so the EMR can attach to an existing patient record.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    plain_text = render_note_plain_text(note)
    encoded = base64.b64encode(plain_text.encode("utf-8")).decode("ascii")

    payload: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "status": _STATUS_CURRENT,
        # Mark the document as belonging to Aurion. Lets a chart-side
        # process filter notes by source without parsing content.
        "identifier": [
            {
                "system": _AURION_IDENTIFIER_SYSTEM,
                "value": str(session_id),
            }
        ],
        "type": {
            "coding": [
                {
                    "system": "http://loinc.org",
                    "code": _LOINC_CLINICAL_NOTE,
                    "display": "Progress note",
                }
            ]
        },
        # Author the document came from. Reference is intentionally
        # internal (`Practitioner/<user_uuid>`) — the real EMR will
        # have its own Practitioner.id; mapping is the connector's
        # job. We surface the Aurion user_id so the audit trail on
        # both sides can be reconciled.
        "author": [
            {"reference": f"Practitioner/{author_user_id}"}
        ],
        "date": now_iso,
        "content": [
            {
                "attachment": {
                    "contentType": "text/plain",
                    "language": "en",
                    "data": encoded,
                    "creation": now_iso,
                }
            }
        ],
    }

    # `specialty` is a required str field on Note but may be empty in
    # edge cases; skip the context block when it's missing.
    if getattr(note, "specialty", None):
        # DocumentReference.context.related is the right home for
        # template/specialty metadata in R4 — keeps the EMR's
        # category column free.
        payload["context"] = {
            "related": [
                {
                    "identifier": {
                        "system": "urn:aurion:specialty",
                        "value": note.specialty,
                    }
                }
            ]
        }

    if external_reference_id:
        # The patient identifier path. We do NOT embed PHI in the
        # subject.display; the identifier value alone is what the
        # EMR uses to attach to its existing patient record. If the
        # connector knows a FHIR Patient/{id} mapping, it can rewrite
        # this in a connector-side adapter.
        payload["subject"] = {
            "identifier": {
                "system": "urn:aurion:patient-identifier",
                "value": external_reference_id,
            }
        }

    return payload


def serialize_payload(
    session_id: str,
    note: Note,
    *,
    author_user_id: str,
    external_reference_id: str | None = None,
) -> bytes:
    """Serialize the DocumentReference to JSON bytes ready for HTTP
    POST. Newline-terminated for readability when a connector logs
    the byte length / hashes the payload.
    """
    doc = serialize_document_reference(
        session_id,
        note,
        author_user_id=author_user_id,
        external_reference_id=external_reference_id,
    )
    body = json.dumps(doc, separators=(",", ":"))
    return (body + "\n").encode("utf-8")


def synthetic_external_id(session_id: str) -> str:
    """Generate a synthetic external_id for the stub connector.

    Real connectors return the EMR's DocumentReference.id. The stub
    needs SOMETHING shaped like an external id to populate
    `emr_write_backs.external_id` without inventing a non-deterministic
    fake on every send. We use the session UUID prefix so the audit
    trail still groups by session.
    """
    return f"stub-{session_id}-{uuid.uuid4().hex[:8]}"
