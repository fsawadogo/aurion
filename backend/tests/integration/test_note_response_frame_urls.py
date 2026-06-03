"""Integration tests for the P1-FU-FRAME-URLS signed-frame-URL plumbing.

Covers the wire surface added in `app/api/v1/notes.py`:
  - `NoteClaimResponse.frame_url`
  - `CitationExpansion.frame_url`
  - Dual-mode resolver `_build_evidence_url_resolver` listing
    frames + clips prefixes independently (ONE LIST per prefix per
    request, NOT one total).
  - Graceful degradation on frames LIST / presign failure.
  - PHI scan over the touched modules.
  - Backward-compat with the P1-6-FU clip path AND with legacy
    decoders that don't know about `frame_url`.

Test isolation strategy
-----------------------
Same pattern as `test_note_response_clip_urls.py`: mock the note + DB +
auth boundaries with `AsyncMock` / `MagicMock` so the full ASGI route
runs end-to-end without Postgres or LocalStack. The S3 client is a
single `MagicMock` driving both `list_objects_v2` and
`generate_presigned_url`, so we can assert prefix-by-prefix call counts
and presign kwargs (notably `ExpiresIn=3600`).
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
    """Note with:
      - one transcript claim         (non-visual baseline)
      - two frame-kind visual claims (test prefix memoization)
      - one clip-kind visual claim   (test backward-compat with P1-6-FU)
      - one screen claim             (non-visual baseline)
      - one physician_edit claim     (non-visual baseline)
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
                        text="Patient reports shoulder stiffness.",
                        source_type="transcript",
                        source_id="seg_001",
                        source_quote="My shoulder has been stiff.",
                    ),
                ],
            ),
            NoteSection(
                id="imaging_review",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c_frame_1",
                        text="X-ray frame shows shoulder joint at neutral.",
                        source_type="visual",
                        source_id="frame_14500",
                    ),
                    NoteClaim(
                        id="c_frame_2",
                        text="Second still shows decreased external rotation.",
                        source_type="visual",
                        source_id="frame_19800",
                    ),
                    NoteClaim(
                        id="c_clip",
                        text="Patient demonstrated abduction to ~140 degrees.",
                        source_type="visual",
                        source_id="seg_001_clip",
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


def _make_frame_only_note(session_uuid: uuid.UUID) -> Note:
    """Frame-only note — used to assert the clips LIST is NEVER made
    when no clip-kind claim exists. Cost-control property."""
    return Note(
        session_id=str(session_uuid),
        stage=2,
        version=2,
        provider_used="anthropic",
        specialty="orthopedic_surgery",
        sections=[
            NoteSection(
                id="imaging_review",
                status="populated",
                claims=[
                    NoteClaim(
                        id="c_frame_1",
                        text="X-ray frame shows shoulder joint at neutral.",
                        source_type="visual",
                        source_id="frame_14500",
                    ),
                ],
            ),
        ],
    )


@pytest.fixture
def mock_s3_dual_kind(session_uuid: uuid.UUID):
    """Patch the shared S3 client with a MagicMock that returns DIFFERENT
    listings for the clips/ vs frames/ prefixes — the dual-mode contract.

    `list_objects_v2` is `side_effect`-driven so we can route by Prefix
    and assert per-prefix call counts via `call_args_list`. The same
    client signs presigned URLs for both kinds with a stub signature.
    """
    clip_keys = [
        {"Key": f"clips/{session_uuid}/abcdef1234.mp4"},
    ]
    frame_keys = [
        {"Key": f"frames/{session_uuid}/14500.jpg"},
        {"Key": f"frames/{session_uuid}/19800.jpg"},
    ]
    signed_url_template = (
        "https://aurion-frames.s3.ca-central-1.amazonaws.com/{key}"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=stubsignature123"
    )

    def _list_side_effect(*, Bucket: str, Prefix: str, **_):
        if Prefix.startswith("clips/"):
            return {"Contents": clip_keys}
        if Prefix.startswith("frames/"):
            return {"Contents": frame_keys}
        return {"Contents": []}

    client = MagicMock()
    client.list_objects_v2 = MagicMock(side_effect=_list_side_effect)
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
def mock_s3_frames_list_fails():
    """S3 client whose `list_objects_v2` raises a ClientError when the
    frames prefix is queried, but succeeds for the clips prefix. Used
    to assert graceful degradation on the frame path while leaving
    clip behaviour untouched."""
    from botocore.exceptions import ClientError

    def _list_side_effect(*, Bucket: str, Prefix: str, **_):
        if Prefix.startswith("frames/"):
            raise ClientError(
                error_response={
                    "Error": {"Code": "AccessDenied", "Message": "fake"}
                },
                operation_name="ListObjectsV2",
            )
        return {"Contents": []}

    client = MagicMock()
    client.list_objects_v2 = MagicMock(side_effect=_list_side_effect)
    client.generate_presigned_url = MagicMock(return_value="should-not-be-called")
    with patch("app.core.s3._s3_client", client), patch(
        "app.core.s3.get_s3_client", return_value=client
    ), patch("app.api.v1.notes.get_s3_client", return_value=client):
        yield client


# ── Helpers ─────────────────────────────────────────────────────────────────


SIGNED_URL_RE = re.compile(
    r"^https://.*\.amazonaws\.com/.*\?.*X-Amz-Signature=.*$"
)


async def _patched_route(
    session_uuid: uuid.UUID, session_model: SessionModel, note: Note
):
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


def _list_prefixes(mock_s3: MagicMock) -> list[str]:
    """Pull the `Prefix` kwarg from every list_objects_v2 call."""
    return [
        call.kwargs.get("Prefix")
        for call in mock_s3.list_objects_v2.call_args_list
    ]


# ── Tests ───────────────────────────────────────────────────────────────────


async def test_full_note_frame_claim_carries_signed_frame_url(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_dual_kind: MagicMock,
) -> None:
    """AC-1: frame-kind visual claim → evidence_kind="frame",
    frame_url is a valid signed URL, clip_url + duration_ms are None.
    AC-2: clip-kind visual claim → evidence_kind="clip", clip_url is a
    valid signed URL, frame_url is None, duration_ms set.
    AC-3: non-visual claims → all four evidence fields None."""

    note = _make_mixed_note(session_uuid)
    patches = await _patched_route(
        session_uuid, session_owned_by_clinician, note
    )
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

    # AC-1 — frame-kind claims
    frame_claim_1 = claims_by_id["c_frame_1"]
    assert frame_claim_1["evidence_kind"] == "frame"
    assert frame_claim_1["clip_url"] is None
    assert frame_claim_1["duration_ms"] is None
    assert frame_claim_1["frame_url"] is not None
    assert SIGNED_URL_RE.match(frame_claim_1["frame_url"]), (
        frame_claim_1["frame_url"]
    )

    frame_claim_2 = claims_by_id["c_frame_2"]
    assert frame_claim_2["evidence_kind"] == "frame"
    assert frame_claim_2["frame_url"] is not None
    assert SIGNED_URL_RE.match(frame_claim_2["frame_url"])

    # AC-2 — clip-kind claim (P1-6-FU regression guard)
    clip_claim = claims_by_id["c_clip"]
    assert clip_claim["evidence_kind"] == "clip"
    assert clip_claim["duration_ms"] is not None
    assert clip_claim["duration_ms"] > 0
    assert clip_claim["clip_url"] is not None
    assert SIGNED_URL_RE.match(clip_claim["clip_url"])
    # P1-FU-FRAME-URLS contract: clip-kind never sets frame_url.
    assert clip_claim["frame_url"] is None

    # AC-3 — non-visual claims
    for claim_id in ("c_transcript", "c_screen", "c_pedit"):
        claim = claims_by_id[claim_id]
        assert claim["evidence_kind"] is None, claim_id
        assert claim["duration_ms"] is None, claim_id
        assert claim["clip_url"] is None, claim_id
        assert claim["frame_url"] is None, claim_id


async def test_frame_url_uses_3600_second_ttl(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_dual_kind: MagicMock,
) -> None:
    """AC-4: frame presign uses ExpiresIn=3600. Every presign call
    (frame OR clip) goes through the same `generate_presigned_evidence_url`
    helper — DRY — so the TTL assertion covers both."""
    note = _make_mixed_note(session_uuid)
    patches = await _patched_route(
        session_uuid, session_owned_by_clinician, note
    )
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/full",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    # At least one presign call fired per kind (clip + ≥1 frame).
    assert mock_s3_dual_kind.generate_presigned_url.call_count >= 2
    for call in mock_s3_dual_kind.generate_presigned_url.call_args_list:
        kwargs = call.kwargs
        assert kwargs.get("ExpiresIn") == 3600, kwargs


async def test_one_list_per_prefix_per_request(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_dual_kind: MagicMock,
) -> None:
    """AC-5: two frame-kind + one clip-kind claim in the same response
    trigger ONE LIST per prefix — total 2 LISTs (clips + frames), NOT
    3 (per-claim) and NOT 1 (P1-6-FU's old guarantee, which would force
    both kinds to share a single LIST against one prefix)."""

    note = _make_mixed_note(session_uuid)
    patches = await _patched_route(
        session_uuid, session_owned_by_clinician, note
    )
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/full",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    prefixes = _list_prefixes(mock_s3_dual_kind)
    # Order-independent contract: each prefix listed at most once.
    assert prefixes.count(f"frames/{session_uuid}/") == 1, prefixes
    assert prefixes.count(f"clips/{session_uuid}/") == 1, prefixes
    assert mock_s3_dual_kind.list_objects_v2.call_count == 2, prefixes


async def test_frame_only_note_never_lists_clips_prefix(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_dual_kind: MagicMock,
) -> None:
    """Cost-control: a frame-only note never LISTs the clips prefix.
    Same DRY property in the other direction — clip-only notes never
    LIST the frames prefix (covered by the existing P1-6-FU tests
    that no longer assert the count was 1)."""

    note = _make_frame_only_note(session_uuid)
    patches = await _patched_route(
        session_uuid, session_owned_by_clinician, note
    )
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/full",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    prefixes = _list_prefixes(mock_s3_dual_kind)
    assert f"frames/{session_uuid}/" in prefixes
    assert f"clips/{session_uuid}/" not in prefixes, (
        f"Frame-only note triggered a wasted clips/ LIST: {prefixes}"
    )


async def test_graceful_degradation_when_frames_list_fails(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_frames_list_fails: MagicMock,
) -> None:
    """AC-8: when the frames LIST raises (S3 outage, IAM regression),
    the response stays 200, frame_url is None, but evidence_kind="frame"
    is preserved so the iOS chip / web UI still know to render a
    still-image indicator (not a play triangle). Same pattern as the
    clip graceful-degradation test."""

    note = _make_frame_only_note(session_uuid)
    patches = await _patched_route(
        session_uuid, session_owned_by_clinician, note
    )
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
    frame_claim = claims_by_id["c_frame_1"]
    assert frame_claim["evidence_kind"] == "frame"
    assert frame_claim["frame_url"] is None
    # We never called presign because there was no key to sign.
    mock_s3_frames_list_fails.generate_presigned_url.assert_not_called()


async def test_detail_endpoint_citations_carry_frame_url(
    app_client: AsyncClient,
    auth_headers: dict[str, str],
    session_uuid: uuid.UUID,
    session_owned_by_clinician: SessionModel,
    mock_s3_dual_kind: MagicMock,
) -> None:
    """AC-6: GET /notes/{id}/detail::citations[claim_id] carries
    frame_url with the same population rules as /full. Both the wire
    NoteResponse AND the CitationExpansion are populated from a SHARED
    resolver, so total LIST count across the two surfaces is still
    bounded by "one per prefix per request"."""

    note = _make_mixed_note(session_uuid)
    patches = await _patched_route(
        session_uuid, session_owned_by_clinician, note
    )
    with patches[0], patches[1], patches[2], patches[3]:
        response = await app_client.get(
            f"/api/v1/notes/{session_uuid}/detail",
            headers=auth_headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()

    wire_claims_by_id = {
        c["id"]: c
        for s in body["note"]["sections"]
        for c in s["claims"]
    }
    citations = body["citations"]

    # Wire surface — frame_url on every frame-kind claim, None on the
    # clip-kind claim, None on non-visual claims.
    assert wire_claims_by_id["c_frame_1"]["frame_url"] is not None
    assert SIGNED_URL_RE.match(wire_claims_by_id["c_frame_1"]["frame_url"])
    assert wire_claims_by_id["c_frame_2"]["frame_url"] is not None
    assert wire_claims_by_id["c_clip"]["frame_url"] is None
    assert wire_claims_by_id["c_transcript"]["frame_url"] is None
    assert wire_claims_by_id["c_screen"]["frame_url"] is None
    assert wire_claims_by_id["c_pedit"]["frame_url"] is None

    # Citation expansion surface (web review UI) — same rules.
    assert citations["c_frame_1"]["evidence_kind"] == "frame"
    assert citations["c_frame_1"]["frame_url"] is not None
    assert SIGNED_URL_RE.match(citations["c_frame_1"]["frame_url"])
    assert citations["c_frame_1"]["clip_url"] is None
    assert citations["c_frame_1"]["duration_ms"] is None

    assert citations["c_clip"]["evidence_kind"] == "clip"
    assert citations["c_clip"]["clip_url"] is not None
    assert citations["c_clip"]["frame_url"] is None

    assert citations["c_transcript"]["frame_url"] is None
    assert citations["c_pedit"]["frame_url"] is None
    # Screen citations stay on the screen-pipeline rails — no signed
    # evidence URL is exposed via the dual-mode resolver.
    assert citations["c_screen"]["frame_url"] is None
    assert citations["c_screen"]["evidence_kind"] is None

    # Sharing the resolver: still ONE LIST per prefix across both
    # wire + citations. Total = 2 (frames + clips).
    prefixes = _list_prefixes(mock_s3_dual_kind)
    assert prefixes.count(f"frames/{session_uuid}/") == 1, prefixes
    assert prefixes.count(f"clips/{session_uuid}/") == 1, prefixes
    assert mock_s3_dual_kind.list_objects_v2.call_count == 2, prefixes


# ── PHI scan over the touched modules (AC-7) ────────────────────────────────


class _LoggerCallVisitor(ast.NodeVisitor):
    """AST walker that collects every `logger.<level>(...)` call."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
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


def test_no_phi_in_frame_url_log_statements() -> None:
    """AC-7: AST-walks every logger call in `core/s3.py` and
    `api/v1/notes.py` (the modules touched by P1-FU-FRAME-URLS) and
    asserts no full S3 key, no full signed URL, no PHI variable rides
    in as a bare arg. Same PHI-safe contract enforced by the P1-6-FU
    scan; re-run here so any new log line introduced by this PR's
    refactor is covered too."""

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
            for forbidden_fragment in (
                "/clips/",
                "/frames/",
                "X-Amz-Signature",
            ):
                if _format_str_contains(call, forbidden_fragment):
                    violations.append(
                        f"{relpath}:{call.lineno} logger format string "
                        f"contains {forbidden_fragment!r} — leak risk"
                    )

    assert not violations, (
        "PHI scan failed on P1-FU-FRAME-URLS touched modules:\n  - "
        + "\n  - ".join(violations)
    )


# ── Wire format / decoder compatibility ─────────────────────────────────────


def test_legacy_decoder_ignores_frame_url_field() -> None:
    """A decoder built from the pre-P1-FU-FRAME-URLS wire shape (no
    `frame_url` key) MUST still parse a new payload — Pydantic ignores
    unknown fields by default. The backward-compatibility AC: every
    existing consumer (older iOS clients, web portal, integration test
    fixtures) keeps decoding unchanged."""
    from app.api.v1.notes import NoteClaimResponse

    # New payload — Pydantic accepts the field.
    new_payload = {
        "id": "c1",
        "text": "hello",
        "source_type": "visual",
        "source_id": "frame_14500",
        "source_quote": "",
        "physician_edited": False,
        "original_text": None,
        # P1-6-FU fields
        "evidence_kind": "frame",
        "duration_ms": None,
        "clip_url": None,
        # P1-FU-FRAME-URLS additive field
        "frame_url": "https://example.com/signed?X-Amz-Signature=stub",
    }
    parsed = NoteClaimResponse.model_validate(new_payload)
    assert parsed.evidence_kind == "frame"
    assert parsed.duration_ms is None
    assert parsed.clip_url is None
    assert parsed.frame_url is not None

    # Pre-P1-FU-FRAME-URLS payload (missing frame_url) still decodes —
    # the Pydantic default fills in None.
    legacy_payload = {
        "id": "c1",
        "text": "hello",
        "source_type": "visual",
        "source_id": "frame_14500",
        "source_quote": "",
        "physician_edited": False,
        "original_text": None,
        "evidence_kind": "frame",
        "duration_ms": None,
        "clip_url": None,
    }
    parsed_legacy = NoteClaimResponse.model_validate(legacy_payload)
    assert parsed_legacy.frame_url is None
    assert parsed_legacy.evidence_kind == "frame"

    # And a fully pre-P1-6-FU payload (none of the dual-mode fields)
    # still decodes — preserves the original P1-6-FU backward-compat
    # guarantee through this refactor.
    pre_p1_6_fu_payload = {
        "id": "c1",
        "text": "hello",
        "source_type": "transcript",
        "source_id": "seg_001",
    }
    parsed_pre = NoteClaimResponse.model_validate(pre_p1_6_fu_payload)
    assert parsed_pre.evidence_kind is None
    assert parsed_pre.duration_ms is None
    assert parsed_pre.clip_url is None
    assert parsed_pre.frame_url is None


def test_dry_only_one_presign_helper_exists() -> None:
    """DRY guard: the `generate_presigned_evidence_url` helper in
    `core/s3.py` is the single source of truth for signed evidence
    URLs. If a developer introduces a second presign helper in
    `api/v1/notes.py` or in any frame/clip module, this test catches it.
    """
    import re

    backend_root = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    )
    pattern = re.compile(
        r"def\s+\w*(?:generate_presigned|sign_evidence|sign_clip|sign_frame)\w*"
    )
    hits: list[str] = []
    for relpath in (
        "app/api/v1/notes.py",
        "app/api/v1/frames.py",
        "app/api/v1/clips.py",
    ):
        abspath = os.path.join(backend_root, relpath)
        if not os.path.exists(abspath):
            continue
        with open(abspath, "r", encoding="utf-8") as fp:
            for lineno, line in enumerate(fp, 1):
                if pattern.search(line):
                    hits.append(f"{relpath}:{lineno} {line.strip()}")
    assert not hits, (
        "Found a second presign helper outside core/s3.py — DRY "
        "violation:\n  - " + "\n  - ".join(hits)
    )
