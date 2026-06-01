"""Background retry worker for EMR write-backs (#57 follow-up).

Closes the retry arc that the scheduler in #174 + admin drain in
#174 / portal UI in #175 set up. Without this worker, retries
require manual operator action via `POST /admin/emr/retry-due`.
With this worker, retryable failures drain on a configurable cadence.

## Lifecycle

Started from the FastAPI lifespan in `app/main.py`. The task runs
forever until cancelled at shutdown, sleeping `interval_seconds`
between drain passes. Cancellation propagates from the lifespan
context manager via `asyncio.CancelledError` — we catch + log + exit
cleanly.

Each drain pass:
  1. opens a fresh DB session
  2. calls `list_due_for_retry` (caps at `batch_size`)
  3. for each row: looks up the source session + note + identifier
     and runs `retry_row`
  4. counts outcomes (sent / still_failed / skipped) and logs the
     pass summary
  5. commits or rolls back

The worker NEVER emits audit events itself. The retry_row service
already writes the per-row state; emitting redundant audit rows
from the worker would double-count for operator-driven retries (a
human hitting the admin endpoint).

## Configuration

  AURION_EMR_RETRY_WORKER_ENABLED — must be "1" / "true" / "yes" to
    start the worker. Default off. Deployment explicitly opts in
    after verifying the connector setup.
  AURION_EMR_RETRY_INTERVAL_SECONDS — sleep between drains.
    Default 60s. Clamped to [10, 600].
  AURION_EMR_RETRY_BATCH_SIZE — max rows per drain pass.
    Default 10. Clamped to [1, 100].

## Concurrency

The worker is a singleton per FastAPI process. If a clinic runs
multiple backend replicas, all of them will poll — that's fine,
the underlying state transition (failed→sending→sent/failed) is
serialized through SQLAlchemy and SCheduled rows are claimed by
the first replica that reaches them (the row's status becomes
"sending" inside `retry_row`'s flush before the connector call).
A second replica picking up the same row will see status != failed
and effectively skip via the standard query filter.

## Error isolation

A failure inside any single row's retry is captured by
`retry_row`'s internal try/except (it returns the row in failed
state instead of raising). A failure in the worker LOOP itself
(DB connection drop, etc.) is caught here, logged, and the loop
sleeps before retrying — never crashes the worker out of the
lifespan.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from app.core.database import async_session_factory
from app.core.kms_encryption import decrypt_str
from app.core.models import SessionModel
from app.modules.emr import service as emr_service
from app.modules.note_gen.service import get_latest_note

logger = logging.getLogger("aurion.emr.worker")

# Env var names — public so tests can monkey-patch them.
ENV_ENABLED = "AURION_EMR_RETRY_WORKER_ENABLED"
ENV_INTERVAL = "AURION_EMR_RETRY_INTERVAL_SECONDS"
ENV_BATCH_SIZE = "AURION_EMR_RETRY_BATCH_SIZE"

# Defaults — tuned conservatively. 60s × 10 rows/pass = 600 retries
# per minute upper bound, more than enough for pilot volume.
_DEFAULT_INTERVAL = 60.0
_DEFAULT_BATCH = 10

_INTERVAL_MIN, _INTERVAL_MAX = 10.0, 600.0
_BATCH_MIN, _BATCH_MAX = 1, 100


def _bool_env(name: str, default: bool = False) -> bool:
    """Truthy env reader matching the audit strict-mode pattern."""
    return os.getenv(name, "").lower() in ("1", "true", "yes")


def _read_interval() -> float:
    try:
        raw = float(os.getenv(ENV_INTERVAL, str(_DEFAULT_INTERVAL)))
    except ValueError:
        return _DEFAULT_INTERVAL
    return max(_INTERVAL_MIN, min(_INTERVAL_MAX, raw))


def _read_batch_size() -> int:
    try:
        raw = int(os.getenv(ENV_BATCH_SIZE, str(_DEFAULT_BATCH)))
    except ValueError:
        return _DEFAULT_BATCH
    return max(_BATCH_MIN, min(_BATCH_MAX, raw))


def is_enabled() -> bool:
    """Public so the lifespan can decide whether to start the task at all."""
    return _bool_env(ENV_ENABLED)


async def drain_once(batch_size: int) -> dict[str, int]:
    """Run one drain pass and return the per-pass counts.

    Used by both the loop and the admin endpoint (in the future
    when we wire the worker behind it). Caller passes an explicit
    batch_size so the loop can use its env-tuned value and ad-hoc
    callers can choose their own.

    Returns a dict for easy logging — keys: candidates, attempted,
    sent, still_failed, skipped.
    """
    sent = 0
    still_failed = 0
    skipped = 0
    attempted = 0

    async with async_session_factory() as db:
        due_rows = await emr_service.list_due_for_retry(db, limit=batch_size)
        for row in due_rows:
            session = await db.get(SessionModel, row.session_id)
            if session is None:
                skipped += 1
                continue
            note = await get_latest_note(str(row.session_id), db)
            if note is None:
                skipped += 1
                continue
            identifier_plain: Optional[str] = None
            if session.external_reference_id_encrypted is not None:
                try:
                    identifier_plain = decrypt_str(
                        session.external_reference_id_encrypted
                    )
                except Exception:
                    logger.warning(
                        "emr worker: identifier decrypt failed session=%s — "
                        "retrying without",
                        row.session_id,
                    )
            attempted += 1
            try:
                updated = await emr_service.retry_row(
                    row,
                    note,
                    author_user_id=str(session.clinician_id),
                    external_reference_id=identifier_plain,
                    db=db,
                )
            except KeyError:
                # Connector no longer registered — leave the row alone.
                logger.warning(
                    "emr worker: connector=%s no longer registered (row=%s)",
                    row.connector, row.id,
                )
                skipped += 1
                continue
            if updated.status == "sent":
                sent += 1
            else:
                still_failed += 1
        await db.commit()

    return {
        "candidates": len(due_rows),
        "attempted": attempted,
        "sent": sent,
        "still_failed": still_failed,
        "skipped": skipped,
    }


async def retry_drain_loop() -> None:
    """Run drain passes forever, sleeping between them.

    Cancellation (lifespan shutdown) propagates as CancelledError
    and exits cleanly. Any other exception is logged and the loop
    sleeps before retrying — never crashes the lifespan task.
    """
    interval = _read_interval()
    batch_size = _read_batch_size()
    logger.info(
        "emr worker: starting retry loop (interval=%.0fs batch=%d)",
        interval, batch_size,
    )

    while True:
        try:
            counts = await drain_once(batch_size)
            if counts["candidates"] > 0:
                logger.info(
                    "emr worker: drain pass — candidates=%d attempted=%d "
                    "sent=%d still_failed=%d skipped=%d",
                    counts["candidates"],
                    counts["attempted"],
                    counts["sent"],
                    counts["still_failed"],
                    counts["skipped"],
                )
        except asyncio.CancelledError:
            logger.info("emr worker: cancelled — shutting down")
            raise
        except Exception:
            # Don't let a transient DB or driver error crash the
            # lifespan task. Log + sleep + try again next tick.
            logger.exception("emr worker: drain pass failed; will retry")

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info("emr worker: cancelled during sleep — shutting down")
            raise


# ── Lifespan integration ────────────────────────────────────────────────

_task: Optional[asyncio.Task] = None


async def start_worker() -> None:
    """Start the worker as an asyncio task. Idempotent: returns the
    existing task if one is already running. No-op when the worker
    isn't enabled via env."""
    global _task
    if not is_enabled():
        logger.info("emr worker: not enabled (%s != 1)", ENV_ENABLED)
        return
    if _task is not None and not _task.done():
        logger.info("emr worker: already running — skipping start")
        return
    _task = asyncio.create_task(retry_drain_loop(), name="emr-retry-worker")
    logger.info("emr worker: task spawned")


async def stop_worker() -> None:
    """Cancel + await the worker task. Safe to call when no task is
    running (no-op). Called from the lifespan teardown."""
    global _task
    if _task is None:
        return
    if not _task.done():
        _task.cancel()
        try:
            await _task
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("emr worker: shutdown raised")
    _task = None
