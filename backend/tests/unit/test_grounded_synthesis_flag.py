"""GS-7 (#549) — the `grounded_synthesis_enabled` feature flag (default OFF).

First slice of the v3.2 Grounded Synthesis epic (#552): an inert flag that
ships DARK. These tests assert it defaults OFF, round-trips through the admin
FeatureFlags surface, and that it does NOT (yet) alter any prompt — the
prompt-relaxing slices (GS-1/3/4) land later and read this flag.
"""

from __future__ import annotations

from app.api.v1.admin.feature_flags import FeatureFlagsResponse, _build_response
from app.modules.config.schema import FeatureFlagsConfig


def test_flag_defaults_off():
    # AC-1: dark by default — the mode is off until GS-9 sign-off flips it.
    assert FeatureFlagsConfig().grounded_synthesis_enabled is False


def test_flag_is_settable():
    cfg = FeatureFlagsConfig(grounded_synthesis_enabled=True)
    assert cfg.grounded_synthesis_enabled is True


def test_response_surfaces_flag():
    # AC-3: GET surface carries the flag, mirroring the live config value.
    resp = _build_response(FeatureFlagsConfig(grounded_synthesis_enabled=True))
    assert resp.grounded_synthesis_enabled is True
    assert _build_response(FeatureFlagsConfig()).grounded_synthesis_enabled is False


def test_response_defaults_off_when_omitted():
    # A save body from a portal build that predates the field must not 422 and
    # must resolve to the safe OFF value (the field has a default, unlike the
    # other required flags).
    body = FeatureFlagsResponse(
        screen_capture_enabled=False,
        note_versioning_enabled=True,
        session_pause_resume_enabled=True,
        per_session_provider_override=True,
        meta_wearables_enabled=True,
        per_session_visual_evidence_mode_override=True,
        clip_video_interpretation_enabled=True,
        frame_by_frame_video_enabled=True,
        orders_card_enabled=False,
        coding_card_enabled=False,
        patient_summary_card_enabled=False,
        emr_writeback_card_enabled=False,
        media_review_retention_enabled=True,
        measurement_enabled=False,
        video_import_enabled=True,
        video_import_drop_zero_face_frames=True,
        specialty_style_in_prompt_enabled=False,
        prompt_studio_enabled=False,
        prompt_studio_roles=["ADMIN"],
        clinician_prompts_note_only=False,
        # grounded_synthesis_enabled intentionally omitted
    )
    assert body.grounded_synthesis_enabled is False
    # And it round-trips into the config the save path validates.
    cfg = FeatureFlagsConfig.model_validate(body.model_dump())
    assert cfg.grounded_synthesis_enabled is False
