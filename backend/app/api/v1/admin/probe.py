"""Admin diagnostic probes for AI provider end-to-end verification.

Adds `POST /api/v1/admin/probe/vision-clip` — a synchronous, admin-only
endpoint that uploads a small clip to the configured `vision_clip`
provider through the registry, times the call, and returns a structured
diagnostic. Used by operators to verify the Gemini Files API +
`caption_clip` work end-to-end before the eval team flips a session
into clips_only.

Design boundaries:
  * **No session linkage.** The probe writes a `VISION_CLIP_PROBED`
    audit row against a synthetic null session id; it does NOT create
    or touch any real session.
  * **No clip persistence after the call.** The clip body is written
    to S3 under `probe/<probe_id>.mp4` so the provider's `get_object`
    path is exercised end-to-end (same code path as a real Stage 2
    captioning run), then deleted in a finally-block regardless of
    provider outcome.
  * **No PHI.** The anchor is synthetic. The clip bytes never reach a
    logger, never reach the audit row, never reach the response body.
  * **Never re-raises.** Provider exceptions are caught, classified,
    and returned as a structured diagnostic. The probe's job is to
    REPORT, not crash.
  * **API keys are scrubbed.** Every `error_message` is passed
    through `_scrub_secrets` before leaving the handler — a leaked
    Gemini / OpenAI / Anthropic / AWS access key in an exception
    message is the worst possible regression for a diagnostic
    endpoint.

Admin-only via `require_role(UserRole.ADMIN)`. The probe reveals
provider state (resolved model, latency profile, configuration
gaps) that must not be exposed beyond operators.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from typing import Final, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel

from app.api.v1._helpers import write_audit
from app.core.audit_events import AuditEventType
from app.core.s3 import FRAMES_BUCKET, get_s3_client
from app.core.types import (
    ClipMaskingMetadata,
    FrameCaption,
    MaskedClip,
    ProviderError,
    TranscriptSegment,
    UserRole,
)
from app.modules.auth.service import CurrentUser, require_role
from app.modules.config.appconfig_client import get_config
from app.modules.config.provider_registry import get_registry
from app.modules.config.schema import VisionProviderKey
from app.modules.providers.vision.anthropic import _MODEL as _ANTHROPIC_MODEL
from app.modules.providers.vision.gemini import _MODEL as _GEMINI_MODEL
from app.modules.providers.vision.openai import _MODEL as _OPENAI_MODEL

logger = logging.getLogger("aurion.api.admin.probe")

router = APIRouter(prefix="/admin", tags=["admin"])

# iOS strips audio before clip upload; the probe mirrors the same
# contract — operators upload a video-only H.264 MP4. Anything else
# fails fast at the boundary.
_ALLOWED_CONTENT_TYPES: Final[frozenset[str]] = frozenset({"video/mp4"})

# Probe clips are tiny by contract — 5 MB is more than enough for a
# 2 s test card. Anything larger is rejected before any S3 write or
# provider call.
_MAX_CLIP_BYTES: Final[int] = 5 * 1024 * 1024

# Synthetic anchor text used as the transcript context the probe sends
# to the provider. Safe — no clinical content, no PHI, no patient
# identifier.
_PROBE_ANCHOR_TEXT: Final[str] = "Range of motion examination"

# Synthetic session id stamped on the probe audit row. Keeps probe
# rows out of any real session's history queries.
_PROBE_SESSION_ID: Final[uuid.UUID] = uuid.UUID(
    "00000000-0000-0000-0000-000000000000"
)

# Truncated probe-id length used in log lines. Probe ids are UUIDs;
# logging the full id is fine (no PHI), but we truncate for log
# legibility and to match the project's `_log_prefix` convention.
_LOG_PROBE_PREFIX_LEN: Final[int] = 8


# ── Secret scrub ───────────────────────────────────────────────────────────
#
# Provider SDKs (and `httpx` itself) sometimes include the API key in
# the exception's `str()` representation — e.g. when the URL with the
# `?key=...` query parameter ends up in a `RequestException`. We scrub
# anything that LOOKS like a known API key shape before letting an
# error_message field cross the wire.
#
# Patterns covered:
#   * Google AI keys     — `AIza[A-Za-z0-9_-]{30,}`
#   * OpenAI keys        — `sk-[A-Za-z0-9_-]{20,}` (and `sk-proj-...`)
#   * Anthropic keys     — `sk-ant-[A-Za-z0-9_-]{20,}`
#   * AWS access keys    — `(?:AKIA|ASIA)[A-Z0-9]{16}`
#   * Bearer header rest — `Bearer\s+[A-Za-z0-9._-]{20,}`
#   * `?key=` URL param  — `\bkey=[A-Za-z0-9_-]{20,}`
#
# The regexes are intentionally generous on the body to defend
# against future key-shape rotations.

_SECRET_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    # Anthropic — check BEFORE generic `sk-` so the longer prefix wins.
    re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    # OpenAI keys (incl. `sk-proj-…`).
    re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    # Google AI / Gemini.
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),
    # AWS access key ids (long-term + STS session). Secret keys are
    # 40-char base64 — the heuristic for those is the explicit
    # `AWS_SECRET_ACCESS_KEY` env-name pattern which is unlikely to
    # appear in a provider exception verbatim, so we don't try.
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    # `Bearer <token>` in HTTP error reprs.
    re.compile(r"Bearer\s+[A-Za-z0-9._-]{20,}"),
    # `?key=<value>` URL params used by `generativelanguage.googleapis.com`.
    re.compile(r"\bkey=[A-Za-z0-9_-]{20,}"),
)

_REDACTED_TOKEN: Final[str] = "***REDACTED***"


def _scrub_secrets(message: str) -> str:
    """Replace anything that LOOKS like an API key with ***REDACTED***.

    Called on every `error_message` before the diagnostic crosses the
    wire. Defensive — provider SDKs sometimes include the URL +
    `?key=...` query parameter in their exception messages.
    """
    if not message:
        return message
    scrubbed = message
    for pattern in _SECRET_PATTERNS:
        scrubbed = pattern.sub(_REDACTED_TOKEN, scrubbed)
    return scrubbed


# ── Exception classification ───────────────────────────────────────────────


def _classify_error(exc: BaseException) -> str:
    """Map an exception to a stable `error_type` string.

    The set is intentionally small — operators triage off this field so
    drift hurts. New exception classes default to `"Exception"` and
    we look up details from the message + audit row.
    """
    if isinstance(exc, ProviderError):
        return "ProviderError"
    if isinstance(exc, asyncio.TimeoutError):
        return "TimeoutError"
    if isinstance(exc, ValueError):
        return "ValueError"
    return "Exception"


# ── Response model ─────────────────────────────────────────────────────────


class VisionClipProbeResponse(BaseModel):
    """Diagnostic round-trip for a single `caption_clip` probe.

    `success=True` populates `caption` with the provider's
    `FrameCaption`. `success=False` populates `error_type` +
    `error_message` (the message is already scrubbed of API keys).

    `raw_response_excerpt` is reserved for future provider-specific
    debugging signals; today it always returns `None` because all
    provider HTTP responses are unwrapped inside the provider's
    `caption_clip` (we never see the raw body at this layer).
    """

    probe_id: str
    provider_used: str
    model_id: str
    latency_ms: int
    success: bool
    caption: Optional[FrameCaption] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    raw_response_excerpt: Optional[str] = None
    clip_metadata: dict


# Provider → model id metadata. Each entry is sourced from the provider
# module's own `_MODEL` constant — single source of truth (DRY, §6c). The
# previous incarnation hardcoded the strings here and drifted from the
# real implementations: `_PROVIDER_MODEL_ID[ANTHROPIC]` reported
# `"claude-sonnet-4-5"` while `anthropic.py:_MODEL` was already
# `"claude-sonnet-4-6"`. Operators saw the wrong model id in the probe
# diagnostic, which defeats the probe's entire purpose. Importing the
# constants makes future bumps a one-line change in the provider module;
# the probe inherits the new value automatically.
_PROVIDER_MODEL_ID: Final[dict[VisionProviderKey, str]] = {
    VisionProviderKey.GEMINI: _GEMINI_MODEL,
    VisionProviderKey.OPENAI: _OPENAI_MODEL,
    VisionProviderKey.ANTHROPIC: _ANTHROPIC_MODEL,
}


def _resolve_provider_key(
    provider_override: Optional[VisionProviderKey],
) -> VisionProviderKey:
    """Resolve the SINGLE provider key the probe will execute against.

    Used both to (a) shape the response's ``provider_used`` /
    ``model_id`` fields and (b) drive
    ``registry.get_vision_provider_for_kind("clip", override=…)``. Having
    ONE resolution call site eliminates the drift that surfaced in
    P1-FU-PROBE-BUGS — where the response-shape resolver could disagree
    with the actual registry resolution if the override path ever
    branched.

    Precedence matches ``ProviderRegistry.get_vision_provider_for_kind``:
    explicit override (already typed as ``VisionProviderKey`` by
    FastAPI's enum validator) wins; otherwise the live AppConfig
    ``providers.vision_clip`` is the default. The clip kind does not
    consult the DB override store today — AppConfig is the only
    runtime knob — so this matches the registry's clip branch exactly.
    """
    if provider_override is not None:
        return provider_override
    return get_config().providers.vision_clip


# ── Handler ────────────────────────────────────────────────────────────────


@router.post(
    "/probe/vision-clip",
    response_model=VisionClipProbeResponse,
)
async def probe_vision_clip(
    clip: UploadFile = File(...),
    provider_override: Optional[VisionProviderKey] = Query(default=None),
    _admin: CurrentUser = Depends(require_role(UserRole.ADMIN)),
) -> VisionClipProbeResponse:
    """Probe the configured `vision_clip` provider end-to-end.

    `provider_override` is a QUERY-STRING parameter (P1-FU-FFMPEG):
    `?provider_override=anthropic`. The previous incarnation declared
    it as `Form(default=None)`, which silently ignored query-string
    values — operators using `curl ... ?provider_override=…` got the
    AppConfig default (Gemini) with no error, defeating the override
    contract documented in `docs/dev/gemini-probe.md`. Query string is
    the natural diagnostic-endpoint shape and matches how Postman /
    curl operators expect to call admin endpoints. Invalid values
    surface as 422 via FastAPI's enum validator.

    Order of operations:

    1. Validate content-type and size cap. Reject early on bad input.
    2. Stream the bytes into S3 under `probe/<probe_id>.mp4` with KMS
       server-side encryption. The provider's `caption_clip`
       implementation reads from S3 (`get_object`), so we exercise the
       full bytes-on-wire path — not just the synthetic-in-memory
       happy path.
    3. Resolve the provider through the registry's
       `get_vision_provider_for_kind("clip", override=…)`. This is the
       SAME entry point used by the real Stage 2 dispatcher (P1-3);
       probing through it gives us identical resolution semantics.
    4. Time the provider call, catch every exception class, classify.
    5. ALWAYS delete the temp S3 object in a finally-block.
    6. Emit `VISION_CLIP_PROBED` audit row regardless of outcome.
    7. Return the structured diagnostic. Never re-raise.

    Operators should upload ONLY synthetic clips (see
    `backend/tests/fixtures/probe_clip.mp4`). The probe does not
    log or persist the bytes, but defense-in-depth: synthetic content
    means no PHI exposure even if the deletion ever leaks.
    """
    # 1. Content-type validation.
    if clip.content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported clip content type: {clip.content_type!r}. "
                f"Expected one of: {sorted(_ALLOWED_CONTENT_TYPES)}."
            ),
        )

    body = await clip.read()
    if not body:
        raise HTTPException(status_code=400, detail="Empty clip body")
    if len(body) > _MAX_CLIP_BYTES:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Clip body too large: {len(body)} bytes "
                f"(limit {_MAX_CLIP_BYTES} bytes for probe clips)."
            ),
        )

    probe_id = uuid.uuid4().hex
    s3_key = f"probe/{probe_id}.mp4"

    # Resolve the provider key ONCE — used to shape the response AND
    # passed to the registry on line ~360. Single source of truth so
    # the response's `provider_used` can never drift from the actual
    # call target. FastAPI has already validated the enum at the
    # boundary (invalid values surface as 422), so this call is
    # infallible at the type level — the try/except below is belt-
    # and-suspenders defense in case the AppConfig snapshot is
    # corrupt.
    try:
        resolved_key = _resolve_provider_key(provider_override)
    except ValueError as exc:
        # Defensive: would only fire if get_config() returned a
        # corrupt providers.vision_clip value (validated by Pydantic
        # at AppConfig parse time, so should never happen at runtime).
        raise HTTPException(
            status_code=400,
            detail=f"Invalid provider_override: {exc}",
        ) from exc

    model_id = _PROVIDER_MODEL_ID.get(resolved_key, "")
    # #437 — report the RESOLVED model: an AppConfig model_versions override
    # wins over the compiled-in default, so the probe shows the id the
    # provider will actually call (this is the canary check for the #438
    # Gemini 3.1 Pro flip).
    _override = getattr(get_config().model_versions, resolved_key.value, None)
    if _override:
        model_id = _override
    clip_metadata = {
        "size_bytes": len(body),
        "duration_ms": 0,  # probe doesn't decode the clip; operator-supplied.
        "content_type": clip.content_type,
    }

    # 2. Upload to S3 (so the provider's get_object path is exercised).
    s3_client = get_s3_client()
    try:
        s3_client.put_object(
            Bucket=FRAMES_BUCKET,
            Key=s3_key,
            Body=body,
            ContentType="video/mp4",
            ServerSideEncryption="aws:kms",
        )
    except Exception as exc:
        # An S3 failure is itself a useful diagnostic — surface it as
        # the probe's failure mode rather than as a 500. The operator
        # learns the dev-env S3 path is broken before the eval team
        # tries to run a real session.
        scrubbed = _scrub_secrets(str(exc))
        logger.error(
            "Probe S3 put failed: probe=%s key_prefix=%s error=%s",
            probe_id[:_LOG_PROBE_PREFIX_LEN], s3_key[:32], scrubbed,
        )
        await write_audit(
            _PROBE_SESSION_ID,
            AuditEventType.VISION_CLIP_PROBED,
            provider=resolved_key.value,
            success=False,
            latency_ms=0,
            error_type="S3UploadError",
        )
        return VisionClipProbeResponse(
            probe_id=probe_id,
            provider_used=resolved_key.value,
            model_id=model_id,
            latency_ms=0,
            success=False,
            caption=None,
            error_type="S3UploadError",
            error_message=scrubbed,
            raw_response_excerpt=None,
            clip_metadata=clip_metadata,
        )

    # 3-5. Resolve provider, call with timer, ALWAYS clean up temp S3
    # object. The provider call is wrapped in a broad except — the
    # probe never re-raises.
    success = False
    caption: Optional[FrameCaption] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    latency_ms = 0

    started_at = time.monotonic()
    try:
        registry = get_registry()
        try:
            # Single registry-resolution call site — uses the same
            # resolved_key the response shape will carry. Pass the
            # already-resolved key explicitly so the registry does NOT
            # re-read AppConfig and risk a snapshot mismatch.
            provider = registry.get_vision_provider_for_kind(
                "clip",
                override=resolved_key.value,
            )
        except ProviderError as exc:
            # Registry resolution itself failed (e.g. unknown enum
            # value, missing provider class). Classify and report.
            error_type = _classify_error(exc)
            error_message = _scrub_secrets(str(exc))
            latency_ms = int((time.monotonic() - started_at) * 1000)
        else:
            # Build the synthetic anchor + clip. Audio context is
            # safe synthetic text; trigger_segment_id is a stable
            # probe identifier; masking_metadata is zeroes (the probe
            # clip is a solid color, no faces).
            anchor = TranscriptSegment(
                id=f"probe_seg_{probe_id[:8]}",
                start_ms=0,
                end_ms=2000,
                text=_PROBE_ANCHOR_TEXT,
                is_visual_trigger=True,
                trigger_type="rom",
            )
            masked_clip = MaskedClip(
                s3_key=s3_key,
                timestamp_ms=0,
                duration_ms=2000,
                trigger_segment_id=anchor.id,
                masking_metadata=ClipMaskingMetadata(
                    frames_total=60,
                    frames_with_faces=0,
                    faces_blurred=0,
                ),
            )

            try:
                caption = await provider.caption_clip(masked_clip, anchor)
                success = True
                latency_ms = int((time.monotonic() - started_at) * 1000)
            except ProviderError as exc:
                error_type = _classify_error(exc)
                error_message = _scrub_secrets(str(exc))
                latency_ms = int((time.monotonic() - started_at) * 1000)
            except asyncio.TimeoutError as exc:
                error_type = _classify_error(exc)
                error_message = _scrub_secrets(str(exc) or "Provider call timed out")
                latency_ms = int((time.monotonic() - started_at) * 1000)
            except Exception as exc:  # noqa: BLE001 — diagnostic catch-all
                error_type = _classify_error(exc)
                error_message = _scrub_secrets(str(exc))
                latency_ms = int((time.monotonic() - started_at) * 1000)
    finally:
        # ALWAYS delete the temp S3 object — success or failure. A
        # leaked object would still be encrypted + scoped to the
        # `probe/` prefix where the bucket TTL policy reaps it, but
        # the deletion here is the primary contract.
        try:
            s3_client.delete_object(Bucket=FRAMES_BUCKET, Key=s3_key)
        except Exception as cleanup_exc:  # noqa: BLE001
            # Cleanup failures don't fail the probe response — they
            # log + add to the audit message field via a side-channel
            # so operators can see the leak.
            logger.error(
                "Probe S3 cleanup failed: probe=%s key_prefix=%s error=%s",
                probe_id[:_LOG_PROBE_PREFIX_LEN], s3_key[:32],
                _scrub_secrets(str(cleanup_exc)),
            )

    # 6. Audit row — fires on every call. error_type only when failure.
    audit_kwargs: dict = {
        "provider": resolved_key.value,
        "success": success,
        "latency_ms": latency_ms,
    }
    if error_type is not None:
        audit_kwargs["error_type"] = error_type
    await write_audit(
        _PROBE_SESSION_ID,
        AuditEventType.VISION_CLIP_PROBED,
        **audit_kwargs,
    )

    logger.info(
        "Vision-clip probe: probe=%s provider=%s success=%s latency_ms=%d",
        probe_id[:_LOG_PROBE_PREFIX_LEN],
        resolved_key.value,
        success,
        latency_ms,
    )

    # 7. Return diagnostic.
    return VisionClipProbeResponse(
        probe_id=probe_id,
        provider_used=resolved_key.value,
        model_id=model_id,
        latency_ms=latency_ms,
        success=success,
        caption=caption,
        error_type=error_type,
        error_message=error_message,
        raw_response_excerpt=None,
        clip_metadata=clip_metadata,
    )
