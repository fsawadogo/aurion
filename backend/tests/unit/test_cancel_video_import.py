"""Cancelling a wedged video import.

Before this, the only exit from a stuck import was the 15-minute watchdog —
and that only fires while something is polling, so a clinician who closed the
tab had no way out at all.

Two properties matter beyond "it marks the row failed":

  * `retryable` must mirror `start_processing`'s guards exactly, or the UI
    offers a Retry that 409s. It is False once processing has begun, because
    the orchestrator purges the raw clip fail-closed on both success AND
    failure — there is nothing left to re-process.
  * A cancelled job must STAY cancelled. /cancel marks the row but cannot kill
    the detached orchestrator task, so a late finisher must stand down rather
    than flip the job back to `completed`.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.core.types import SessionState


def _session(state=SessionState.CONSENT_PENDING, consent=True):
    return SimpleNamespace(id=uuid.uuid4(), state=state, consent_confirmed=consent)


def _job(status="running", key="video-imports/x/clip.mp4", purged_at=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        status=status,
        raw_video_s3_key=key,
        raw_video_purged_at=purged_at,
        error_message=None,
    )


class _S3Ok:
    def head_object(self, **_kwargs):
        return {"ContentLength": 1}


class _S3Missing:
    def head_object(self, **_kwargs):
        from botocore.exceptions import ClientError

        raise ClientError({"Error": {"Code": "404"}}, "HeadObject")


class TestRetryEligibility:
    """`retryable` must not promise a retry that /process would reject."""

    def test_retryable_when_untouched_and_clip_present(self):
        from app.api.v1 import video_import as vi

        with patch.object(vi, "get_s3_client", return_value=_S3Ok()):
            ok, reason = vi._retry_eligibility(_session(), _job())
        assert ok is True
        assert reason is None

    def test_not_retryable_once_processing_started(self):
        """The clip is purged fail-closed, so there is nothing to re-process."""
        from app.api.v1 import video_import as vi

        with patch.object(vi, "get_s3_client", return_value=_S3Ok()):
            ok, reason = vi._retry_eligibility(
                _session(state=SessionState.PROCESSING_STAGE1), _job()
            )
        assert ok is False
        assert "already started" in reason

    def test_not_retryable_without_consent(self):
        from app.api.v1 import video_import as vi

        with patch.object(vi, "get_s3_client", return_value=_S3Ok()):
            ok, reason = vi._retry_eligibility(_session(consent=False), _job())
        assert ok is False

    def test_not_retryable_when_purge_stamped(self):
        from app.api.v1 import video_import as vi

        with patch.object(vi, "get_s3_client", return_value=_S3Ok()):
            ok, reason = vi._retry_eligibility(
                _session(), _job(purged_at="2026-08-13T00:00:00Z")
            )
        assert ok is False
        assert "deleted" in reason

    def test_not_retryable_when_object_actually_gone(self):
        """The purge stamp is best-effort — trust S3, not the column."""
        from app.api.v1 import video_import as vi

        with patch.object(vi, "get_s3_client", return_value=_S3Missing()):
            ok, reason = vi._retry_eligibility(_session(), _job())
        assert ok is False
        assert "no longer available" in reason


class TestCancelRoute:
    @pytest.mark.asyncio
    async def test_cancel_marks_failed_and_audits(self):
        from app.api.v1 import video_import as vi

        session, job = _session(), _job(status="running")
        mark_failed = AsyncMock()
        audit = AsyncMock()

        with (
            patch.object(vi, "get_owned_session_or_404", AsyncMock(return_value=session)),
            patch.object(vi.jobs, "get_job_for_session", AsyncMock(return_value=job)),
            patch.object(vi.jobs, "mark_failed", mark_failed),
            patch.object(vi, "write_audit", audit),
            patch.object(vi, "get_s3_client", return_value=_S3Ok()),
        ):
            resp = await vi.cancel_video_import(
                session.id, None, SimpleNamespace(user_id=uuid.uuid4()), AsyncMock()
            )

        assert mark_failed.await_count == 1
        assert mark_failed.await_args.args[2] == vi.CANCEL_REASON
        assert resp.retryable is True
        # The audit reason must be PHI-free and name the cause.
        assert audit.await_args.kwargs["reason"] == vi.CANCEL_REASON

    @pytest.mark.asyncio
    async def test_cancel_rejects_an_already_finished_job(self):
        from app.api.v1 import video_import as vi

        session, job = _session(), _job(status="completed")
        with (
            patch.object(vi, "get_owned_session_or_404", AsyncMock(return_value=session)),
            patch.object(vi.jobs, "get_job_for_session", AsyncMock(return_value=job)),
        ):
            with pytest.raises(HTTPException) as exc:
                await vi.cancel_video_import(
                    session.id, None, SimpleNamespace(user_id=uuid.uuid4()), AsyncMock()
                )
        assert exc.value.status_code == 409

    @pytest.mark.asyncio
    async def test_cancel_reports_not_retryable_after_processing_began(self):
        """The UI must offer 'Start over', not a Retry that would 409."""
        from app.api.v1 import video_import as vi

        session = _session(state=SessionState.PROCESSING_STAGE1)
        job = _job(status="running")

        with (
            patch.object(vi, "get_owned_session_or_404", AsyncMock(return_value=session)),
            patch.object(vi.jobs, "get_job_for_session", AsyncMock(return_value=job)),
            patch.object(vi.jobs, "mark_failed", AsyncMock()),
            patch.object(vi, "write_audit", AsyncMock()),
            patch.object(vi, "get_s3_client", return_value=_S3Ok()),
        ):
            resp = await vi.cancel_video_import(
                session.id, None, SimpleNamespace(user_id=uuid.uuid4()), AsyncMock()
            )

        assert resp.retryable is False
        assert resp.retry_blocked_reason
