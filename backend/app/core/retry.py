"""Reusable retry wrapper with exponential backoff and jitter for AWS S3 operations.

Only retries on transient errors (5xx, throttling, timeouts). Non-retryable
errors (403, 404) are raised immediately. Every retry attempt is logged.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Callable, TypeVar

from botocore.exceptions import BotoCoreError, ClientError

logger = logging.getLogger("aurion.retry")

T = TypeVar("T")

RETRYABLE_ERROR_CODES = {
    "500",
    "503",
    "Throttling",
    "RequestTimeout",
    "ServiceUnavailable",
}


def _is_retryable(exc: Exception) -> bool:
    """Determine whether an exception is retryable."""
    if isinstance(exc, TimeoutError):
        return True
    if isinstance(exc, BotoCoreError):
        return True
    if isinstance(exc, ClientError):
        error_code = exc.response.get("Error", {}).get("Code", "")
        return error_code in RETRYABLE_ERROR_CODES
    return False


async def with_retry(
    fn: Callable[..., T],
    *args: Any,
    max_retries: int = 3,
    base_delay: float = 1.0,
    operation: str = "operation",
    session_id: str = "",
    **kwargs: Any,
) -> T:
    """Execute *fn* with exponential backoff and jitter on transient failures.

    Args:
        fn: The callable to execute.  May be sync or async.
        *args: Positional arguments forwarded to *fn*.
        max_retries: Maximum number of retry attempts (default 3).
        base_delay: Base delay in seconds for the first retry.
        operation: Human-readable label used in log messages.
        session_id: Session identifier included in log messages.
        **kwargs: Keyword arguments forwarded to *fn*.

    Returns:
        The return value of *fn*.

    Raises:
        The last exception encountered after all retries are exhausted, or a
        non-retryable error immediately.
    """
    last_exc: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            result = fn(*args, **kwargs)
            # If fn returns an awaitable, await it
            if asyncio.iscoroutine(result):
                result = await result
            return result  # type: ignore[return-value]
        except (BotoCoreError, ClientError, TimeoutError) as exc:
            last_exc = exc

            # Non-retryable errors are raised immediately
            if not _is_retryable(exc):
                raise

            if attempt < max_retries:
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(
                    "Retry %d/%d for %s: %s (session=%s, delay=%.2fs)",
                    attempt + 1,
                    max_retries,
                    operation,
                    exc,
                    session_id,
                    delay,
                )
                await asyncio.sleep(delay)
            else:
                logger.error(
                    "All %d retries exhausted for %s: %s (session=%s)",
                    max_retries,
                    operation,
                    exc,
                    session_id,
                )
                raise
        except Exception:
            # Non-AWS exceptions are not retried
            raise

    # Should never be reached, but satisfy the type checker
    assert last_exc is not None
    raise last_exc
