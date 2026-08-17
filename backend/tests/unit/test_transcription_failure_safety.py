"""PHI-safe provider failure coverage for Stage 1 transcription."""

from __future__ import annotations

import traceback
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.types import ProviderError
from app.modules.transcription import service


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_error", [False, True])
async def test_transcription_provider_failure_never_surfaces_raw_text(
    provider_error: bool,
) -> None:
    phi_sentinel = "Marie Example private knee finding"
    failure = (
        ProviderError("whisper", phi_sentinel)
        if provider_error
        else RuntimeError(phi_sentinel)
    )
    expected_reason = (
        "transcription_provider_error"
        if provider_error
        else "transcription_unexpected_error"
    )
    provider = SimpleNamespace(transcribe=AsyncMock(side_effect=failure))
    registry = SimpleNamespace(
        get_transcription_provider=lambda **_kwargs: provider,
    )
    audit = SimpleNamespace(write_event=AsyncMock())
    usage = AsyncMock()
    alert = AsyncMock()

    with (
        patch.object(service, "upload_audio_to_s3", AsyncMock()),
        patch.object(service, "get_registry", return_value=registry),
        patch.object(service, "get_audit_log_service", return_value=audit),
        patch.object(service, "try_record_provider_usage", usage),
        patch.object(service, "try_publish_alert", alert),
    ):
        with pytest.raises(ProviderError) as caught:
            await service.transcribe_audio(b"audio", uuid.uuid4())

    assert str(caught.value) == "[transcription] Transcription failed."
    assert caught.value.original is None
    assert phi_sentinel not in "".join(
        traceback.format_exception(caught.value)
    )
    assert phi_sentinel not in repr(audit.write_event.await_args_list)
    assert phi_sentinel not in repr(alert.await_args_list)
    assert phi_sentinel not in repr(usage.await_args_list)
    assert audit.write_event.await_args.kwargs["error_message"] == expected_reason
    assert "reason" not in alert.await_args.kwargs["metadata"]
