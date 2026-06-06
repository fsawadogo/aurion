"""Derive a human-readable device hint from a raw User-Agent string.

Issue #163 — Portal MFA setup + active sessions.

The portal "Active sessions" card needs a label per row so the
clinician can recognize which row is which device. Two design
constraints:

* We must NOT persist the raw User-Agent. It carries fingerprint-
  grade specificity (exact patch versions, build numbers) that
  ages poorly in an immutable trail and amplifies the deanonymization
  risk if the column ever leaks. The fingerprinting risk is the same
  reason ``issued_ip_hash`` is hashed.

* We must NOT call out to an external UA-parser library. The dataset
  doesn't change quarterly the way browser-fingerprinting databases
  do, and a static heuristic keeps the dependency surface small and
  the test surface deterministic.

The heuristic returns ``"<browser> · <platform>"`` (e.g.
``"Safari · iOS"`` / ``"Firefox · Windows"`` / ``"iOS app"``) capped
at 64 chars. Unknown UAs collapse to ``"Unknown device"``.

Single source of truth: every refresh-row mint (login + refresh)
funnels through this function so the rule is consistent across the
lifecycle.
"""

from __future__ import annotations

# Order matters — Edge contains "Chrome" in its UA, Chrome contains
# "Safari", Safari is the fallback among WebKit browsers. We probe the
# most specific signal first.
_BROWSERS: tuple[tuple[str, str], ...] = (
    ("Edg/", "Edge"),
    ("OPR/", "Opera"),
    ("Firefox/", "Firefox"),
    ("Chrome/", "Chrome"),
    # Mobile Safari sits in the iPhone/iPad cohort but we still label
    # the browser "Safari" so a clinician on Mac vs iPad can tell them
    # apart via the platform field.
    ("Safari/", "Safari"),
    # iOS app is the URLSession default — flag explicitly so it shows
    # up as "Aurion iOS" instead of "Unknown".
    ("Aurion-iOS", "Aurion iOS"),
    ("CFNetwork", "Aurion iOS"),
)

# Platform inference. ``iPad`` must come before ``Mac`` because newer
# iPadOS Safari announces itself as a Mac for the desktop-class layout.
_PLATFORMS: tuple[tuple[str, str], ...] = (
    ("iPad", "iPad"),
    ("iPhone", "iPhone"),
    ("iPod", "iOS"),
    ("Android", "Android"),
    ("Windows", "Windows"),
    ("Macintosh", "macOS"),
    ("Mac OS", "macOS"),
    ("Linux", "Linux"),
)

_MAX_LENGTH = 64
_UNKNOWN = "Unknown device"


def device_hint_from_user_agent(ua: str | None) -> str:
    """Return a short "browser · platform" label, or ``"Unknown device"``.

    Empty / None / unparseable UAs collapse to a single fixed string so
    the portal card never renders an empty cell. The label is at most
    64 chars to fit the ``device_hint`` column width.
    """
    if not ua:
        return _UNKNOWN

    browser = _first_match(ua, _BROWSERS)
    platform = _first_match(ua, _PLATFORMS)

    if not browser and not platform:
        return _UNKNOWN
    if browser and not platform:
        return browser[:_MAX_LENGTH]
    if platform and not browser:
        return platform[:_MAX_LENGTH]

    label = f"{browser} · {platform}"
    return label[:_MAX_LENGTH]


def _first_match(
    haystack: str, candidates: tuple[tuple[str, str], ...]
) -> str | None:
    """Return the second element of the first ``(needle, label)`` whose
    needle appears in ``haystack``; ``None`` if no needle matches."""
    for needle, label in candidates:
        if needle in haystack:
            return label
    return None


import ipaddress


def ip_class(raw_ip: str | None) -> str:
    """Return one of ``"local" | "private" | "internet" | "unknown"``.

    The portal sessions card surfaces this as a coarse hint so the
    clinician can spot anomalies (e.g. a session originating from the
    public internet when they only ever sign in from the clinic LAN).
    NEVER returns the raw IP — PHI-adjacent and not necessary for the
    UX.

    Categories:
      * ``local`` — loopback (127.0.0.1, ::1).
      * ``private`` — RFC 1918 / RFC 4193 ranges.
      * ``internet`` — globally routable.
      * ``unknown`` — empty / unparseable.
    """
    if not raw_ip:
        return "unknown"
    try:
        addr = ipaddress.ip_address(raw_ip)
    except ValueError:
        return "unknown"
    if addr.is_loopback:
        return "local"
    if addr.is_private or addr.is_link_local:
        return "private"
    return "internet"


__all__ = ["device_hint_from_user_agent", "ip_class"]
