"""VID-01 — the video-import master flag must default OFF (ships dark).

The feature touches a new PHI surface (uploaded video → server-side
processing), so like ``measurement_enabled`` it must be opt-in: the fallback
config (used when AppConfig is unreachable) defaults the flag False.
"""

from __future__ import annotations

from app.modules.config.schema import AppConfigSchema, FeatureFlagsConfig


def test_video_import_disabled_by_default() -> None:
    assert FeatureFlagsConfig().video_import_enabled is False


def test_video_import_flag_present_on_full_appconfig_default() -> None:
    cfg = AppConfigSchema()
    assert cfg.feature_flags.video_import_enabled is False


def test_video_import_flag_can_be_enabled() -> None:
    assert FeatureFlagsConfig(video_import_enabled=True).video_import_enabled is True
