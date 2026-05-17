"""M-05: consent method validation on `/sessions/{id}/consent`."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.api.v1.sessions import ConfirmConsentRequest


class TestConsentMethod:
    @pytest.mark.parametrize("method", ["verbal", "paper_form", "digital_form"])
    def test_accepts_allowed_methods(self, method: str):
        req = ConfirmConsentRequest(consent_method=method)
        assert req.consent_method == method

    @pytest.mark.parametrize("method", ["", "spoken", "implied", "unknown"])
    def test_rejects_unknown_methods(self, method: str):
        with pytest.raises(ValidationError):
            ConfirmConsentRequest(consent_method=method)

    def test_method_is_required(self):
        with pytest.raises(ValidationError):
            ConfirmConsentRequest()
