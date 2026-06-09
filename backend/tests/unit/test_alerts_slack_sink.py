"""Unit tests for the #76 Slack delivery sink.

Pins the gates that make the sink safe: off-until-configured, CRITICAL
only, failures swallowed, and no PHI-bearing fields beyond the already
PHI-free alert columns in the payload.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.alerts import slack_sink


@pytest.fixture(autouse=True)
def _unset_env(monkeypatch):
    monkeypatch.delenv("SLACK_ALERTS_WEBHOOK_URL", raising=False)
    slack_sink._disabled_logged = False
    yield


def _client_returning(status: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.post = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_unconfigured_is_noop_false() -> None:
    assert slack_sink.is_configured() is False
    ok = await slack_sink.notify_slack(
        alert_type="masking_failed", severity="critical",
        source="vision_service", message="m",
    )
    assert ok is False


@pytest.mark.asyncio
async def test_configured_posts_payload(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_ALERTS_WEBHOOK_URL", "https://hooks.slack.test/T/B/x")
    client = _client_returning(200)
    with patch.object(slack_sink.httpx, "AsyncClient", return_value=client):
        ok = await slack_sink.notify_slack(
            alert_type="masking_failed", severity="critical",
            source="vision_service", message="Clip masking failed for 1a2b3c4d",
        )
    assert ok is True
    url, kwargs = client.post.call_args[0][0], client.post.call_args[1]
    assert url == "https://hooks.slack.test/T/B/x"
    text = kwargs["json"]["text"]
    assert "CRITICAL" in text
    assert "masking_failed" in text
    assert "vision_service" in text
    assert "Clip masking failed for 1a2b3c4d" in text


@pytest.mark.asyncio
async def test_non_2xx_returns_false(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_ALERTS_WEBHOOK_URL", "https://hooks.slack.test/T/B/x")
    with patch.object(
        slack_sink.httpx, "AsyncClient", return_value=_client_returning(500)
    ):
        ok = await slack_sink.notify_slack(
            alert_type="t", severity="critical", source="s", message="m",
        )
    assert ok is False


@pytest.mark.asyncio
async def test_transport_error_swallowed(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_ALERTS_WEBHOOK_URL", "https://hooks.slack.test/T/B/x")
    client = _client_returning()
    client.post = AsyncMock(side_effect=RuntimeError("connection refused"))
    with patch.object(slack_sink.httpx, "AsyncClient", return_value=client):
        ok = await slack_sink.notify_slack(
            alert_type="t", severity="critical", source="s", message="m",
        )
    assert ok is False  # never raises


@pytest.mark.asyncio
async def test_schedule_gates_on_severity(monkeypatch) -> None:
    monkeypatch.setenv("SLACK_ALERTS_WEBHOOK_URL", "https://hooks.slack.test/T/B/x")
    with patch.object(slack_sink, "notify_slack", AsyncMock()) as mock_notify:
        slack_sink.schedule_critical_notification(
            alert_type="t", severity="warning", source="s", message="m",
        )
        # Let any (incorrectly) scheduled task run.
        import asyncio
        await asyncio.sleep(0)
        mock_notify.assert_not_called()

        slack_sink.schedule_critical_notification(
            alert_type="t", severity="critical", source="s", message="m",
        )
        await asyncio.sleep(0)
        mock_notify.assert_called_once()


def test_schedule_unconfigured_is_silent_noop() -> None:
    # No env, no running loop — must not raise.
    slack_sink.schedule_critical_notification(
        alert_type="t", severity="critical", source="s", message="m",
    )
