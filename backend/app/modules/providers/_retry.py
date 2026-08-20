"""Shared bounded-backoff retry for provider HTTP calls.

Rate-limit resilience for the httpx-based LLM providers. The Gemini
*vision* provider carries its own richer policy (process-wide request
gate + fail-fast circuit, see ``providers/vision/gemini.py``) because
Stage 2 fans out many concurrent calls; every other provider call is a
single request per operation, where a bounded retry with backoff is
enough to let a burst drain instead of turning one 429 into a failed
note or caption.

429 = rate limit, 503 = transient upstream. Anything else propagates
immediately via ``raise_for_status`` so callers' existing error paths
(``ProviderError`` wrapping, registry fallback) engage unchanged.
"""

import asyncio
import logging
import random
from typing import Awaitable, Callable, Final

import httpx

logger = logging.getLogger(__name__)

RETRY_STATUSES: Final[frozenset[int]] = frozenset({429, 503})

_MAX_RETRIES: Final[int] = 3
_BACKOFF_BASE_SECONDS: Final[float] = 1.0
_BACKOFF_MAX_SECONDS: Final[float] = 30.0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """Parse a ``Retry-After`` header (delta-seconds form) when present."""
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return min(max(0.0, float(raw)), _BACKOFF_MAX_SECONDS)
    except ValueError:
        return None


async def send_with_backoff(
    send: Callable[[], Awaitable[httpx.Response]],
    *,
    provider: str,
    label: str,
    max_retries: int = _MAX_RETRIES,
) -> httpx.Response:
    """Issue ``send()`` with bounded backoff on 429/503.

    Retries up to ``max_retries`` times, honouring a ``Retry-After``
    header when the server sends one, else backing off 1s, 2s, 4s, …
    with full jitter, capped at ``_BACKOFF_MAX_SECONDS``. Once retries
    are exhausted — or on any non-retryable status — the response's
    ``raise_for_status`` propagates. ``send`` must build a fresh request
    each call (a zero-arg closure over ``client.post(...)``).

    Never logs request contents or URLs — only the provider name, the
    caller-supplied label, the status, and the delay.
    """
    attempt = 0
    while True:
        response = await send()
        if response.status_code in RETRY_STATUSES and attempt < max_retries:
            delay = _retry_after_seconds(response)
            if delay is None:
                backoff = min(
                    _BACKOFF_BASE_SECONDS * (2**attempt), _BACKOFF_MAX_SECONDS
                )
                delay = random.uniform(0.0, backoff)
            logger.warning(
                "%s %s rate-limited (HTTP %d); retry %d/%d in %.1fs",
                provider,
                label,
                response.status_code,
                attempt + 1,
                max_retries,
                delay,
            )
            await asyncio.sleep(delay)
            attempt += 1
            continue
        response.raise_for_status()
        return response
