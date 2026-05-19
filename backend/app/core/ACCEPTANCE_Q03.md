# Q-03 — Audit event kwarg whitelist (Acceptance Criteria)

## Goal

Tighten ``write_audit(session_id, event_type, **fields)`` so unknown
kwargs are caught at test/CI time instead of silently landing in
DynamoDB as a misspelled field. Pair with Q-01's
``AuditEventType`` enum, which now defines *which* events we emit;
this PR defines *what fields each event may carry*.

## Approach

### 1. Registry: ``ALLOWED_AUDIT_KWARGS``

A frozen ``dict[AuditEventType, frozenset[str]]`` in
``core/audit_events.py``. Every enum member maps to the exact set
of kwargs it may carry, derived from the real call sites surveyed
in this PR's research phase.

  * Server-emitted events: real kwargs (e.g.
    ``STAGE1_APPROVED → {"version", "provider_used", "completeness_score"}``).
  * iOS-emitted events (``MASKING_CONFIRMED``,
    ``BIOMETRIC_CONSENT_CONFIRMED``, ``VOICE_ENROLLMENT_*``): empty
    frozenset — the server never emits them via ``write_audit``;
    iOS hits the DynamoDB-backed endpoint directly with its own
    schema. An empty set means "if the server ever does emit this,
    no extra fields allowed."
  * Lifecycle events that flow through ``write_audit(session.id,
    get_audit_event_for_state(state))`` carry no kwargs.

### 2. Validation helper

```python
def validate_audit_kwargs(
    event_type: AuditEventType | str,
    fields: dict[str, Any],
) -> set[str]:
    """Return the set of unknown kwarg names. Empty set = clean."""
```

The helper is permissive when ``event_type`` is a raw ``str`` (the
fallback path for unknown states) — we can't validate against an
event we don't know about, so we don't try.

### 3. Wired into ``write_audit``

```python
async def write_audit(session_id, event_type, **fields):
    unknown = validate_audit_kwargs(event_type, fields)
    if unknown:
        msg = f"Unknown kwargs for {event_type}: {sorted(unknown)}"
        if _STRICT_MODE:
            raise ValueError(msg)
        logger.warning(msg)
    audit = get_audit_log_service()
    await audit.write_event(session_id=session_id, event_type=event_type, **fields)
```

**Strict mode toggle:** ``AURION_AUDIT_STRICT`` env var. The pytest
conftest sets it to ``1`` for the whole test session. Production
runs without strict mode — a misspelled kwarg gets logged but the
audit event still writes. Losing an audit row to a typo is worse
than landing one with an extra field; the warning trail surfaces
it within minutes via CloudWatch alarms.

## Why not TypedDict?

The original ticket mentioned TypedDict. After the survey:

- Pyright isn't a CI gate yet, and ``**TypedDict`` unpacking
  isn't supported by every static checker.
- A runtime check catches typos in places no type checker would
  (e.g. dict comprehensions building kwargs, downstream callers
  passing through ``**kw`` from a base helper).
- The runtime version is one ``frozenset`` membership check —
  it's not on a hot path.

TypedDict stays available as a future enhancement (own backlog
item if compliance asks for static-time guarantees).

## Files

- `backend/app/core/audit_events.py` — add ``ALLOWED_AUDIT_KWARGS``
  + ``validate_audit_kwargs``.
- `backend/app/api/v1/_helpers.py` — wire validation into ``write_audit``.
- `backend/tests/unit/test_audit_events.py` — extend with whitelist
  coverage and strict-mode behavior tests.
- `backend/tests/conftest.py` (new) — auto-enable strict mode for
  every test in the suite (unit + e2e).

## DRY / SOLID gates

- **DRY:** every event's kwarg list defined exactly once, next to
  the enum it relates to. Call sites still pass natural kwargs.
- **SRP:** ``validate_audit_kwargs`` is a pure function. The enum
  catalog has no behavior. ``write_audit`` keeps its single
  responsibility (emit one event) plus a one-line guard.
- **OCP:** new events require a new whitelist entry; the test fires
  if any enum member lacks one. No existing entries get edited
  unless an event genuinely takes new fields.

## Acceptance

```bash
# Every enum member has a whitelist entry (open-closed guard).
pytest backend/tests/unit/test_audit_events.py -v

# Strict mode catches typos at test time.
pytest backend -q   # 229 unit + 4 e2e + 3 new = 236 green expected

# Misspelled kwargs in the route layer break the e2e test immediately,
# not silently three weeks later in CloudWatch.
```

## Risk + mitigation

- **Whitelist drift:** a new event added without a whitelist entry
  trips ``test_every_audit_event_has_whitelist``. CI catches it.
- **Production traffic:** strict mode is OFF in production. A typo
  hits the warning log + still writes. Worst case: one DynamoDB row
  with an extra field; compliance can grep it. No runtime regression.
- **iOS-emitted events:** empty frozenset means "no extra fields."
  If iOS starts emitting through the backend (unlikely), the test
  trips and we widen the whitelist.
