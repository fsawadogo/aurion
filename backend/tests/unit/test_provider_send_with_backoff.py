"""Shared provider retry — bounded 429/503 backoff for httpx providers.

``send_with_backoff`` is the light-weight sibling of the Gemini vision
provider's guarded post (which additionally carries a process gate and a
circuit breaker). Every other provider call is a single request per
operation; these tests lock the shared helper's contract:

  * a rate-limited call retries and eventually succeeds;
  * retries are bounded — once exhausted the HTTP error propagates so the
    caller's ``ProviderError`` wrapping / registry fallback engages;
  * ``Retry-After`` is honoured when the server sends one;
  * a non-retryable status (400) is never retried.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

import app.modules.providers._retry as retry_mod
from app.modules.providers._retry import send_with_backoff


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    """Make backoff instant so tests don't actually wait."""
    sleep = AsyncMock(return_value=None)
    monkeypatch.setattr(retry_mod.asyncio, "sleep", sleep)
    return sleep


def _response(status_code: int, headers: dict[str, str] | None = None) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.headers = headers or {}
    if status_code >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"Error '{status_code}'", request=MagicMock(), response=r
        )
    else:
        r.raise_for_status.return_value = None
    return r


async def test_retries_429_then_succeeds(_no_sleep: AsyncMock) -> None:
    send = AsyncMock(side_effect=[_response(429), _response(200)])

    response = await send_with_backoff(send, provider="openai", label="note_gen")

    assert response.status_code == 200
    assert send.await_count == 2
    assert _no_sleep.await_count == 1


async def test_gives_up_after_bounded_retries(_no_sleep: AsyncMock) -> None:
    send = AsyncMock(side_effect=[_response(429)] * 10)

    with pytest.raises(httpx.HTTPStatusError):
        await send_with_backoff(send, provider="gemini", label="note_gen", max_retries=3)

    # 1 initial attempt + 3 retries, no more.
    assert send.await_count == 4


async def test_honours_retry_after_header(_no_sleep: AsyncMock) -> None:
    send = AsyncMock(
        side_effect=[_response(429, headers={"Retry-After": "7"}), _response(200)]
    )

    await send_with_backoff(send, provider="anthropic", label="note_gen")

    assert _no_sleep.await_args.args[0] == 7.0


async def test_retries_503(_no_sleep: AsyncMock) -> None:
    send = AsyncMock(side_effect=[_response(503), _response(200)])

    response = await send_with_backoff(send, provider="openai", label="vision_frame")

    assert response.status_code == 200
    assert send.await_count == 2


async def test_non_retryable_status_raises_immediately(_no_sleep: AsyncMock) -> None:
    send = AsyncMock(side_effect=[_response(400)])

    with pytest.raises(httpx.HTTPStatusError):
        await send_with_backoff(send, provider="openai", label="note_gen")

    assert send.await_count == 1
    assert _no_sleep.await_count == 0
