"""Gemini vision — 429/503 backoff + API-key redaction.

The dev Gemini key throttles hard when a Stage-2 run (or the Grounded Lab
replay) captions many frames at once. Without retry, one 429 discards a frame
and a whole session collapses to zero findings. These tests lock:

  * ``_post_generate_content`` retries a rate-limited call and eventually
    succeeds, gives up after the bounded number of attempts, and does NOT
    retry a non-retryable status.
  * ``Retry-After`` is honoured when present.
  * ``_redact`` strips the API key so httpx's ``?key=…`` URL never reaches a
    log line or a raised error.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

import app.modules.providers.vision.gemini as gemini
from app.core.types import ProviderError
from app.modules.config.schema import AppConfigSchema
from app.modules.providers.vision.gemini import (
    _MAX_RETRIES,
    _post_generate_content,
    _redact,
    _retry_after_seconds,
)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make backoff instant so tests don't actually wait."""
    monkeypatch.setattr(gemini.asyncio, "sleep", AsyncMock(return_value=None))
    gemini._REQUEST_GATES.clear()
    gemini._TRANSIENT_CIRCUITS.clear()


def _response(status_code: int, headers: dict[str, str] | None = None) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.headers = headers or {}
    if status_code >= 400:
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"Client error '{status_code}'", request=MagicMock(), response=r
        )
    else:
        r.raise_for_status.return_value = None
    r.json.return_value = {"ok": True}
    return r


def _client(responses: list[MagicMock]) -> MagicMock:
    client = MagicMock()
    client.post = AsyncMock(side_effect=responses)
    return client


# ── retry behaviour ──────────────────────────────────────────────────────────


async def test_retries_then_succeeds() -> None:
    client = _client([_response(429), _response(429), _response(200)])
    resp = await _post_generate_content(client, "gemini-x", {}, label="frame vision")
    assert resp.status_code == 200
    assert client.post.await_count == 3


async def test_gives_up_after_max_retries_and_raises() -> None:
    # _MAX_RETRIES retries → _MAX_RETRIES + 1 total attempts, last one raises.
    responses = [_response(429) for _ in range(_MAX_RETRIES + 1)]
    client = _client(responses)
    with pytest.raises(httpx.HTTPStatusError):
        await _post_generate_content(client, "gemini-x", {}, label="frame vision")
    assert client.post.await_count == _MAX_RETRIES + 1


async def test_503_is_also_retried() -> None:
    client = _client([_response(503), _response(200)])
    resp = await _post_generate_content(client, "gemini-x", {}, label="clip vision")
    assert resp.status_code == 200
    assert client.post.await_count == 2


async def test_non_retryable_status_is_not_retried() -> None:
    # A 400 is a real error, not a throttle — fail fast, no retry.
    client = _client([_response(400)])
    with pytest.raises(httpx.HTTPStatusError):
        await _post_generate_content(client, "gemini-x", {}, label="frame vision")
    assert client.post.await_count == 1


async def test_success_first_try_makes_one_call() -> None:
    client = _client([_response(200)])
    await _post_generate_content(client, "gemini-x", {}, label="frame vision")
    assert client.post.await_count == 1


async def test_key_rides_a_header_not_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    # The key must NOT go in ?key= (httpx logs the URL → CloudWatch leak). It
    # rides the x-goog-api-key auth header instead.
    monkeypatch.setattr(gemini, "_GOOGLE_AI_API_KEY", "AIzaSyHEADERONLY")
    client = _client([_response(200)])
    await _post_generate_content(client, "gemini-x", {}, label="frame vision")
    _, kwargs = client.post.call_args
    assert kwargs.get("params") is None
    assert kwargs["headers"]["x-goog-api-key"] == "AIzaSyHEADERONLY"


async def test_retry_after_header_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    slept: list[float] = []

    async def _capture(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(gemini.asyncio, "sleep", _capture)
    client = _client([_response(429, {"Retry-After": "7"}), _response(200)])
    await _post_generate_content(client, "gemini-x", {}, label="frame vision")
    assert slept == [7.0]


async def test_retry_after_is_capped_to_bounded_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slept: list[float] = []

    async def _capture(delay: float) -> None:
        slept.append(delay)

    monkeypatch.setattr(gemini.asyncio, "sleep", _capture)
    client = _client([_response(429, {"Retry-After": "600"}), _response(200)])
    await _post_generate_content(client, "gemini-x", {}, label="frame vision")
    assert slept == [gemini._BACKOFF_MAX_SECONDS]


async def test_exhausted_429_opens_circuit_and_queued_call_fails_fast() -> None:
    cfg = AppConfigSchema()
    first_client = _client([_response(429) for _ in range(cfg.pipeline.vision_gemini_max_retries + 1)])
    second_client = _client([_response(200)])

    with patch.object(gemini, "get_config", return_value=cfg):
        with pytest.raises(httpx.HTTPStatusError):
            await gemini._guarded_post_generate_content(first_client, "gemini-x", {}, label="frame vision")
        with pytest.raises(ProviderError, match="temporarily unavailable"):
            await gemini._guarded_post_generate_content(second_client, "gemini-x", {}, label="frame vision")

    assert first_client.post.await_count == cfg.pipeline.vision_gemini_max_retries + 1
    assert second_client.post.await_count == 0


async def test_exhausted_503_opens_circuit_for_queued_evidence() -> None:
    cfg = AppConfigSchema()
    first_client = _client(
        [_response(503) for _ in range(cfg.pipeline.vision_gemini_max_retries + 1)]
    )
    queued_client = _client([_response(200)])

    with patch.object(gemini, "get_config", return_value=cfg):
        with pytest.raises(httpx.HTTPStatusError):
            await gemini._guarded_post_generate_content(
                first_client, "gemini-x", {}, label="clip vision"
            )
        with pytest.raises(ProviderError, match="temporarily unavailable"):
            await gemini._guarded_post_generate_content(
                queued_client, "gemini-x", {}, label="clip vision"
            )

    assert queued_client.post.await_count == 0


async def test_transport_timeout_opens_circuit_for_queued_evidence() -> None:
    cfg = AppConfigSchema()
    request = httpx.Request("POST", "https://example.invalid")
    first_client = MagicMock()
    first_client.post = AsyncMock(
        side_effect=httpx.ReadTimeout("upstream stalled", request=request)
    )
    queued_client = _client([_response(200)])

    with patch.object(gemini, "get_config", return_value=cfg):
        with pytest.raises(httpx.ReadTimeout):
            await gemini._guarded_post_generate_content(
                first_client, "gemini-x", {}, label="frame vision"
            )
        with pytest.raises(ProviderError, match="temporarily unavailable"):
            await gemini._guarded_post_generate_content(
                queued_client, "gemini-x", {}, label="frame vision"
            )

    assert first_client.post.await_count == 1
    assert queued_client.post.await_count == 0


async def test_primary_attempt_deadline_opens_circuit_and_cancels_request() -> None:
    cfg = AppConfigSchema()
    cfg = cfg.model_copy(
        update={
            "pipeline": cfg.pipeline.model_copy(
                update={"vision_gemini_primary_timeout_seconds": 0.01}
            )
        }
    )
    cancelled = asyncio.Event()

    async def _stalled_post(*_args, **_kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    first_client = MagicMock()
    first_client.post = AsyncMock(side_effect=_stalled_post)
    queued_client = _client([_response(200)])

    with patch.object(gemini, "get_config", return_value=cfg):
        with pytest.raises(ProviderError, match="bounded primary-attempt timeout"):
            await gemini._guarded_post_generate_content(
                first_client, "gemini-x", {}, label="clip vision"
            )
        with pytest.raises(ProviderError, match="temporarily unavailable"):
            await gemini._guarded_post_generate_content(
                queued_client, "gemini-x", {}, label="clip vision"
            )

    assert cancelled.is_set()
    assert queued_client.post.await_count == 0


async def test_non_retryable_4xx_does_not_open_shared_circuit() -> None:
    cfg = AppConfigSchema()
    invalid_client = _client([_response(400)])
    next_client = _client([_response(200)])

    with patch.object(gemini, "get_config", return_value=cfg):
        with pytest.raises(httpx.HTTPStatusError):
            await gemini._guarded_post_generate_content(
                invalid_client, "gemini-x", {}, label="frame vision"
            )
        response = await gemini._guarded_post_generate_content(
            next_client, "gemini-x", {}, label="frame vision"
        )

    assert response.status_code == 200
    assert next_client.post.await_count == 1


async def test_external_cancellation_propagates_without_opening_circuit() -> None:
    cfg = AppConfigSchema()
    started = asyncio.Event()

    async def _stalled_post(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    client = MagicMock()
    client.post = AsyncMock(side_effect=_stalled_post)

    with patch.object(gemini, "get_config", return_value=cfg):
        task = asyncio.create_task(
            gemini._guarded_post_generate_content(
                client, "gemini-x", {}, label="frame vision"
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert gemini._TRANSIENT_CIRCUITS.get(asyncio.get_running_loop(), 0.0) == 0.0


async def test_two_runs_share_the_same_gemini_concurrency_gate() -> None:
    cfg = AppConfigSchema()
    state = {"active": 0, "peak": 0}

    async def _post(*_args, **_kwargs):
        state["active"] += 1
        state["peak"] = max(state["peak"], state["active"])
        try:
            await asyncio.sleep(0)
            return _response(200)
        finally:
            state["active"] -= 1

    client = MagicMock()
    client.post = AsyncMock(side_effect=_post)
    with patch.object(gemini, "get_config", return_value=cfg):
        await asyncio.gather(
            gemini._guarded_post_generate_content(client, "gemini-x", {}, label="doctor"),
            gemini._guarded_post_generate_content(client, "gemini-x", {}, label="lab"),
        )

    assert state["peak"] == cfg.pipeline.vision_gemini_max_concurrency == 1


# ── header parsing ───────────────────────────────────────────────────────────


def _hdr(value: Any) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.headers = {} if value is None else {"Retry-After": value}
    return r


def test_retry_after_parses_seconds() -> None:
    assert _retry_after_seconds(_hdr("12")) == 12.0


def test_retry_after_absent_is_none() -> None:
    assert _retry_after_seconds(_hdr(None)) is None


def test_retry_after_garbage_is_none() -> None:
    # HTTP-date form isn't parsed; degrade to exponential backoff, never crash.
    assert _retry_after_seconds(_hdr("Wed, 21 Oct 2026 07:28:00 GMT")) is None


# ── key redaction (the secret-in-logs fix) ───────────────────────────────────


def test_redact_strips_the_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini, "_GOOGLE_AI_API_KEY", "AIzaSyREALSECRET123")
    leaked = (
        "Client error '429 Too Many Requests' for url "
        "'https://generativelanguage.googleapis.com/v1beta/models/x:generateContent"
        "?key=AIzaSyREALSECRET123'"
    )
    out = _redact(leaked)
    assert "AIzaSyREALSECRET123" not in out
    assert "***" in out


def test_redact_noop_when_key_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(gemini, "_GOOGLE_AI_API_KEY", "")
    assert _redact("no key here") == "no key here"
