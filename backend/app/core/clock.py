"""Project-wide UTC clock helper.

Callers should use ``utcnow()`` instead of repeating
``datetime.now(timezone.utc)`` so the import surface stays small and
there's exactly one place to look at when discussing time in the app.
"""

from __future__ import annotations

from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
