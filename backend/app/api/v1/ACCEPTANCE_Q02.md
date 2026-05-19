# Q-02 — Privacy purge cleanup (Acceptance Criteria)

## Primary goal

Flatten the 5-level nesting in
`_purge_s3_objects_for_sessions` (`privacy.py:259`) by extracting an
inner `_purge_session_prefix(s3, bucket, prefix) -> int` helper.

## Secondary goal (latent-bug fix)

`delete_my_account` (`privacy.py:337`) emits the `account_deleted`
audit event from two branches:

  * **session_ids non-empty** (lines 393-403) — uses real counters.
  * **session_ids empty** (lines 406-416) — **hardcodes zeros** for
    every counter.

The hardcoded branch is wrong for one narrow case: a user with
`pilot_metrics` rows but no sessions still has those rows deleted at
line 374, but the audit log records `deleted_pilot_metrics=0`. Q-02
collapses both branches to a single loop using the real
`metric_count`, fixing the bug as a side effect of the dedup.

## Out of scope

- Behavior changes to S3 purge order or error swallowing.
- The route still returns the same `DeletionResult` shape.

## Approach

```python
def _purge_session_prefix(s3, bucket: str, prefix: str) -> int:
    """Delete every object under ``s3://{bucket}/{prefix}`` and return
    the count. Errors are swallowed (logged) — purge is best-effort.
    """
    deleted = 0
    try:
        paginator = s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            keys = [{"Key": obj["Key"]} for obj in objects]
            s3.delete_objects(Bucket=bucket, Delete={"Objects": keys, "Quiet": True})
            deleted += len(keys)
    except Exception:
        logger.warning("S3 purge error: bucket=%s prefix=%s", bucket, prefix, exc_info=True)
    return deleted


def _purge_s3_objects_for_sessions(session_ids: list[uuid.UUID]) -> int:
    s3 = get_s3_client()
    return sum(
        _purge_session_prefix(s3, bucket, str(sid))
        for bucket in (AUDIO_BUCKET, FRAMES_BUCKET)
        for sid in session_ids
    )
```

For the audit-write collapse:

```python
audit_targets = [str(sid) for sid in session_ids] or [f"account-{user.user_id}"]
audit_kwargs = dict(
    clinician_id=str(user.user_id),
    deleted_sessions=session_count,
    deleted_note_versions=note_count,
    deleted_pilot_metrics=metric_count,
    deleted_s3_objects=s3_deleted,
    retention_note="Audit logs pseudonymized, retained 7 years for compliance",
)
for target in audit_targets:
    await write_audit(target, AuditEventType.ACCOUNT_DELETED, **audit_kwargs)
```

## DRY / SOLID gates

- **DRY:** the audit-write block exists in one place after the refactor.
  Same string ("Audit logs pseudonymized, …") was written twice; now once.
- **SRP:** `_purge_session_prefix` does one thing — purge a single
  prefix in a single bucket. `_purge_s3_objects_for_sessions` does
  the cartesian-product iteration. Each function is < 20 lines.
- **OCP:** adding a new bucket means adding it to the tuple at the
  callsite, not editing the inner helper.

## Acceptance

```bash
# Nesting reduced — the deepest indented line inside
# _purge_session_prefix is the for-loop body (3 levels), not the
# original 5.
grep -n '^\s\{20,\}' backend/app/api/v1/privacy.py | head
# (no lines should match for the purge region)

pytest backend -q  # 228 unit + 3 e2e green; new regression test makes it 229+3
```

## Files

- `backend/app/api/v1/privacy.py` — refactor
- `backend/tests/unit/test_privacy_deletion.py` — new regression test
  for the metric_count fix
