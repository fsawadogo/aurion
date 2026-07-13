"""Unit tests for GET /me/feature-flags (portal flag exposure).

The portal reads this to gate surfaces for the signed-in clinician.
`template_authoring_chat_enabled` gates the "From a past encounter" entry into
Create-with-AI; verify it is surfaced and DARK by default.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.api.v1 import me as me_module


def _cfg(**overrides):
    base = {
        "video_import_enabled": False,
        "multi_clip_import_enabled": False,
        "cross_clinician_chart_enabled": False,
        "template_authoring_chat_enabled": False,
    }
    base.update(overrides)
    return SimpleNamespace(feature_flags=SimpleNamespace(**base))


@pytest.mark.asyncio
async def test_portal_flags_template_authoring_dark_by_default(monkeypatch):
    monkeypatch.setattr(me_module, "get_config", lambda: _cfg())
    resp = await me_module.get_portal_feature_flags(_user=MagicMock())
    assert resp.template_authoring_chat_enabled is False


@pytest.mark.asyncio
async def test_portal_flags_surfaces_template_authoring_when_on(monkeypatch):
    monkeypatch.setattr(
        me_module, "get_config", lambda: _cfg(template_authoring_chat_enabled=True)
    )
    resp = await me_module.get_portal_feature_flags(_user=MagicMock())
    assert resp.template_authoring_chat_enabled is True
