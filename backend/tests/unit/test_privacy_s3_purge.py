"""Regression tests for the Law 25 erasure S3 purge (#337).

``DELETE /privacy/my-account`` used to call ``_purge_session_prefix``
with the BARE session UUID as the S3 prefix and only iterate
``(AUDIO_BUCKET, FRAMES_BUCKET)``. Two defects fell out of that:

  * Defect A — every object key is kind-prefixed
    (``audio/{sid}/…``, ``frames/{sid}/…``, ``clips/{sid}/…``,
    ``screen_frames/{sid}/…``). ``list_objects_v2`` ``Prefix`` is a
    literal leading match, so the bare UUID matched nothing → 0 deleted.
  * Defect B — the eval bucket (no lifecycle/TTL) was never scanned, so
    the migrated frames/clips copies survived erasure forever.

These tests exercise ``_purge_s3_objects_for_sessions`` against an
in-memory S3 fake that implements *real* ``Prefix`` semantics, so they
fail against the old bare-UUID-prefix / frames-bucket-only code (which
would return 0 and leave every object in place) and pass only once the
purge targets each real kind prefix in all three buckets.

LocalStack is not required: a MagicMock can't enforce prefix matching,
and a LocalStack-gated test would be skipped in CI (which runs only
``tests/unit/``) and never actually validate the fix. The fake below
matches keys exactly the way S3 does, which is what makes the test a
true regression guard.
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

from app.api.v1 import privacy
from app.core.s3 import AUDIO_BUCKET, EVAL_BUCKET, FRAMES_BUCKET


class _FakePaginator:
    """Minimal ``list_objects_v2`` paginator with real Prefix matching."""

    def __init__(self, store: dict[str, set[str]]):
        self._store = store

    def paginate(self, Bucket: str, Prefix: str):  # noqa: N803 — boto3 kwarg casing
        keys = sorted(k for k in self._store.get(Bucket, set()) if k.startswith(Prefix))
        # One page is enough for a unit test; chunking would not change
        # the assertions and `_purge_session_prefix` handles N pages.
        if keys:
            yield {"Contents": [{"Key": k} for k in keys]}
        else:
            yield {}


class _FakeS3:
    """In-memory S3 stand-in honoring the literal-leading-match Prefix
    contract that the real bug depended on."""

    def __init__(self, store: dict[str, set[str]]):
        self._store = store

    def get_paginator(self, operation_name: str) -> _FakePaginator:
        assert operation_name == "list_objects_v2"
        return _FakePaginator(self._store)

    def delete_objects(self, Bucket: str, Delete: dict):  # noqa: N803
        deleted = []
        for obj in Delete.get("Objects", []):
            key = obj["Key"]
            self._store.get(Bucket, set()).discard(key)
            deleted.append({"Key": key})
        return {"Deleted": deleted}

    def list_objects_v2(self, Bucket: str, Prefix: str, MaxKeys: int = 1000):  # noqa: N803
        keys = [k for k in self._store.get(Bucket, set()) if k.startswith(Prefix)]
        if keys:
            return {"Contents": [{"Key": k} for k in keys[:MaxKeys]], "KeyCount": len(keys)}
        return {"KeyCount": 0}


def _seed_session(store: dict[str, set[str]], sid: str) -> None:
    """Seed one object under every real kind prefix in all 3 buckets."""
    store.setdefault(AUDIO_BUCKET, set()).add(f"audio/{sid}/rec.wav")
    for bucket in (FRAMES_BUCKET, EVAL_BUCKET):
        store.setdefault(bucket, set()).update(
            {
                f"frames/{sid}/100.jpg",
                f"clips/{sid}/clip1.mp4",
                f"screen_frames/{sid}/200.jpg",
            }
        )


def test_purge_deletes_every_kind_prefix_across_all_buckets():
    """Seed audio/frames/clips/screen_frames in AUDIO + FRAMES + EVAL
    buckets, run the account-deletion purge path, and assert every prefix
    is empty afterward with a non-zero deleted count.

    Fails against the pre-#337 code: bare-UUID prefix matches nothing and
    the eval bucket is never scanned → 0 deleted, all objects survive.
    """
    sid = uuid.uuid4()
    sid_str = str(sid)
    store: dict[str, set[str]] = {}
    _seed_session(store, sid_str)

    fake = _FakeS3(store)
    with patch("app.api.v1.privacy.get_s3_client", return_value=fake):
        deleted = privacy._purge_s3_objects_for_sessions([sid])

    # 1 audio + 3 frames-bucket + 3 eval-bucket objects.
    assert deleted == 7, f"expected 7 objects purged, got {deleted}"

    # Every targeted prefix is now empty.
    targets = [
        (AUDIO_BUCKET, f"audio/{sid_str}/"),
        (FRAMES_BUCKET, f"frames/{sid_str}/"),
        (FRAMES_BUCKET, f"clips/{sid_str}/"),
        (FRAMES_BUCKET, f"screen_frames/{sid_str}/"),
        (EVAL_BUCKET, f"frames/{sid_str}/"),
        (EVAL_BUCKET, f"clips/{sid_str}/"),
        (EVAL_BUCKET, f"screen_frames/{sid_str}/"),
    ]
    for bucket, prefix in targets:
        remaining = fake.list_objects_v2(Bucket=bucket, Prefix=prefix).get("KeyCount", 0)
        assert remaining == 0, f"{bucket}/{prefix} still has {remaining} object(s)"

    # Nothing at all left for this session in any bucket.
    for bucket in (AUDIO_BUCKET, FRAMES_BUCKET, EVAL_BUCKET):
        assert not [k for k in store[bucket] if sid_str in k]


def test_purge_does_not_touch_other_sessions():
    """The purge must be scoped to the requested session(s) — another
    user's objects under the same kind prefixes must survive."""
    target = uuid.uuid4()
    other = uuid.uuid4()
    store: dict[str, set[str]] = {}
    _seed_session(store, str(target))
    _seed_session(store, str(other))

    fake = _FakeS3(store)
    with patch("app.api.v1.privacy.get_s3_client", return_value=fake):
        deleted = privacy._purge_s3_objects_for_sessions([target])

    assert deleted == 7
    # Every object belonging to the untouched session is still present.
    other_str = str(other)
    for bucket in (AUDIO_BUCKET, FRAMES_BUCKET, EVAL_BUCKET):
        survivors = [k for k in store[bucket] if other_str in k]
        assert survivors, f"{bucket}: other session's objects were wrongly purged"


def test_purge_sums_counts_across_multiple_sessions():
    """Multiple sessions: count is the sum of objects deleted per session."""
    sids = [uuid.uuid4() for _ in range(3)]
    store: dict[str, set[str]] = {}
    for sid in sids:
        _seed_session(store, str(sid))

    fake = _FakeS3(store)
    with patch("app.api.v1.privacy.get_s3_client", return_value=fake):
        deleted = privacy._purge_s3_objects_for_sessions(sids)

    assert deleted == 7 * len(sids)
    for bucket in (AUDIO_BUCKET, FRAMES_BUCKET, EVAL_BUCKET):
        assert store[bucket] == set()


def test_purge_no_sessions_is_zero():
    """Empty session list short-circuits to zero deletions."""
    fake = _FakeS3({})
    with patch("app.api.v1.privacy.get_s3_client", return_value=fake):
        assert privacy._purge_s3_objects_for_sessions([]) == 0
