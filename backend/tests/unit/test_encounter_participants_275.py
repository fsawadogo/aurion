"""Unit tests for encounter participants + day-roster marker (#275).

Covers the IMPLEMENT-NOW scope (per-member access control is deferred):

  * B1 — ``SessionParticipantRequest`` validator: anonymous role chips
    (``source="adhoc_role"``) must NOT carry a name; ``source="profile"``
    requires one; ``is_persistent`` is derived from ``source``.
  * B2 — ``sessions._to_response`` surfaces ``participants`` round-trip and
    swallows a malformed ``participants_json`` to ``None``.
  * B3 — attribution rendering: the gate fires for a SINGLE participant
    (the enrolling clinician is an implicit second speaker), and an
    anonymous chip renders role-only with NO synthesized name and no
    ``KeyError``. Verified against both the live provider prompt
    (``shared.build_user_prompt``) and the tested helper
    (``note_gen.service.build_stage1_user_prompt``).
  * B4 — ``profile._annotate_team_presence`` effective-today logic +
    stale-date daily auto-reset.
  * B5 — the allied-health team cap is a named constant (default 8) and
    rejects rosters above it.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.api.v1.profile import _annotate_team_presence
from app.api.v1.sessions import SessionParticipantRequest, _to_response
from app.core.types import (
    SessionState,
    Template,
    TemplateSection,
    Transcript,
    TranscriptSegment,
)
from app.modules.note_gen.service import build_stage1_user_prompt
from app.modules.profile.service import (
    MAX_ALLIED_HEALTH_TEAM_MEMBERS,
    update_profile,
)
from app.modules.providers.note_gen.shared import (
    build_user_prompt,
    render_participants_block,
)

# ── B1 — SessionParticipantRequest validator ─────────────────────────────

class TestParticipantRequestValidator:
    def test_adhoc_role_rejects_a_name(self) -> None:
        with pytest.raises(ValidationError):
            SessionParticipantRequest(
                name="Sarah Chen", role="nurse", source="adhoc_role"
            )

    def test_adhoc_role_without_name_is_anonymous_and_not_persistent(self) -> None:
        p = SessionParticipantRequest(role="nurse", source="adhoc_role")
        assert p.name is None
        assert p.is_persistent is False

    def test_adhoc_role_blank_name_is_allowed_and_normalized_to_none(self) -> None:
        p = SessionParticipantRequest(
            name="   ", role="nurse", source="adhoc_role"
        )
        assert p.name is None

    def test_profile_requires_a_name(self) -> None:
        with pytest.raises(ValidationError):
            SessionParticipantRequest(role="resident", source="profile")

    def test_profile_member_is_persistent_and_name_stripped(self) -> None:
        p = SessionParticipantRequest(
            name="  Dr. Lee  ", role="physician", source="profile"
        )
        assert p.name == "Dr. Lee"
        assert p.is_persistent is True

    def test_default_source_is_adhoc_named_and_not_persistent(self) -> None:
        p = SessionParticipantRequest(name="Alex Wu", role="scribe")
        assert p.source == "adhoc_named"
        assert p.is_persistent is False

    def test_adhoc_named_blank_name_degrades_to_none(self) -> None:
        p = SessionParticipantRequest(name="", role="scribe")
        assert p.name is None

    def test_client_sent_is_persistent_is_overridden_by_source(self) -> None:
        # Client claims persistent on an adhoc chip — the derived flag wins.
        p = SessionParticipantRequest(
            name="Alex Wu", role="scribe",
            source="adhoc_named", is_persistent=True,
        )
        assert p.is_persistent is False

    def test_model_dump_carries_all_persistence_keys(self) -> None:
        dumped = SessionParticipantRequest(
            name="Dr. Lee", role="physician", source="profile"
        ).model_dump()
        assert dumped == {
            "name": "Dr. Lee",
            "role": "physician",
            "source": "profile",
            "is_persistent": True,
        }


# ── B2 — _to_response surfaces participants (round-trip + defensive) ──────

def _fake_session(participants_json):
    now = datetime.now(timezone.utc)
    return SimpleNamespace(
        id=uuid.uuid4(),
        clinician_id=uuid.uuid4(),
        specialty="orthopedic_surgery",
        state=SessionState.RECORDING,
        encounter_type="doctor_patient",
        capture_mode="multimodal",
        external_reference_id_encrypted=None,
        provider_overrides=None,
        participants_json=participants_json,
        created_at=now,
        updated_at=now,
    )


class TestToResponseParticipants:
    def test_round_trip_returns_participants(self) -> None:
        members = [
            {"name": "Dr. Lee", "role": "physician",
             "source": "profile", "is_persistent": True},
            {"name": None, "role": "nurse",
             "source": "adhoc_role", "is_persistent": False},
        ]
        resp = _to_response(_fake_session(json.dumps(members)))
        assert resp.participants == members

    def test_null_column_yields_none(self) -> None:
        assert _to_response(_fake_session(None)).participants is None

    def test_malformed_json_is_swallowed_to_none(self) -> None:
        # Legacy str(dict) / garbage must never 500 the response.
        assert _to_response(_fake_session("{not json")).participants is None

    def test_non_list_json_is_dropped(self) -> None:
        assert _to_response(_fake_session('{"a": 1}')).participants is None


# ── B3 — attribution rendering (gate + anonymous chips) ──────────────────

def _transcript() -> Transcript:
    return Transcript(
        session_id="s",
        provider_used="whisper",
        segments=[
            TranscriptSegment(id="seg_001", start_ms=0, end_ms=1000, text="hi")
        ],
    )


def _template() -> Template:
    return Template(
        key="orthopedic_surgery",
        display_name="Orthopedic Surgery",
        sections=[TemplateSection(id="cc", title="CC")],
    )


class TestRenderParticipantsBlock:
    def test_empty_returns_blank(self) -> None:
        assert render_participants_block([]) == ""
        assert render_participants_block(None) == ""

    def test_single_named_member_fires_the_gate(self) -> None:
        block = render_participants_block(
            [{"name": "Dr. Lee", "role": "physician"}]
        )
        assert "ENCOUNTER PARTICIPANTS:" in block
        assert "- Dr. Lee (Physician)" in block

    def test_anonymous_chip_renders_role_only_no_name(self) -> None:
        block = render_participants_block(
            [{"name": None, "role": "scrub_nurse", "source": "adhoc_role"}]
        )
        assert "- (Scrub Nurse), unnamed" in block
        # NEVER synthesize a name and never leak the literal "None".
        assert "None" not in block

    def test_mixed_named_and_anonymous(self) -> None:
        block = render_participants_block([
            {"name": "Dr. Lee", "role": "physician"},
            {"name": None, "role": "nurse", "source": "adhoc_role"},
        ])
        assert "- Dr. Lee (Physician)" in block
        assert "- (Nurse), unnamed" in block

    def test_missing_role_key_does_not_raise(self) -> None:
        # Defensive: a chip missing 'role' renders an empty role, no KeyError.
        block = render_participants_block([{"name": "X"}])
        assert "- X ()" in block


class TestBuildUserPromptParticipants:
    """The LIVE provider path (shared.build_user_prompt)."""

    def test_block_injected_for_single_member(self) -> None:
        prompt = build_user_prompt(
            _transcript(), _template(), stage=1,
            participants=[{"name": "Dr. Lee", "role": "physician"}],
        )
        assert "ENCOUNTER PARTICIPANTS:" in prompt
        assert "- Dr. Lee (Physician)" in prompt

    def test_anonymous_chip_no_keyerror_role_only(self) -> None:
        prompt = build_user_prompt(
            _transcript(), _template(), stage=1,
            participants=[{"name": None, "role": "nurse", "source": "adhoc_role"}],
        )
        assert "- (Nurse), unnamed" in prompt

    def test_no_participants_omits_block(self) -> None:
        prompt = build_user_prompt(_transcript(), _template(), stage=1)
        assert "ENCOUNTER PARTICIPANTS" not in prompt


class TestBuildStage1UserPromptParticipants:
    """The tested helper (note_gen.service.build_stage1_user_prompt) —
    gate fix + anonymous-chip safety (no KeyError on a null name)."""

    def test_single_member_fires_gate(self) -> None:
        prompt = build_stage1_user_prompt(
            _transcript(), _template(),
            participants=[{"name": "Dr. Lee", "role": "physician"}],
        )
        assert "ENCOUNTER PARTICIPANTS:" in prompt
        assert "- Dr. Lee (Physician)" in prompt

    def test_anonymous_chip_role_only_no_keyerror(self) -> None:
        # Pre-#275 this raised KeyError on p['name']; must not now.
        prompt = build_stage1_user_prompt(
            _transcript(), _template(),
            participants=[{"role": "nurse", "source": "adhoc_role"}],
        )
        assert "- (Nurse), unnamed" in prompt
        assert "None" not in prompt.split("Transcript")[0]

    def test_no_participants_omits_block(self) -> None:
        prompt = build_stage1_user_prompt(_transcript(), _template())
        assert "ENCOUNTER PARTICIPANTS" not in prompt


# ── B4 — present-today marker (effective + stale auto-reset) ──────────────

class TestAnnotateTeamPresence:
    def test_present_today_with_today_date_is_effective(self) -> None:
        today = date.today().isoformat()
        out = _annotate_team_presence(
            [{"name": "Sarah", "role": "RN",
              "present_today": True, "present_today_date": today}]
        )
        assert out[0]["present_today_effective"] is True

    def test_stale_date_auto_resets_to_absent(self) -> None:
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        out = _annotate_team_presence(
            [{"name": "Sarah", "role": "RN",
              "present_today": True, "present_today_date": yesterday}]
        )
        # The whole point: no cron — a stale flag reads absent on READ.
        assert out[0]["present_today_effective"] is False

    def test_flag_false_today_is_absent(self) -> None:
        today = date.today().isoformat()
        out = _annotate_team_presence(
            [{"name": "Sarah", "role": "RN",
              "present_today": False, "present_today_date": today}]
        )
        assert out[0]["present_today_effective"] is False

    def test_missing_keys_default_absent(self) -> None:
        out = _annotate_team_presence([{"name": "Sarah", "role": "RN"}])
        assert out[0]["present_today_effective"] is False
        # Raw stored fields untouched (round-trippable for the editor).
        assert out[0]["name"] == "Sarah"

    def test_raw_keys_are_preserved(self) -> None:
        today = date.today().isoformat()
        out = _annotate_team_presence(
            [{"name": "Sarah", "role": "RN",
              "present_today": True, "present_today_date": today}]
        )
        assert out[0]["present_today"] is True
        assert out[0]["present_today_date"] == today

    def test_non_dict_entry_passes_through(self) -> None:
        out = _annotate_team_presence(["junk"])  # type: ignore[list-item]
        assert out == ["junk"]


# ── B5 — allied-health team cap (named constant, default 8) ───────────────

def _mock_db_with_profile() -> tuple[MagicMock, SimpleNamespace]:
    profile = SimpleNamespace(allied_health_team="[]")
    result = MagicMock()
    result.scalar_one_or_none.return_value = profile
    db = MagicMock()
    db.execute = AsyncMock(return_value=result)
    db.flush = AsyncMock()
    return db, profile


class TestTeamCap:
    def test_cap_constant_default(self) -> None:
        assert MAX_ALLIED_HEALTH_TEAM_MEMBERS == 8

    @pytest.mark.asyncio
    async def test_roster_above_cap_is_rejected(self) -> None:
        db, _profile = _mock_db_with_profile()
        oversized = [
            {"name": f"M{i}", "role": "RN"}
            for i in range(MAX_ALLIED_HEALTH_TEAM_MEMBERS + 1)
        ]
        with pytest.raises(ValueError, match="Maximum 8 allied health"):
            await update_profile(
                db, uuid.uuid4(), {"allied_health_team": oversized}
            )

    @pytest.mark.asyncio
    async def test_roster_at_cap_is_accepted(self) -> None:
        db, profile = _mock_db_with_profile()
        at_cap = [
            {"name": f"M{i}", "role": "RN"}
            for i in range(MAX_ALLIED_HEALTH_TEAM_MEMBERS)
        ]
        await update_profile(db, uuid.uuid4(), {"allied_health_team": at_cap})
        stored = json.loads(profile.allied_health_team)
        assert len(stored) == MAX_ALLIED_HEALTH_TEAM_MEMBERS

    @pytest.mark.asyncio
    async def test_present_today_keys_persist_on_write(self) -> None:
        db, profile = _mock_db_with_profile()
        today = date.today().isoformat()
        team = [{
            "name": "Sarah", "role": "RN",
            "present_today": True, "present_today_date": today,
        }]
        await update_profile(db, uuid.uuid4(), {"allied_health_team": team})
        stored = json.loads(profile.allied_health_team)
        assert stored[0]["present_today"] is True
        assert stored[0]["present_today_date"] == today
