"""Fire-and-forget background tasks that survive garbage collection.

``asyncio`` keeps only a **weak** reference to a ``Task``. A bare
``asyncio.create_task(coro)`` whose result isn't stored anywhere can therefore
be garbage-collected before — or while — it runs, and the coroutine then never
completes (see the CPython ``asyncio.create_task`` docs: "Save a reference to
the result of this function, to avoid a task disappearing mid-execution").

This module holds a strong reference to each spawned task until it finishes, so
fire-and-forget work (pipeline orchestrators, best-effort notifications) is
guaranteed to run. Use :func:`spawn_background_task` instead of a bare
``asyncio.create_task`` for anything not awaited by its caller.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Coroutine, Optional

logger = logging.getLogger("aurion.background")

# Strong references to in-flight fire-and-forget tasks. Without this set the
# event loop's weak reference is the ONLY one, so the GC may collect the task
# before it runs. Entries are removed by the done-callback when each completes.
_background_tasks: set[asyncio.Task[Any]] = set()


def spawn_background_task(
    coro: Coroutine[Any, Any, Any], *, name: Optional[str] = None
) -> "asyncio.Task[Any]":
    """Schedule ``coro`` as a background task with a retained strong reference.

    The task is added to a module-level set (kept alive across the await points
    of the request that spawned it) and removed when it completes. Returns the
    ``Task`` so a caller that wants to await/cancel it still can.
    """
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)

    def _on_done(t: "asyncio.Task[Any]") -> None:
        _background_tasks.discard(t)
        # Surface a crashed background task instead of asyncio's
        # "Task exception was never retrieved" warning at GC time.
        if not t.cancelled():
            exc = t.exception()
            if exc is not None:
                logger.error(
                    "Background task %r failed: %s",
                    t.get_name(),
                    exc,
                    exc_info=exc,
                )

    task.add_done_callback(_on_done)
    return task
