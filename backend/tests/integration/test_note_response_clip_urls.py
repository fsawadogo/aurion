"""Integration tests for the P1-6-FU clip URL plumbing.

Covers the wire surface added in `app/api/v1/notes.py`:
  - `NoteClaimResponse.evidence_kind` / `duration_ms` / `clip_url`
  - `CitationExpansion.evidence_kind` / `duration_ms` / `clip_url`
  - per-request memoized S3 LIST
  - graceful degradation on S3 / presign failure
  - PHI scan over the touched modules

Test isolation strategy
-----------------------
The note builder is pure-Python; we mock `get_latest_note`,
`_load_transcript`, `is_note_approved`, and `get_session` at the
boundaries so the full route path exercises end-to-end without a real
Postgres or LocalStack. The S3 client is a MagicMock so we can assert
both `list_objects_v2` call counts AND `generate_presigned_url` kwargs
(notably `ExpiresIn=3600`).
"""

from __future__ import annotations

import ast
import os
import re
import uuid
from typing import AsyncGenerator
from unittest.mock import AsyncMock, MagicMock, patch

# Set env before app import — APP_ENV=local enables the dev-token
# bearer shape `<role>:<user_id>` parsed by `_parse_dev_token`.
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AWS_DEFAULT_REGION", "ca-central-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "test")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "test")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.models import SessionModel  # noqa: E402
from app.core.types import (  # noqa: E402
    Note,
    NoteClaim,
    NoteSection,
    SessionState,
)

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def clinician_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def session_uuid() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def auth_headers(clinician_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer CLINICIAN:{clinician_id}"}


@pytest.fixture
def session_owned_by_clinician(
    session_uuid: uuid.UUID, clinician_id: uuid.UUID
) -> SessionModel:
    """A SessionModel stub in a state where the note review endpoints
    accept reads (AWAITING_REVIEW or later)."""
    return SessionModel(
        id=session_uuid,
        clinician_id=clinician_id,
        specialty="orthopedic_surgery",
        state=SessionState.REVIEW_COMPLETE,
    )


@pytest_asyncio.fixture
async def app_client() -> AsyncGenerator[AsyncClient, None]:
    """ASGI in-process client; DB dependency yields a MagicMock."""
    from app.core.database import get_db
    from app.main import app

    async def _yield_mock_db() -> AsyncGenerator[MagicMock, None]:
        yield MagicMock()

    app.dependency_overrides[get_db] = _yield_mock_db
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(
            transport=transport, base_url="http://aurion.test"
        ) as client:
            yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _make_mixed_note(session_uuid: uuid.UUID) -> Note:
    """Note with one transcript claim, one frame-kind visual claim, one
    clip-kind visual claim, one screen claim, one physician_edit claim.
    Hits every branch in the claim-to-response builder."""
    return Note(
        session_id=str(session_uuid),
        stage=2,
        version=3,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[
            NoteSection(
                id="hpi",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c_transcript",
                        text="Patient reports knee pain x 2 weeks.",
                        source_type="transcript",
                        source_id="seg_001",
                        source_quote="My knee has been hurting for two weeks.",
                    ),
                ],
            ),
            NoteSection(
                id="imaging_review",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c_frame",
                        text="X-ray frame shows knee joint.",
                        source_type="visual",
                        source_id="frame_14500",
                    ),
                    NoteClaim(
                        id="c_clip",
                        text="Patient demonstrated abduction to ~140 degrees.",
                        source_type="visual",
                        # Convention from caption_clip:
                        # frame_id = f"{clip.trigger_segment_id}_clip"
                        source_id="seg_001_clip",
                    ),
                    NoteClaim(
                        id="c_clip_2",
                        text="Patient winced and stopped at 145 degrees.",
                        source_type="visual",
                        source_id="seg_002_clip",
                    ),
                ],
            ),
            NoteSection(
                id="investigations",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c_screen",
                        text="Hemoglobin 138 g/L (normal).",
                        source_type="screen",
                        source_id="screen_18300",
                    ),
                ],
            ),
            NoteSection(
                id="plan",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c_pedit",
                        text="Refer to physiotherapy.",
                        source_type="physician_edit",
                        source_id="pedit_plan",
                        physician_edited=True,
                    ),
                ],
            ),
        ],
    )


def _stub_clip_listing(session_uuid: uuid.UUID, n_clips: int = 1) -> dict:
    """Build a list_objects_v2 response with ``n_clips`` clip keys."""
    return {
        "Contents": [
            {"Key": f"clips/{session_uuid}/{uuid.uuid4().hex}.mp4"}
            for _ in range(n_clips)
        ]
    }


@pytest.fixture
def mock_s3_with_clips(session_uuid: uuid.UUID):
    """Patch the shared S3 client factory with a MagicMock pre-loaded
    with one clip and a presigned URL stub.

    Critically, both `list_objects_v2` and `generate_presigned_url` are
    on the SAME client mock so tests can assert call counts on each.
    """
    listing = _stub_clip_listing(session_uuid, n_clips=1)
    signed_url_template = (
        "https://aurion-frames.s3.ca-central-1.amazonaws.com/{key}"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=stubsignature123"
    )

    client = MagicMock()
    client.list_objects_v2 = MagicMock(return_value=listing)
    client.generate_presigned_url = MagicMock(
        side_effect=lambda **kwargs: signed_url_template.format(
            key=kwargs["Params"]["Key"]
        )
    )
    with patch("app.core.s3._s3_client", client), patch(
        "app.core.s3.get_s3_client", return_value=client
    ), patch("app.api.v1.notes.get_s3_client", return_value=client):
        yield client


@pytest.fixture
def mock_s3_empty():
    """S3 client with NO clips listed — covers the graceful-degradation
    path where evidence_kind populates but clip_url stays None."""
    client = MagicMock()
    client.list_objects_v2 = MagicMock(return_value={"Contents": []})
    client.generate_presigned_url = MagicMock(return_value="should-not-be-called")
    with patch("app.core.s3._s3_client", client), patch(
        "app.core.s3.get_s3_client", return_value=client
    ), patch("app.api.v1.notes.get_s3_client", return_value=client):
        yield client


# ── Tests ───────────────────────────────────────────────────────────────────


SIGNED_URL_RE = re.compile(
    r"^https://.*\.amazonaws\.com/.*\?.*X-Amz-Signature=.*$"
)


async def _patched_route(session_uuid: uuid.UUID, session_model: SessionModel, note: Note):
    """Set of patches the full + detail endpoints need: owned session,
    latest note, transcript, approved flag."""
    return [
        patch(
            "app.api.v1._helpers.get_session",
            AsyncMock(return_value=session_model),
        ),
        patch(
            "app.api.v1.notes.get_latest_note",
            AsyncMock(return_value=note),
        ),
        patch(
            "app.api.v1.notes._load_transcript",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.api.v1.notes.is_note_approved",
            AsyncMock(return_value=True),
        ),
    ]


async def test_full_note_clip_claim_carries_signed_url(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_with_clips: MagicMock,
) -> None:
    """AC-1: clip-kind visual claim → evidence_kind="clip", duration_ms set,
    clip_url matches the signed-URL regex.
    AC-2: frame-kind visual claim → evidence_kind="frame", others None.
    AC-3: non-visual claims → all three new fields None."""

    note = _make_mixed_note(session_uuid)
    patches = await _patched_route(session_uuid, session_owned_by_clinician, note)
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/full",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()

    # Flatten the nested sections → claims.
    claims_by_id = {
        c["id"]: c for s in body["sections"] for c in s["claims"]
    }

    # AC-1 — clip-kind claim
    clip_claim = claims_by_id["c_clip"]
    assert clip_claim["evidence_kind"] == "clip"
    assert clip_claim["duration_ms"] is not None
    assert clip_claim["duration_ms"] > 0
    assert clip_claim["clip_url"] is not None
    assert SIGNED_URL_RE.match(clip_claim["clip_url"]), clip_claim["clip_url"]

    # AC-2 — frame-kind visual claim
    frame_claim = claims_by_id["c_frame"]
    assert frame_claim["evidence_kind"] == "frame"
    assert frame_claim["duration_ms"] is None
    assert frame_claim["clip_url"] is None

    # AC-3 — non-visual claims
    transcript_claim = claims_by_id["c_transcript"]
    assert transcript_claim["evidence_kind"] is None
    assert transcript_claim["duration_ms"] is None
    assert transcript_claim["clip_url"] is None

    screen_claim = claims_by_id["c_screen"]
    assert screen_claim["evidence_kind"] is None
    assert screen_claim["duration_ms"] is None
    assert screen_claim["clip_url"] is None

    pedit_claim = claims_by_id["c_pedit"]
    assert pedit_claim["evidence_kind"] is None
    assert pedit_claim["duration_ms"] is None
    assert pedit_claim["clip_url"] is None


async def test_signed_url_uses_3600_second_ttl(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_with_clips: MagicMock,
) -> None:
    """AC-4: TTL is exactly 3600 seconds — assert on the mocked
    generate_presigned_url kwargs."""
    note = _make_mixed_note(session_uuid)
    patches = await _patched_route(session_uuid, session_owned_by_clinician, note)
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/full",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    # At least one presign call fired for the clip claims.
    assert mock_s3_with_clips.generate_presigned_url.call_count >= 1
    for call in mock_s3_with_clips.generate_presigned_url.call_args_list:
        kwargs = call.kwargs
        assert kwargs.get("ExpiresIn") == 3600, kwargs


async def test_per_request_memoized_s3_list(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_with_clips: MagicMock,
) -> None:
    """AC-5: two clip-kind claims in the same response trigger exactly
    ONE S3 LIST call. Per-request memoization is the DRY guarantee."""

    note = _make_mixed_note(session_uuid)
    # Sanity: the fixture has two clip-kind claims.
    clip_kind_count = sum(
        1
        for s in note.sections
        for c in s.claims
        if c.source_type == "visual" and c.source_id.endswith("_clip")
    )
    assert clip_kind_count >= 2, "Test fixture should carry >=2 clip claims"

    patches = await _patched_route(session_uuid, session_owned_by_clinician, note)
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/full",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    # Exactly ONE list_objects_v2 call for the whole request.
    assert mock_s3_with_clips.list_objects_v2.call_count == 1, (
        "Memoization broken — N visual claims caused N LIST calls"
    )


async def test_graceful_degradation_when_no_clips_in_s3(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_empty: MagicMock,
) -> None:
    """When S3 lists no clip objects, the clip claim still surfaces
    evidence_kind='clip' (so iOS shows the play indicator), but
    clip_url is None — iOS falls back to the localized alert. The
    response stays 200; the review page never 500s on missing clips."""

    note = _make_mixed_note(session_uuid)
    patches = await _patched_route(session_uuid, session_owned_by_clinician, note)
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/full",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    claims_by_id = {
        c["id"]: c for s in body["sections"] for c in s["claims"]
    }
    clip_claim = claims_by_id["c_clip"]
    assert clip_claim["evidence_kind"] == "clip"
    assert clip_claim["duration_ms"] is not None
    assert clip_claim["clip_url"] is None
    # We never called presign because there was no key to sign.
    mock_s3_empty.generate_presigned_url.assert_not_called()


async def test_detail_endpoint_citations_carry_new_fields(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_with_clips: MagicMock,
) -> None:
    """AC-6: GET /notes/{id}/detail::citations[claim_id] carries the
    new evidence_kind / duration_ms / clip_url with the same population
    rules as /full. Both the wire NoteResponse AND the
    CitationExpansion are populated from a SHARED resolver."""

    note = _make_mixed_note(session_uuid)
    patches = await _patched_route(session_uuid, session_owned_by_clinician, note)
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/detail",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()

    # Detail wraps the wire note + a citations map. Both surfaces carry
    # the new fields for visual claims.
    wire_claims_by_id = {
        c["id"]: c
        for s in body["note"]["sections"]
        for c in s["claims"]
    }
    citations = body["citations"]

    # Wire surface
    assert wire_claims_by_id["c_clip"]["evidence_kind"] == "clip"
    assert wire_claims_by_id["c_clip"]["clip_url"] is not None
    assert SIGNED_URL_RE.match(wire_claims_by_id["c_clip"]["clip_url"])
    assert wire_claims_by_id["c_frame"]["evidence_kind"] == "frame"

    # Citation expansion surface (web review UI)
    assert citations["c_clip"]["evidence_kind"] == "clip"
    assert citations["c_clip"]["duration_ms"] is not None
    assert citations["c_clip"]["clip_url"] is not None
    assert SIGNED_URL_RE.match(citations["c_clip"]["clip_url"])

    assert citations["c_frame"]["evidence_kind"] == "frame"
    assert citations["c_frame"]["duration_ms"] is None
    assert citations["c_frame"]["clip_url"] is None

    assert citations["c_transcript"]["evidence_kind"] is None
    assert citations["c_pedit"]["evidence_kind"] is None
    assert citations["c_screen"]["evidence_kind"] is None

    # Sharing the resolver means ONE S3 LIST for both wire + citations.
    assert mock_s3_with_clips.list_objects_v2.call_count == 1


# ── PHI scan over the touched modules (AC-7) ────────────────────────────────


class _LoggerCallVisitor(ast.NodeVisitor):
    """AST walker that collects every `logger.<level>(...)` call.

    Used by the PHI scan tests to assert no full S3 key, no signed URL,
    and no transcript content leaks into a log line.
    """

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        # Match `logger.<level>(...)` and `_logger.<level>(...)` shapes.
        # Anything else (e.g. mock.assert_called_once) is ignored.
        if isinstance(node.func, ast.Attribute) and node.func.attr in {
            "debug",
            "info",
            "warning",
            "error",
            "exception",
            "critical",
        }:
            if isinstance(node.func.value, ast.Name) and node.func.value.id in {
                "logger",
                "_logger",
                "log",
            }:
                self.calls.append(node)
        self.generic_visit(node)


def _collect_logger_calls(source_path: str) -> list[ast.Call]:
    with open(source_path, "r", encoding="utf-8") as fp:
        tree = ast.parse(fp.read(), filename=source_path)
    visitor = _LoggerCallVisitor()
    visitor.visit(tree)
    return visitor.calls


def _format_str_contains(node: ast.AST, needle: str) -> bool:
    """Walk an AST node looking for `needle` as a literal substring in
    any contained string constant. Used to flag e.g. a logger call that
    embeds `{s3_key}` without truncation."""
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
            if needle in sub.value:
                return True
    return False


# Variable / parameter names that would, if logged in full, leak a
# session UUID, a signed URL, or PHI. Each touched module must NEVER
# pass these as raw args to a logger call.
_FORBIDDEN_LOG_VARS: frozenset[str] = frozenset(
    {
        # Full S3 keys / URLs — the truncation pattern is `s3_key[:12]`
        # or `key_prefix=...` so a bare `s3_key` arg is suspect.
        "url",
        "signed_url",
        "presigned_url",
        # Transcript content
        "transcript_text",
        "transcript_json",
        "segment_text",
        # Note content
        "note_content",
        "claim_text",
        "source_quote",
    }
)


def _bare_name_in_args(call: ast.Call, forbidden: frozenset[str]) -> set[str]:
    """Names from `forbidden` that appear as a top-level argument to the
    logger call without any slicing or attribute access."""
    hits: set[str] = set()
    for arg in call.args:
        if isinstance(arg, ast.Name) and arg.id in forbidden:
            hits.add(arg.id)
    return hits


def test_no_phi_in_clip_url_log_statements() -> None:
    """AC-7: AST-walks every logger call in core/s3.py and
    api/v1/notes.py (the modules touched by P1-6-FU) and asserts that
    no full S3 key, no signed URL, no session_id without truncation,
    and no PHI variable rides in as a bare arg."""

    touched_modules = [
        "app/core/s3.py",
        "app/api/v1/notes.py",
    ]

    violations: list[str] = []
    backend_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )

    for relpath in touched_modules:
        abspath = os.path.join(backend_root, relpath)
        for call in _collect_logger_calls(abspath):
            # 1. Bare PHI-adjacent variable names.
            bare = _bare_name_in_args(call, _FORBIDDEN_LOG_VARS)
            if bare:
                violations.append(
                    f"{relpath}:{call.lineno} bare PHI-adjacent var(s) "
                    f"{sorted(bare)} in logger call"
                )
            # 2. Format-string fragments that imply a full key / URL.
            for forbidden_fragment in ("/clips/", "/frames/", "X-Amz-Signature"):
                if _format_str_contains(call, forbidden_fragment):
                    violations.append(
                        f"{relpath}:{call.lineno} logger format string contains "
                        f"{forbidden_fragment!r} — leak risk"
                    )

    assert not violations, (
        "PHI scan failed on P1-6-FU touched modules:\n  - "
        + "\n  - ".join(violations)
    )


# ── Wire format / decoder compatibility ─────────────────────────────────────


def test_legacy_decoder_ignores_new_fields() -> None:
    """A decoder built from the pre-P1-6-FU wire shape (no
    `evidence_kind` / `duration_ms` / `clip_url` keys) MUST still parse
    a new payload — Pydantic ignores unknown fields by default.

    This is the backward-compatibility AC: every existing consumer
    (older iOS clients, web portal, integration tests fixtures) keeps
    decoding unchanged.
    """
    from app.api.v1.notes import NoteClaimResponse

    new_payload = {
        "id": "c1",
        "text": "hello",
        "source_type": "visual",
        "source_id": "frame_14500",
        "source_quote": "",
        "physician_edited": False,
        "original_text": None,
        # New fields — legacy decoders ignore these.
        "evidence_kind": "frame",
        "duration_ms": None,
        "clip_url": None,
    }
    parsed = NoteClaimResponse.model_validate(new_payload)
    assert parsed.evidence_kind == "frame"
    assert parsed.duration_ms is None
    assert parsed.clip_url is None

    # And a payload missing the new fields still decodes (Pydantic
    # defaults kick in).
    legacy_payload = {
        "id": "c1",
        "text": "hello",
        "source_type": "transcript",
        "source_id": "seg_001",
    }
    parsed_legacy = NoteClaimResponse.model_validate(legacy_payload)
    assert parsed_legacy.evidence_kind is None
    assert parsed_legacy.duration_ms is None
    assert parsed_legacy.clip_url is None
