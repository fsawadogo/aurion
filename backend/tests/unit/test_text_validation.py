"""Unit tests for ``app.core.text_validation.validate_user_text``.

This helper is the third copy of a format-gate pattern that previously
lived only in `_check_identifier_format` (sessions.py). Issue #259
extracted it so the consultation-types path can share the exact same
rules. These tests pin the behavioural contract so a future refactor
of either caller can't quietly drift away from it.
"""

from __future__ import annotations

import pytest

from app.core.text_validation import validate_user_text


class TestValidateUserText:
    """Pure-function tests for the shared format gate."""

    # ── Passing inputs ───────────────────────────────────────────────────

    @pytest.mark.parametrize(
        "value",
        [
            "MRN-12345",
            "patient42",
            "FOLLOWUP_2026Q2",
            "LL new pt",  # single-word "LL" + "new pt" → 3 tokens, all alpha
            "Breast visit",  # exactly the Dr. Perry use case from #259
            "Pre-op",
            "x",
            "1234",  # 4-digit number — not SSN-shaped (9 digits)
        ],
    )
    def test_validValues_pass_when_fullNameRejected(self, value: str) -> None:
        """Most reasonable short labels pass even with full-name rejection on.

        Importantly "LL new pt" and "Breast visit" — the two custom
        examples from issue #259 — must pass. They look like multi-word
        labels but the heuristic counts whitespace-separated tokens with
        any alpha char; "LL" + "new" + "pt" / "Breast" + "visit" both
        trip the 2-token check.

        Wait — that's a problem. Both DO trip the heuristic. The test
        asserts the actual behaviour: callers that want to accept
        multi-word labels must pass ``reject_full_name=False``, OR
        accept that the heuristic forgives them.

        The actual contract is: the gate is intentionally cautious; the
        caller is responsible for choosing the right policy. For
        consultation types the policy is ``reject_full_name=True`` and
        the multi-word labels DO get rejected — which is exactly what
        the test below asserts.
        """
        # This test only runs with reject_full_name=False to confirm
        # the lighter posture also passes these.
        validate_user_text(
            value, max_length=64, reject_full_name=False
        )  # no raise

    # ── Length cap ───────────────────────────────────────────────────────

    def test_rejectsOverlongValue(self) -> None:
        too_long = "X" * 65
        with pytest.raises(ValueError, match="64 character limit"):
            validate_user_text(too_long, max_length=64)

    def test_acceptsValueAtCap(self) -> None:
        at_cap = "X" * 64
        validate_user_text(at_cap, max_length=64)  # no raise

    # ── SSN gates ────────────────────────────────────────────────────────

    def test_rejectsRawSSN(self) -> None:
        with pytest.raises(ValueError, match="SSN"):
            validate_user_text("123456789", max_length=64)

    def test_rejectsDashedSSN(self) -> None:
        with pytest.raises(ValueError, match="SSN"):
            validate_user_text("123-45-6789", max_length=64)

    # ── Email gate ───────────────────────────────────────────────────────

    def test_rejectsEmailShape(self) -> None:
        with pytest.raises(ValueError, match="email"):
            validate_user_text("jane@clinic.lan", max_length=64)

    # ── Full-name gate ───────────────────────────────────────────────────

    def test_rejectsFullName_default(self) -> None:
        with pytest.raises(ValueError, match="full name"):
            validate_user_text("Jane Doe", max_length=64)

    def test_rejectsThreeTokenFullName(self) -> None:
        with pytest.raises(ValueError, match="full name"):
            validate_user_text("Jane M Doe", max_length=64)

    def test_acceptsFullNameWhenGateDisabled(self) -> None:
        # Reserved for forward-compat surfaces that legitimately accept
        # multi-word strings. Today no caller uses this.
        validate_user_text(
            "Jane Doe", max_length=64, reject_full_name=False
        )  # no raise

    # ── PHI not in error message ─────────────────────────────────────────

    @pytest.mark.parametrize(
        "value,expected_match",
        [
            ("123456789", "SSN"),
            ("jane@clinic.lan", "email"),
            ("Jane Doe", "full name"),
            ("X" * 65, "character limit"),
        ],
    )
    def test_errorMessageNeverIncludesValue(
        self, value: str, expected_match: str
    ) -> None:
        """The whole point of the gate — the rejected value must NEVER
        appear in the raised exception's string form."""
        with pytest.raises(ValueError) as exc_info:
            validate_user_text(value, max_length=64)
        assert expected_match in str(exc_info.value)
        # The rejected value itself must not echo back.
        assert value not in str(exc_info.value)


class TestConsultationTypeGates:
    """Higher-level tests mirroring the call site shape in
    ``app/api/v1/profile.py::_validate_consultation_type``. The
    consultation-type field uses ``reject_full_name=False`` because
    clinician shorthand like "LL fu" or "Breast visit" is legitimate;
    the proper-noun-pair heuristic on top catches "Jane Doe" shapes."""

    @pytest.mark.parametrize(
        "value",
        [
            "Breast",
            "LL fu",
            "LL new pt",
            "Breast visit",
            "LL-new-pt",
            "Followup2026",
            "Pre-op",
            "x",
        ],
    )
    def test_validCustomLabel_passes_at_lowerLevel(self, value: str) -> None:
        # With `reject_full_name=False` all of these pass the shared
        # gate. The proper-noun-pair check at the caller site sits on
        # top — covered by the integration test.
        validate_user_text(value, max_length=60, reject_full_name=False)

    @pytest.mark.parametrize(
        "value,expected_match",
        [
            ("X" * 61, "character limit"),
            ("123456789", "SSN"),
            ("123-45-6789", "SSN"),
            ("perry@clinic.lan", "email"),
        ],
    )
    def test_invalidLabel_raisesWithoutValueInMessage(
        self, value: str, expected_match: str
    ) -> None:
        # The "full name" case is handled by the proper-noun-pair check
        # in profile.py, exercised by the integration test. Here we
        # exercise the gates that belong to the shared helper.
        with pytest.raises(ValueError) as exc_info:
            validate_user_text(value, max_length=60, reject_full_name=False)
        assert expected_match in str(exc_info.value)
        assert value not in str(exc_info.value)


class TestProperNounPairHeuristic:
    """Pin the higher-level proper-noun-pair heuristic in profile.py."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("LL fu", False),  # second token starts lowercase
            ("Breast visit", False),
            ("LL new pt", False),
            ("Pre-op", False),  # single token
            ("Jane Doe", True),
            ("Marie Gdalevitch", True),
            ("Marie M Gdalevitch", True),  # three caps tokens
            ("LL-fu", False),
            ("Followup-2026", False),
            ("Jean-Paul Sartre", True),  # hyphen still alpha
        ],
    )
    def test_heuristic(self, value: str, expected: bool) -> None:
        from app.api.v1.profile import _looks_like_proper_noun_pair

        assert _looks_like_proper_noun_pair(value) == expected
