"""Clip-aware pilot_metrics aggregation + persistence (P1-FU-METRICS).

Lives next to ``service.py`` so the Stage 2 dispatch loop can hand off
per-clip telemetry to a small, focused module — SRP. The dispatch loop
times each call and records ``ClipTelemetry``; this module turns those
records into the per-session ``pilot_metrics`` row update.

Three layers:

1. ``ClipTelemetry``      — dataclass carrying one clip's per-call
                            measurements (provider, model, latency,
                            tokens, degraded flag, byte size).
2. ``aggregate_clip_metrics`` — pure function: list[ClipTelemetry] →
                            dict[str, int] / None for the SQL row.
                            No DB, no I/O — trivially testable.
3. ``record_clip_metrics``   — DB-bound upsert into ``pilot_metrics``.
                            Mirrors ``_record_stage1_latency`` in
                            ``api/v1/transcription.py`` (same upsert
                            shape, same fail-loud-fail-warn behaviour).

CLAUDE.md §"Passive Data Collection" guards this surface: metrics are
non-blocking — a write failure here NEVER fails Stage 2 delivery. PHI
must not appear in any log line emitted from this module; we log
session_id-prefix (8 chars) only, never s3_keys or captions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.cost_rates import estimate_cost_usd_micros
from app.core.models import PilotMetricsModel, SessionModel

logger = logging.getLogger("aurion.vision.clip_metrics")


@dataclass(frozen=True)
class ClipTelemetry:
    """One clip's per-call measurements, captured during Stage 2 dispatch.

    All fields are populated by ``vision.service.caption_visual_evidence``
    as each clip completes. Frame-kind evidence does NOT produce a
    ``ClipTelemetry`` — this is clip-specific by contract; the existing
    frame metrics (``low_confidence_frame_rate``, etc.) live on the
    same row but are written by the existing Stage 2 flow.

    Token counts default to 0 when the provider does not surface them
    (vision providers don't return ``usage`` today — see
    ``docs/plans/p1-fu-metrics-clips.md`` for the deferred follow-up).
    """

    provider: str
    model: str
    latency_ms: int
    input_tokens: int = 0
    output_tokens: int = 0
    degraded_to_frame: bool = False
    bytes_uploaded: int = 0


def aggregate_clip_metrics(
    telemetries: list[ClipTelemetry],
) -> dict[str, Optional[int]]:
    """Aggregate per-clip telemetries into the pilot_metrics column shape.

    Returns a dict keyed by the ``pilot_metrics`` column names this PR
    adds. Empty input → ``clip_count=0`` + the two mean/sum columns
    stay ``None`` so "no clips processed" reads distinct from
    "0 ms / $0".

    ``clip_avg_latency_ms`` is the arithmetic mean of all per-clip
    latencies (integer floor, since the column is ``Integer``).

    ``clip_vision_spend_estimate_usd_micros`` is the sum of per-clip
    estimates from ``cost_rates.estimate_cost_usd_micros`` — pricing
    can vary between clips when the fallback chain swaps providers,
    so we price per-clip and sum.

    Pure function: no DB, no logging side effects, no clock reads.
    """
    if not telemetries:
        return {
            "clip_count": 0,
            "clip_bytes_uploaded": 0,
            "clip_avg_latency_ms": None,
            "clip_vision_spend_estimate_usd_micros": None,
            "clip_degraded_to_frame_count": 0,
        }

    clip_count = len(telemetries)
    bytes_total = sum(t.bytes_uploaded for t in telemetries)
    latency_total = sum(t.latency_ms for t in telemetries)
    # Integer floor mean — column is INTEGER; sub-ms precision is noise.
    avg_latency = latency_total // clip_count
    degraded_count = sum(1 for t in telemetries if t.degraded_to_frame)
    spend_micros = sum(
        estimate_cost_usd_micros(
            provider=t.provider,
            model=t.model,
            input_tokens=t.input_tokens,
            output_tokens=t.output_tokens,
        )
        for t in telemetries
    )

    return {
        "clip_count": clip_count,
        "clip_bytes_uploaded": bytes_total,
        "clip_avg_latency_ms": avg_latency,
        "clip_vision_spend_estimate_usd_micros": spend_micros,
        "clip_degraded_to_frame_count": degraded_count,
    }


async def record_clip_metrics(
    db: AsyncSession,
    session_id: str,
    telemetries: list[ClipTelemetry],
) -> None:
    """Upsert clip-aware metrics into the pilot_metrics row for a session.

    Mirrors ``_record_stage1_latency`` in ``api/v1/transcription.py``
    (same upsert shape, same fail-loud-fail-warn discipline) — we
    duplicate the pattern in place per §6c's rule of three: two
    occurrences today, the third extraction promotes the shared helper
    to ``modules/session/pilot_metrics_repo.py``.

    Non-fatal: a metrics write failure logs WARNING and returns; the
    Stage 2 pipeline keeps moving (CLAUDE.md §"Passive Data
    Collection" requires this).

    No PHI on this path: ``session_id`` is a UUID, and the aggregate
    dict carries only counts + ms + USD micros.
    """
    if not telemetries:
        # No clips were processed; nothing to record. Frame-only
        # sessions land here and skip the upsert.
        return

    aggregate = aggregate_clip_metrics(telemetries)

    try:
        # Look up the session for clinician_id + specialty so a row can
        # be created if Stage 1 hasn't yet (rare — Stage 1 latency
        # writes the row first today, but eval-team-only sessions
        # might exercise vision without a prior Stage 1 emit).
        existing = (
            await db.execute(
                select(PilotMetricsModel).where(
                    PilotMetricsModel.session_id == session_id
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            session_row = (
                await db.execute(
                    select(SessionModel).where(SessionModel.id == session_id)
                )
            ).scalar_one_or_none()
            if session_row is None:
                # No session row → metrics have nowhere to attach.
                # Logging at INFO; not an error because the eval team
                # probe endpoint exercises this path intentionally.
                logger.info(
                    "clip_metrics: no session row for session=%s — skipping upsert",
                    str(session_id)[:8],
                )
                return
            db.add(
                PilotMetricsModel(
                    session_id=session_id,
                    clinician_id=session_row.clinician_id,
                    specialty=session_row.specialty,
                    **aggregate,
                )
            )
        else:
            existing.clip_count = aggregate["clip_count"]
            existing.clip_bytes_uploaded = aggregate["clip_bytes_uploaded"]
            existing.clip_avg_latency_ms = aggregate["clip_avg_latency_ms"]
            existing.clip_vision_spend_estimate_usd_micros = aggregate[
                "clip_vision_spend_estimate_usd_micros"
            ]
            existing.clip_degraded_to_frame_count = aggregate[
                "clip_degraded_to_frame_count"
            ]
        await db.flush()
        logger.info(
            "clip_metrics recorded: session=%s clips=%d avg_latency_ms=%s "
            "bytes=%d degraded=%d spend_micros=%s",
            str(session_id)[:8],
            aggregate["clip_count"],
            aggregate["clip_avg_latency_ms"],
            aggregate["clip_bytes_uploaded"],
            aggregate["clip_degraded_to_frame_count"],
            aggregate["clip_vision_spend_estimate_usd_micros"],
        )
    except Exception as exc:  # noqa: BLE001 — passive metrics must not break Stage 2
        logger.warning(
            "Failed to record clip metrics for session=%s: %s",
            str(session_id)[:8],
            exc,
        )
