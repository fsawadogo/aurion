"""Tests for session state machine — validates all transitions and consent hard block."""



from app.core.types import SessionState
from app.modules.session.service import (
    VALID_TRANSITIONS,
    ConsentRequiredError,
    InvalidTransitionError,
    get_audit_event_for_state,
)


class TestValidTransitions:
    """Verify the state machine transition table is correct."""

    def test_idle_only_to_consent_pending(self):
        assert VALID_TRANSITIONS[SessionState.IDLE] == [SessionState.CONSENT_PENDING]

    def test_consent_pending_only_to_recording(self):
        assert VALID_TRANSITIONS[SessionState.CONSENT_PENDING] == [SessionState.RECORDING]

    def test_recording_to_paused_or_processing(self):
        allowed = VALID_TRANSITIONS[SessionState.RECORDING]
        assert SessionState.PAUSED in allowed
        assert SessionState.PROCESSING_STAGE1 in allowed

    def test_paused_to_recording_or_processing(self):
        allowed = VALID_TRANSITIONS[SessionState.PAUSED]
        assert SessionState.RECORDING in allowed
        assert SessionState.PROCESSING_STAGE1 in allowed

    def test_processing_stage1_to_awaiting_review_or_failed_no_audio(self):
        # lane-backend/empty-transcript-guard: PROCESSING_STAGE1 also drops
        # into STAGE1_FAILED_NO_AUDIO when the entry guard fires (no
        # transcript / too short — see modules/note_gen/service.py).
        allowed = VALID_TRANSITIONS[SessionState.PROCESSING_STAGE1]
        assert SessionState.AWAITING_REVIEW in allowed
        assert SessionState.STAGE1_FAILED_NO_AUDIO in allowed

    def test_stage1_failed_no_audio_is_terminal(self):
        """The guard-fail state is terminal — the only recovery is a
        session discard (DELETE /sessions/{id}); there's no audio to
        retry against."""
        assert VALID_TRANSITIONS[SessionState.STAGE1_FAILED_NO_AUDIO] == []

    def test_processing_stage1_to_stage1_failed(self):
        """Generic note-gen provider failure (parse error / rate limit /
        timeout) drops PROCESSING_STAGE1 into the terminal STAGE1_FAILED —
        previously this path left the session stranded in PROCESSING_STAGE1."""
        assert (
            SessionState.STAGE1_FAILED
            in VALID_TRANSITIONS[SessionState.PROCESSING_STAGE1]
        )

    def test_stage1_failed_is_terminal_with_audit_mapping(self):
        from app.core.audit_events import AuditEventType
        from app.modules.session.service import STATE_AUDIT_EVENTS

        assert VALID_TRANSITIONS[SessionState.STAGE1_FAILED] == []
        assert (
            STATE_AUDIT_EVENTS[SessionState.STAGE1_FAILED]
            is AuditEventType.STAGE1_FAILED
        )

    def test_awaiting_review_to_processing_stage2(self):
        assert VALID_TRANSITIONS[SessionState.AWAITING_REVIEW] == [SessionState.PROCESSING_STAGE2]

    def test_processing_stage2_to_review_complete(self):
        assert VALID_TRANSITIONS[SessionState.PROCESSING_STAGE2] == [SessionState.REVIEW_COMPLETE]

    def test_review_complete_to_exported(self):
        assert VALID_TRANSITIONS[SessionState.REVIEW_COMPLETE] == [SessionState.EXPORTED]

    def test_exported_to_purged(self):
        assert VALID_TRANSITIONS[SessionState.EXPORTED] == [SessionState.PURGED]

    def test_purged_is_terminal(self):
        assert VALID_TRANSITIONS[SessionState.PURGED] == []

    def test_all_states_have_transition_entry(self):
        """Every state in the enum must have an entry in the transitions table."""
        for state in SessionState:
            assert state in VALID_TRANSITIONS, f"Missing transition entry for {state}"


class TestInvalidTransitionError:
    def test_error_message(self):
        err = InvalidTransitionError(SessionState.IDLE, SessionState.RECORDING)
        assert "IDLE" in str(err)
        assert "RECORDING" in str(err)


class TestConsentRequiredError:
    def test_error_message(self):
        err = ConsentRequiredError()
        assert "consent" in str(err).lower()


class TestAuditEventMapping:
    def test_all_states_have_audit_event(self):
        """Every state must map to an audit event."""
        for state in SessionState:
            event = get_audit_event_for_state(state)
            assert event is not None
            assert isinstance(event, str)
            assert len(event) > 0

    def test_specific_events(self):
        assert get_audit_event_for_state(SessionState.RECORDING) == "recording_started"
        assert get_audit_event_for_state(SessionState.PAUSED) == "session_paused"
        assert get_audit_event_for_state(SessionState.PURGED) == "session_purged"


class TestStateCompleteness:
    def test_state_count_matches_documented_set(self):
        """The CLAUDE.md spec pinned 10 happy-path states; two terminal
        off-ramps were added — STAGE1_FAILED_NO_AUDIO (empty-transcript
        guard) and STAGE1_FAILED (generic note-gen provider failure).
        Total is 10 + 2 = 12 — every state still maps in
        ``VALID_TRANSITIONS`` and ``STATE_AUDIT_EVENTS``."""
        assert len(SessionState) == 12
        # Every member has a transition entry — guard against silent
        # state additions that skip the transition table.
        for state in SessionState:
            assert state in VALID_TRANSITIONS

    def test_no_state_can_skip_consent(self):
        """RECORDING cannot be reached from IDLE — must go through CONSENT_PENDING."""
        assert SessionState.RECORDING not in VALID_TRANSITIONS[SessionState.IDLE]
