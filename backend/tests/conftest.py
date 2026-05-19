"""Top-level test config.

Sets ``AURION_AUDIT_STRICT=1`` for the whole pytest suite so unknown
``write_audit(**fields)`` kwargs raise instead of warning. Production
runs without strict mode (a typo logs and still writes the event —
losing an audit row to a typo is worse than landing one with an extra
field), but in tests we want typos to break the build immediately.

The env var is read by ``app.core.audit_events.enforce_audit_kwargs``.
Must be set before any test imports the FastAPI app, hence the
top-level conftest.
"""

import os

os.environ.setdefault("AURION_AUDIT_STRICT", "1")
