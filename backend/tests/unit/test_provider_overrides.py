"""Tests for the global runtime AI-provider override layer.

Covers:
- Registry precedence: per-call override > DB override store > AppConfig.
- ``get_override`` returns None when unset.
- ``set_cached`` / ``clear_cached`` cache behavior.
- Admin endpoint validation (bad provider_type / bad value → 400).
- Admin endpoint role gate (CLINICIAN → 403; ADMIN / COMPLIANCE_OFFICER
  can set + clear) and the audit write on set/clear.

These exercise the endpoint coroutines directly with a mocked async
session + a ``CurrentUser`` (mirroring ``test_metrics_timeseries.py``),
so no TestClient / Cognito setup is needed.
"""

from __future__ import annotations

import inspect
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.modules.config import provider_overrides as store
from app.modules.config.provider_registry import ProviderRegistry
from app.modules.config.schema import AppConfigSchema
from app.modules.providers.note_gen.anthropic import AnthropicNoteGenerationProvider
from app.modules.providers.note_gen.openai import OpenAINoteGenerationProvider
from app.modules.providers.transcription.assemblyai import (
    AssemblyAITranscriptionProvider,
)
from app.modules.providers.transcription.whisper import WhisperTranscriptionProvider
from app.modules.providers.vision.anthropic import AnthropicVisionProvider
from app.modules.providers.vision.openai import OpenAIVisionProvider


def _mock_config(**overrides) -> AppConfigSchema:
    providers = {
        "transcription": "whisper",
        "note_generation": "anthropic",
        "vision": "openai",
    }
    providers.update(overrides)
    return AppConfigSchema.model_validate({"providers": providers})


@pytest.fixture(autouse=True)
def _clean_cache():
    """Each test starts and ends with an empty override cache so global
    module state doesn't leak between tests."""
    store._cache.clear()
    yield
    store._cache.clear()


# ── Store cache behavior ────────────────────────────────────────────────────


class TestStoreCache:
    def test_get_override_none_when_unset(self) -> None:
        assert store.get_override("transcription") is None
        assert store.get_override("note_generation") is None
        assert store.get_override("vision") is None

    def test_set_cached_then_get(self) -> None:
        store.set_cached("transcription", "assemblyai")
        assert store.get_override("transcription") == "assemblyai"
        # Other types unaffected.
        assert store.get_override("vision") is None

    def test_clear_cached_removes_entry(self) -> None:
        store.set_cached("vision", "anthropic")
        assert store.get_override("vision") == "anthropic"
        store.clear_cached("vision")
        assert store.get_override("vision") is None

    def test_clear_cached_missing_is_noop(self) -> None:
        # No KeyError when clearing an absent entry.
        store.clear_cached("note_generation")
        assert store.get_override("note_generation") is None


# ── Registry precedence ─────────────────────────────────────────────────────


class TestRegistryPrecedence:
    def test_appconfig_used_when_no_override(self) -> None:
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(),
        ):
            provider = registry.get_transcription_provider()
        assert isinstance(provider, WhisperTranscriptionProvider)

    def test_store_override_beats_appconfig(self) -> None:
        registry = ProviderRegistry()
        store.set_cached("transcription", "assemblyai")
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(),  # appconfig says whisper
        ):
            provider = registry.get_transcription_provider()
        assert isinstance(provider, AssemblyAITranscriptionProvider)

    def test_per_call_override_beats_store(self) -> None:
        registry = ProviderRegistry()
        # Store says assemblyai, AppConfig says whisper, but per-call wins.
        store.set_cached("transcription", "assemblyai")
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(),
        ):
            provider = registry.get_transcription_provider(override="whisper")
        assert isinstance(provider, WhisperTranscriptionProvider)

    def test_note_store_override_beats_appconfig(self) -> None:
        registry = ProviderRegistry()
        store.set_cached("note_generation", "openai")
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(),  # appconfig says anthropic
        ):
            provider = registry.get_note_provider()
        assert isinstance(provider, OpenAINoteGenerationProvider)

    def test_vision_store_override_beats_appconfig(self) -> None:
        registry = ProviderRegistry()
        store.set_cached("vision", "anthropic")
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(),  # appconfig says openai
        ):
            provider = registry.get_vision_provider()
        assert isinstance(provider, AnthropicVisionProvider)

    def test_fallback_primary_respects_store_override(self) -> None:
        registry = ProviderRegistry()
        store.set_cached("note_generation", "openai")
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(),  # appconfig says anthropic
        ):
            provider = registry.get_note_provider_with_fallback()
        assert isinstance(provider, OpenAINoteGenerationProvider)

    def test_fallback_uses_appconfig_when_no_store(self) -> None:
        registry = ProviderRegistry()
        with patch(
            "app.modules.config.provider_registry.get_config",
            return_value=_mock_config(),
        ):
            provider = registry.get_note_provider_with_fallback()
        assert isinstance(provider, AnthropicNoteGenerationProvider)


# ── Admin endpoint: validation ──────────────────────────────────────────────


def _admin_user() -> MagicMock:
    from app.core.types import UserRole

    return MagicMock(role=UserRole.ADMIN, user_id=uuid.uuid4(), email="admin@aurion.local")


class TestEndpointValidation:
    @pytest.mark.asyncio
    async def test_invalid_provider_type_rejected(self) -> None:
        from fastapi import HTTPException

        from app.api.v1.admin.config import (
            SetProviderOverrideRequest,
            set_provider_override,
        )

        db = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await set_provider_override(
                provider_type="not_a_provider",
                body=SetProviderOverrideRequest(value="whisper"),
                user=_admin_user(),
                db=db,
            )
        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_invalid_value_rejected(self) -> None:
        from fastapi import HTTPException

        from app.api.v1.admin.config import (
            SetProviderOverrideRequest,
            set_provider_override,
        )

        db = MagicMock()
        with pytest.raises(HTTPException) as exc:
            await set_provider_override(
                provider_type="transcription",
                body=SetProviderOverrideRequest(value="openai"),  # not a transcription key
                user=_admin_user(),
                db=db,
            )
        assert exc.value.status_code == 400


# ── Admin endpoint: behavior + audit ────────────────────────────────────────


class TestEndpointBehavior:
    @pytest.mark.asyncio
    async def test_set_inserts_row_caches_and_audits(self) -> None:
        from app.api.v1.admin.config import (
            SetProviderOverrideRequest,
            set_provider_override,
        )
        from app.core.audit_events import AuditEventType

        db = MagicMock()
        db.get = AsyncMock(return_value=None)  # no existing row → insert
        db.add = MagicMock()
        db.flush = AsyncMock()
        user = _admin_user()

        with (
            patch(
                "app.api.v1.admin.config.get_config", return_value=_mock_config()
            ),
            patch(
                "app.api.v1.admin.config.write_audit", new=AsyncMock()
            ) as audit_mock,
        ):
            resp = await set_provider_override(
                provider_type="transcription",
                body=SetProviderOverrideRequest(value="assemblyai", reason="vendor outage"),
                user=user,
                db=db,
            )

        # Row inserted.
        assert db.add.called
        added = db.add.call_args[0][0]
        assert added.provider_type == "transcription"
        assert added.provider_value == "assemblyai"
        assert added.set_by == user.user_id
        assert added.reason == "vendor outage"

        # Cache updated immediately.
        assert store.get_override("transcription") == "assemblyai"

        # Effective value reflects the override.
        by_type = {p.provider_type: p for p in resp.providers}
        assert by_type["transcription"].override_value == "assemblyai"
        assert by_type["transcription"].appconfig_value == "whisper"
        assert by_type["transcription"].effective_value == "assemblyai"

        # Audit event written with the right type + fields.
        audit_mock.assert_awaited_once()
        args, kwargs = audit_mock.await_args
        assert args[0] == "system"  # non-session sentinel
        assert args[1] == AuditEventType.PROVIDER_OVERRIDE_SET
        assert kwargs["provider_type"] == "transcription"
        assert kwargs["new_provider"] == "assemblyai"
        assert kwargs["changed_by"] == str(user.user_id)

    @pytest.mark.asyncio
    async def test_set_updates_existing_row(self) -> None:
        from app.api.v1.admin.config import (
            SetProviderOverrideRequest,
            set_provider_override,
        )
        from app.core.models import ProviderOverrideModel

        existing = ProviderOverrideModel(
            provider_type="vision",
            provider_value="openai",
            set_by=uuid.uuid4(),
            reason="old",
        )
        db = MagicMock()
        db.get = AsyncMock(return_value=existing)
        db.add = MagicMock()
        db.flush = AsyncMock()
        user = _admin_user()

        with (
            patch("app.api.v1.admin.config.get_config", return_value=_mock_config()),
            patch("app.api.v1.admin.config.write_audit", new=AsyncMock()),
        ):
            await set_provider_override(
                provider_type="vision",
                body=SetProviderOverrideRequest(value="anthropic", reason="new"),
                user=user,
                db=db,
            )

        # Updated in place, not re-added.
        assert not db.add.called
        assert existing.provider_value == "anthropic"
        assert existing.set_by == user.user_id
        assert existing.reason == "new"
        assert store.get_override("vision") == "anthropic"

    @pytest.mark.asyncio
    async def test_clear_deletes_row_clears_cache_and_audits(self) -> None:
        from app.api.v1.admin.config import clear_provider_override
        from app.core.audit_events import AuditEventType
        from app.core.models import ProviderOverrideModel

        existing = ProviderOverrideModel(
            provider_type="note_generation",
            provider_value="openai",
            set_by=uuid.uuid4(),
            reason="x",
        )
        store.set_cached("note_generation", "openai")

        db = MagicMock()
        db.get = AsyncMock(return_value=existing)
        db.delete = AsyncMock()
        db.flush = AsyncMock()
        user = _admin_user()

        with (
            patch("app.api.v1.admin.config.get_config", return_value=_mock_config()),
            patch("app.api.v1.admin.config.write_audit", new=AsyncMock()) as audit_mock,
        ):
            resp = await clear_provider_override(
                provider_type="note_generation",
                user=user,
                db=db,
            )

        db.delete.assert_awaited_once_with(existing)
        assert store.get_override("note_generation") is None

        by_type = {p.provider_type: p for p in resp.providers}
        assert by_type["note_generation"].override_value is None
        assert by_type["note_generation"].effective_value == "anthropic"

        audit_mock.assert_awaited_once()
        args, kwargs = audit_mock.await_args
        assert args[1] == AuditEventType.PROVIDER_OVERRIDE_CLEARED
        assert kwargs["old_provider"] == "openai"
        assert kwargs["provider_type"] == "note_generation"


# ── Admin endpoint: role gate ───────────────────────────────────────────────


class TestRoleGate:
    def test_endpoints_guarded_by_require_role(self) -> None:
        """All three endpoints carry a Depends-wrapped require_role on
        their ``user`` parameter."""
        from app.api.v1.admin.config import (
            clear_provider_override,
            get_providers,
            set_provider_override,
        )

        for fn in (get_providers, set_provider_override, clear_provider_override):
            sig = inspect.signature(fn)
            user_param = sig.parameters["user"]
            assert user_param.default is not None
            assert user_param.default.dependency.__qualname__.startswith(
                "require_role"
            ), f"{fn.__name__} is missing the require_role gate"

    @pytest.mark.asyncio
    async def test_clinician_denied(self) -> None:
        """A CLINICIAN hitting the role checker gets 403."""
        from fastapi import HTTPException

        from app.core.types import UserRole
        from app.modules.auth.service import CurrentUser, require_role

        checker = require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
        clinician = CurrentUser(
            user_id=uuid.uuid4(), role=UserRole.CLINICIAN, email="doc@aurion.local"
        )
        with pytest.raises(HTTPException) as exc:
            await checker(user=clinician)
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    async def test_admin_and_compliance_allowed(self) -> None:
        from app.core.types import UserRole
        from app.modules.auth.service import CurrentUser, require_role

        checker = require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
        for role in (UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER):
            u = CurrentUser(user_id=uuid.uuid4(), role=role, email="x@aurion.local")
            returned = await checker(user=u)
            assert returned is u


# ── Audit events present ─────────────────────────────────────────────────────


def test_override_audit_events_have_whitelist_entries() -> None:
    from app.core.audit_events import ALLOWED_AUDIT_KWARGS, AuditEventType

    for ev in (
        AuditEventType.PROVIDER_OVERRIDE_SET,
        AuditEventType.PROVIDER_OVERRIDE_CLEARED,
    ):
        assert ev in ALLOWED_AUDIT_KWARGS
