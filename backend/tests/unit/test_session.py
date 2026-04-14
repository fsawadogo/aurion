"""Tests for session state machine — validates all transitions and consent hard block."""

import uuid

import pytest

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

    def test_processing_stage1_to_awaiting_review(self):
        assert VALID_TRANSITIONS[SessionState.PROCESSING_STAGE1] == [SessionState.AWAITING_REVIEW]

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
    def test_ten_states_exist(self):
        """The spec requires exactly 10 states."""
        assert len(SessionState) == 10

    def test_no_state_can_skip_consent(self):
        """RECORDING cannot be reached from IDLE — must go through CONSENT_PENDING."""
        assert SessionState.RECORDING not in VALID_TRANSITIONS[SessionState.IDLE]
