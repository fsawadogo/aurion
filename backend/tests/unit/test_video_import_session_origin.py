"""VID-09 — session origin in the response + portal feature-flags read."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.api.v1.sessions import _to_response
from app.core.types import SessionState


def _session(import_source):
    return SimpleNamespace(
        id=uuid.uuid4(),
        clinician_id=uuid.uuid4(),
        specialty="general",
        state=SessionState.AWAITING_REVIEW,
        encounter_type="doctor_patient",
        capture_mode="multimodal",
        import_source=import_source,
        external_reference_id_encrypted=None,
        provider_overrides=None,
        participants_json=None,
        created_at=None,
        updated_at=None,
    )


def test_import_source_surfaced_for_video_upload() -> None:
    assert _to_response(_session("video_upload")).import_source == "video_upload"


def test_import_source_none_for_live_session() -> None:
    assert _to_response(_session(None)).import_source is None


@pytest.mark.asyncio
async def test_portal_feature_flags_reads_config() -> None:
    from app.api.v1 import me

    cfg = SimpleNamespace(
        feature_flags=SimpleNamespace(
            video_import_enabled=True,
            multi_clip_import_enabled=True,
            cross_clinician_chart_enabled=True,
        )
    )
    with patch.object(me, "get_config", return_value=cfg):
        resp = await me.get_portal_feature_flags(_user=SimpleNamespace())
    assert resp.video_import_enabled is True
    assert resp.multi_clip_import_enabled is True
    assert resp.cross_clinician_chart_enabled is True
