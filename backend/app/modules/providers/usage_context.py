"""Per-call provider usage collector (#73 / OV-2).

Providers parse token usage out of their raw API responses but their
interfaces deliberately return domain objects only (``Note``,
``Transcript`` — LSP: every provider interchangeable at the type
boundary). Rather than widen those signatures or hang mutable state off
shared provider singletons (a cross-request race), each provider drops
its usage into a ``ContextVar`` and the calling service consumes it
right after the call. ContextVars are asyncio-task-local, so concurrent
pipeline calls cannot cross-contaminate.

Contract: ``consume_call_usage()`` returns-and-clears, so stale usage
from a failed earlier call can never be attributed to a later one.
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class CallUsage:
    input_tokens: int
    output_tokens: int
    model: str


_current: ContextVar[CallUsage | None] = ContextVar("aurion_call_usage", default=None)


def set_call_usage(*, input_tokens: int, output_tokens: int, model: str) -> None:
    """Called by a provider after parsing its API response."""
    _current.set(CallUsage(input_tokens=input_tokens, output_tokens=output_tokens, model=model))


def consume_call_usage() -> CallUsage | None:
    """Return the last call's usage and clear it (read-once)."""
    usage = _current.get()
    _current.set(None)
    return usage
