"""Shared UUID coercion helper.

Promotes a previously duplicated idiom (``_to_uuid``) out of three
repositories and the route-helper module into a single home in
``core/``. Repository modules call ``to_uuid(value)`` on inbound IDs
that may arrive as either ``str`` (from path params) or ``uuid.UUID``
(when callers have already parsed).
"""

from __future__ import annotations

import uuid


def to_uuid(value: str | uuid.UUID) -> uuid.UUID:
    """Return ``value`` as a ``uuid.UUID``.

    Accepts either a string or an existing UUID — the latter passes
    through unchanged so callers can normalise without paying for an
    extra parse on the already-typed path.
    """
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
