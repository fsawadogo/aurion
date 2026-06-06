"""Unit tests for the device-hint / ip-class helpers (#163).

Each call is constant-time + side-effect-free, so unit-test surface is
cheap and high coverage matters more than scenario realism.
"""

from __future__ import annotations

import pytest

from app.modules.auth.device_hint import device_hint_from_user_agent, ip_class


@pytest.mark.parametrize(
    "ua,expected",
    [
        # Desktop Chrome on macOS — common dev shape.
        (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 "
            "Safari/537.36",
            "Chrome · macOS",
        ),
        # Edge wraps Chrome — must be detected as Edge, not Chrome.
        (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/126.0.0.0 Safari/537.36 Edg/126.0",
            "Edge · Windows",
        ),
        # iPad Safari — iPad takes precedence over Mac in the UA.
        (
            "Mozilla/5.0 (iPad; CPU OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 Safari/604.1",
            "Safari · iPad",
        ),
        # iPhone Safari.
        (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
            "AppleWebKit/605.1.15 Safari/604.1",
            "Safari · iPhone",
        ),
        # Native iOS app UA. The Aurion app sends UA's like
        # "Aurion-iOS/1.4.2 (iPad; iPadOS 17.5) CFNetwork/1410". Plain
        # "Aurion-iOS" + CFNetwork without an iPad/iPhone token resolves
        # to the browser label only — fine for the portal where most
        # rows will be real browsers anyway.
        ("Aurion-iOS/1.4.2 CFNetwork/1410", "Aurion iOS"),
        (
            "Aurion-iOS/1.4.2 (iPad; iPadOS 17.5) CFNetwork/1410",
            "Aurion iOS · iPad",
        ),
        # Firefox on Linux.
        (
            "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 "
            "Firefox/128.0",
            "Firefox · Linux",
        ),
        # Android Chrome.
        (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 "
            "Chrome/126.0.0.0 Mobile Safari/537.36",
            "Chrome · Android",
        ),
        # Empty / unknown.
        ("", "Unknown device"),
        ("totally unparseable", "Unknown device"),
    ],
)
def test_device_hint_from_user_agent(ua: str, expected: str) -> None:
    assert device_hint_from_user_agent(ua) == expected


def test_device_hint_none_collapses_to_unknown() -> None:
    assert device_hint_from_user_agent(None) == "Unknown device"


def test_device_hint_truncates_to_64_chars() -> None:
    # Synthesize a UA with enough labels that the joined string exceeds
    # 64 chars (it won't in practice, but the guard is on the helper).
    ua = "Mozilla/5.0 " + "X" * 200 + " Chrome/1 Safari/1 Linux"
    hint = device_hint_from_user_agent(ua)
    assert len(hint) <= 64


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("127.0.0.1", "local"),
        ("::1", "local"),
        ("10.0.0.5", "private"),
        ("192.168.1.50", "private"),
        ("172.16.0.10", "private"),
        ("169.254.1.1", "private"),
        ("8.8.8.8", "internet"),
        ("2606:4700:4700::1111", "internet"),
        ("", "unknown"),
        ("not-an-ip", "unknown"),
        (None, "unknown"),
    ],
)
def test_ip_class(raw: str | None, expected: str) -> None:
    assert ip_class(raw) == expected
