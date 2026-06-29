"""Unit tests for spawn_background_task (bg-task-retain).

A bare ``asyncio.create_task`` is only weakly referenced by the event loop, so an
un-stored task can be garbage-collected before it runs — the root cause of video
imports stalling forever in ``pending``. ``spawn_background_task`` holds a strong
reference until completion.
"""

from __future__ import annotations

import asyncio
import gc

import pytest

from app.core import background
from app.core.background import spawn_background_task


@pytest.mark.asyncio
async def test_runs_coro_and_retains_then_releases() -> None:
    ran = asyncio.Event()

    async def work() -> None:
        ran.set()

    task = spawn_background_task(work(), name="t")
    assert task in background._background_tasks  # retained while pending
    await asyncio.wait_for(ran.wait(), timeout=1)
    await task
    await asyncio.sleep(0)  # let the done-callback run
    assert task not in background._background_tasks  # released after done


@pytest.mark.asyncio
async def test_survives_gc_with_no_caller_reference() -> None:
    """The whole point: the caller keeps NO reference, yet the task still runs."""
    ran = asyncio.Event()

    async def work() -> None:
        ran.set()

    spawn_background_task(work())  # result deliberately not stored
    gc.collect()  # force a collection — the retained set must keep it alive
    await asyncio.wait_for(ran.wait(), timeout=1)


@pytest.mark.asyncio
async def test_task_exception_is_swallowed_and_released() -> None:
    async def boom() -> None:
        raise ValueError("kaboom")

    task = spawn_background_task(boom())
    with pytest.raises(ValueError):
        await task
    await asyncio.sleep(0)  # let the done-callback run (logs + discards)
    assert task not in background._background_tasks
