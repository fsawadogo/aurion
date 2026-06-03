"""Unit tests for `resolve_evidence_mode` (P1-7).

The helper is the single read path for the per-session override; this
suite locks the four cases the Stage 2 dispatch needs:

  1. Session override wins over the AppConfig global default.
  2. AppConfig default wins when no override is set.
  3. Invalid override string raises ValueError so the caller can choose
     to fall back to the default with a warning.
  4. Legacy `str(dict)` rows decode as None and fall through cleanly
     (no exception bubbles up from the JSON parse).

DRY: the suite proves the helper is the ONE place that reads
`session.provider_overrides`. Future override keys land by extending
the dict and the schema, not by adding a new read site.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.modules.config.schema import (
    AppConfigSchema,
    PipelineConfig,
    VisualEvidenceMode,
)
from app.modules.vision.service import resolve_evidence_mode


def _stub_session(provider_overrides: str | None):
    """A SessionModel stand-in carrying only the field the resolver
    reads. SimpleNamespace keeps the test orthogonal from SQLAlchemy."""
    return SimpleNamespace(provider_overrides=provider_overrides)


def _config(mode: VisualEvidenceMode = VisualEvidenceMode.FRAMES_ONLY) -> AppConfigSchema:
    return AppConfigSchema(pipeline=PipelineConfig(visual_evidence_mode=mode))


# ── Resolution order ────────────────────────────────────────────────────────


def test_session_override_wins_over_global_default():
    """clips_only on the session takes precedence over frames_only global."""
    session = _stub_session('{"visual_evidence_mode": "clips_only"}')
    cfg = _config(VisualEvidenceMode.FRAMES_ONLY)

    assert resolve_evidence_mode(session, cfg) == VisualEvidenceMode.CLIPS_ONLY


def test_session_override_wins_when_global_is_also_non_default():
    """Override wins regardless of which mode the global is at — the
    resolver doesn't 'merge' modes, it picks one."""
    session = _stub_session('{"visual_evidence_mode": "frames_only"}')
    cfg = _config(VisualEvidenceMode.CLIPS_ONLY)

    assert resolve_evidence_mode(session, cfg) == VisualEvidenceMode.FRAMES_ONLY


def test_returns_global_default_when_no_override():
    session = _stub_session(None)
    cfg = _config(VisualEvidenceMode.HYBRID)

    assert resolve_evidence_mode(session, cfg) == VisualEvidenceMode.HYBRID


def test_returns_global_default_when_override_dict_omits_mode_key():
    """Override dict exists but carries other keys only — still falls
    through to the AppConfig default."""
    session = _stub_session('{"vision": "anthropic"}')
    cfg = _config(VisualEvidenceMode.FRAMES_ONLY)

    assert resolve_evidence_mode(session, cfg) == VisualEvidenceMode.FRAMES_ONLY


# ── Defensive behavior ──────────────────────────────────────────────────────


def test_invalid_session_mode_raises_value_error():
    """Hand-edited / corrupt session row — caller catches + falls back."""
    session = _stub_session('{"visual_evidence_mode": "not_a_real_mode"}')
    cfg = _config(VisualEvidenceMode.FRAMES_ONLY)

    with pytest.raises(ValueError):
        resolve_evidence_mode(session, cfg)


def test_legacy_str_dict_row_decodes_as_none_and_falls_through():
    """Pre-P1-7 rows used `str(dict)` (Python repr, not JSON). Decoder
    catches the ValueError and the resolver falls through to the
    AppConfig default — these rows continue working, they just don't
    carry an override on read.
    """
    session = _stub_session("{'visual_evidence_mode': 'clips_only'}")  # single quotes
    cfg = _config(VisualEvidenceMode.FRAMES_ONLY)

    assert resolve_evidence_mode(session, cfg) == VisualEvidenceMode.FRAMES_ONLY


def test_empty_string_overrides_falls_through():
    """Empty-string column → no override; AppConfig default wins."""
    session = _stub_session("")
    cfg = _config(VisualEvidenceMode.CLIPS_ONLY)

    assert resolve_evidence_mode(session, cfg) == VisualEvidenceMode.CLIPS_ONLY


def test_non_dict_json_payload_falls_through():
    """Legacy / hand-edited row that happens to be valid JSON but not a
    dict (a list, a string, a number). Should not crash — just no
    override read."""
    session = _stub_session('["clips_only"]')
    cfg = _config(VisualEvidenceMode.FRAMES_ONLY)

    assert resolve_evidence_mode(session, cfg) == VisualEvidenceMode.FRAMES_ONLY


# ── AppConfig dependency-inversion ──────────────────────────────────────────


def test_config_arg_optional_falls_back_to_get_config(monkeypatch):
    """When caller doesn't pass an AppConfig snapshot, the resolver
    fetches via the existing get_config() singleton. Verifies the DIP
    contract — the helper never instantiates a concrete config inline."""
    sentinel_config = _config(VisualEvidenceMode.HYBRID)
    monkeypatch.setattr(
        "app.modules.vision.service.get_config",
        lambda: sentinel_config,
    )
    session = _stub_session(None)

    assert resolve_evidence_mode(session) == VisualEvidenceMode.HYBRID


# ── PHI scan ────────────────────────────────────────────────────────────────


def test_no_phi_in_resolve_call_path(caplog):
    """Sanity: the resolver doesn't emit any log lines today (it's a
    pure read), but if it ever starts logging, PHI keys must not leak.
    This test wraps `caplog` so it fails the moment a transcript or
    patient identifier shows up in the resolver's log output.
    """
    import logging

    session = _stub_session(
        '{"visual_evidence_mode": "clips_only"}'
    )
    cfg = _config(VisualEvidenceMode.FRAMES_ONLY)

    with caplog.at_level(logging.DEBUG, logger="aurion.vision"):
        resolve_evidence_mode(session, cfg)

    forbidden = ("transcript", "encounter_context", "external_reference_id", "patient_id")
    for record in caplog.records:
        msg = record.getMessage().lower()
        for term in forbidden:
            assert term not in msg, (
                f"resolve_evidence_mode log line leaked '{term}': {msg!r}"
            )
