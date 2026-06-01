"""Unit tests for the EMR retry worker (#57 follow-up).

Worker behavior we lock:
  * env reads are bounded — interval clamped to [10, 600] seconds,
    batch size clamped to [1, 100] rows
  * is_enabled() honors the three truthy values + defaults to False
  * start_worker is no-op when not enabled (returns without spawning)
  * start_worker spawns a task when enabled
  * stop_worker is a no-op when nothing is running
  * stop_worker cancels and awaits a running task
  * the retry loop catches non-CancelledError exceptions and keeps
    looping (transient DB failures don't crash the lifespan)

The full drain pass is integration-flavored (touches the registry +
async session factory) — we mock the service module rather than
running against a real DB.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Iterator
from unittest import mock

import pytest

from app.modules.emr import worker


@pytest.fixture
def clear_worker_env() -> Iterator[None]:
    """Strip worker env vars between tests."""
    keys = (worker.ENV_ENABLED, worker.ENV_INTERVAL, worker.ENV_BATCH_SIZE)
    snapshot = {k: os.environ.pop(k, None) for k in keys}
    try:
        yield
    finally:
        for k, v in snapshot.items():
            if v is not None:
                os.environ[k] = v


@pytest.fixture(autouse=True)
def reset_worker_task() -> Iterator[None]:
    """The worker module holds a module-level _task ref. Reset it
    between tests so a previous test's leftover doesn't pollute."""
    worker._task = None
    yield
    worker._task = None


# ── _read_interval / _read_batch_size — env clamping ────────────────────


def test_read_interval_default(clear_worker_env):
    assert worker._read_interval() == 60.0


def test_read_interval_custom(clear_worker_env):
    os.environ[worker.ENV_INTERVAL] = "120"
    assert worker._read_interval() == 120.0


def test_read_interval_clamps_low(clear_worker_env):
    """Below 10s would hammer the DB; we clamp."""
    os.environ[worker.ENV_INTERVAL] = "1"
    assert worker._read_interval() == 10.0


def test_read_interval_clamps_high(clear_worker_env):
    """Above 10min the queue could back up; cap."""
    os.environ[worker.ENV_INTERVAL] = "999999"
    assert worker._read_interval() == 600.0


def test_read_interval_bad_value_falls_back(clear_worker_env):
    os.environ[worker.ENV_INTERVAL] = "not-a-number"
    assert worker._read_interval() == 60.0


def test_read_batch_size_default(clear_worker_env):
    assert worker._read_batch_size() == 10


def test_read_batch_size_custom(clear_worker_env):
    os.environ[worker.ENV_BATCH_SIZE] = "25"
    assert worker._read_batch_size() == 25


def test_read_batch_size_clamps_low(clear_worker_env):
    os.environ[worker.ENV_BATCH_SIZE] = "0"
    assert worker._read_batch_size() == 1


def test_read_batch_size_clamps_high(clear_worker_env):
    os.environ[worker.ENV_BATCH_SIZE] = "9999"
    assert worker._read_batch_size() == 100


def test_read_batch_size_bad_value_falls_back(clear_worker_env):
    os.environ[worker.ENV_BATCH_SIZE] = "ten"
    assert worker._read_batch_size() == 10


# ── is_enabled ──────────────────────────────────────────────────────────


def test_is_enabled_false_by_default(clear_worker_env):
    assert worker.is_enabled() is False


def test_is_enabled_recognizes_truthy(clear_worker_env):
    for v in ("1", "true", "yes", "TRUE", "Yes"):
        os.environ[worker.ENV_ENABLED] = v
        assert worker.is_enabled() is True, f"value={v!r} should be truthy"


def test_is_enabled_other_values_are_false(clear_worker_env):
    for v in ("0", "false", "no", "on", ""):
        os.environ[worker.ENV_ENABLED] = v
        assert worker.is_enabled() is False, f"value={v!r} should be falsy"


# ── start_worker / stop_worker lifecycle ────────────────────────────────


@pytest.mark.asyncio
async def test_start_worker_noop_when_disabled(clear_worker_env):
    """No env set → no task spawned."""
    await worker.start_worker()
    assert worker._task is None


@pytest.mark.asyncio
async def test_start_worker_spawns_when_enabled(clear_worker_env):
    """Enabled env → task is created and named."""
    os.environ[worker.ENV_ENABLED] = "true"
    # drain_once → no-op AsyncMock so we don't hit the DB.
    # We use the real loop with a fast interval (clamped at 10s,
    # but we never let it tick more than once via stop_worker below).
    with (
        mock.patch.object(
            worker, "drain_once",
            new=mock.AsyncMock(return_value={
                "candidates": 0, "attempted": 0,
                "sent": 0, "still_failed": 0, "skipped": 0,
            }),
        ),
        mock.patch.object(worker, "_read_interval", return_value=0.01),
    ):
        await worker.start_worker()
        assert worker._task is not None
        assert worker._task.get_name() == "emr-retry-worker"
        await worker.stop_worker()
    assert worker._task is None


@pytest.mark.asyncio
async def test_start_worker_idempotent(clear_worker_env):
    """Second start_worker call with a running task is a no-op."""
    os.environ[worker.ENV_ENABLED] = "true"
    with (
        mock.patch.object(
            worker, "drain_once",
            new=mock.AsyncMock(return_value={
                "candidates": 0, "attempted": 0,
                "sent": 0, "still_failed": 0, "skipped": 0,
            }),
        ),
        mock.patch.object(worker, "_read_interval", return_value=0.01),
    ):
        await worker.start_worker()
        first = worker._task
        await worker.start_worker()
        # Second call must not replace the running task
        assert worker._task is first
        await worker.stop_worker()


@pytest.mark.asyncio
async def test_stop_worker_noop_when_no_task():
    """Stop with no running task is a no-op (safe at lifespan
    shutdown even when worker never started)."""
    assert worker._task is None
    await worker.stop_worker()
    assert worker._task is None


@pytest.mark.asyncio
async def test_stop_worker_cancels_running_task(clear_worker_env):
    """A running task gets cancelled cleanly + awaited to completion."""
    os.environ[worker.ENV_ENABLED] = "true"
    with (
        mock.patch.object(
            worker, "drain_once",
            new=mock.AsyncMock(return_value={
                "candidates": 0, "attempted": 0,
                "sent": 0, "still_failed": 0, "skipped": 0,
            }),
        ),
        # Long interval so the task parks inside its sleep when we cancel.
        mock.patch.object(worker, "_read_interval", return_value=10.0),
    ):
        await worker.start_worker()
        assert worker._task is not None
        await worker.stop_worker()
        assert worker._task is None


# ── retry_drain_loop — error isolation ──────────────────────────────────


@pytest.mark.asyncio
async def test_loop_swallows_drain_pass_exceptions(clear_worker_env):
    """A transient exception inside one drain pass must not crash
    the loop. Subsequent passes still run."""
    os.environ[worker.ENV_ENABLED] = "true"
    # Tiny interval so the loop ticks fast.
    os.environ[worker.ENV_INTERVAL] = "10"  # clamps to minimum
    # We do NOT patch asyncio.sleep here — patching it globally also
    # affects the test's own wait, breaking the polling pattern.
    # Instead we monkey-patch the interval reader to return ~0s.

    call_count = 0
    second_call_done = asyncio.Event()

    async def flaky_drain(batch_size):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("transient DB error")
        if call_count >= 2:
            second_call_done.set()
        return {
            "candidates": 0, "attempted": 0,
            "sent": 0, "still_failed": 0, "skipped": 0,
        }

    # Override the interval to a tiny value via the helper, NOT
    # via env (env value gets clamped to 10s).
    with mock.patch.object(worker, "_read_interval", return_value=0.01):
        with mock.patch.object(worker, "drain_once", new=flaky_drain):
            task = asyncio.create_task(worker.retry_drain_loop())
            try:
                await asyncio.wait_for(second_call_done.wait(), timeout=2.0)
            finally:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    # Both calls ran — exception was swallowed
    assert call_count >= 2


@pytest.mark.asyncio
async def test_loop_propagates_cancellation(clear_worker_env):
    """CancelledError MUST propagate (vs being caught + retried)
    so the lifespan teardown can shut the task down cleanly."""
    os.environ[worker.ENV_ENABLED] = "true"
    with (
        mock.patch.object(
            worker, "drain_once",
            new=mock.AsyncMock(return_value={
                "candidates": 0, "attempted": 0,
                "sent": 0, "still_failed": 0, "skipped": 0,
            }),
        ),
        # Long interval so the task parks inside its sleep when we cancel.
        mock.patch.object(worker, "_read_interval", return_value=10.0),
    ):
        task = asyncio.create_task(worker.retry_drain_loop())
        # Yield once so the task enters its sleep
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
