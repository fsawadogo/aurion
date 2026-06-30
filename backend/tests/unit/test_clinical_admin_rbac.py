"""Unit tests for the CLINICAL_ADMIN role (#578).

CLINICAL_ADMIN is an elevatable super-user: it joins the role sets on the
template Library + Prompt Studio curation surfaces, but is deliberately ABSENT
from infra/security/regulatory gates (Feature Flags, AI Providers, Config,
Users, PHI, Audit). `require_role` is an OR-set with no hierarchy, so "absent
from the set" == 403 — that's the AC's negative requirement, exercised here via
the ADMIN-only / ADMIN+COMPLIANCE gates the infra endpoints use.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.v1.admin import shared_templates, templates
from app.core.types import UserRole
from app.modules.auth.service import _resolve_role_from_groups, require_role
from app.modules.config.schema import FeatureFlagsConfig


def test_enum_has_clinical_admin() -> None:
    assert UserRole.CLINICAL_ADMIN.value == "CLINICAL_ADMIN"


# ── Elevatable surfaces include CLINICAL_ADMIN ───────────────────────────────


def test_system_templates_gate_includes_clinical_admin() -> None:
    assert UserRole.CLINICAL_ADMIN in templates._ROLES
    assert UserRole.ADMIN in templates._ROLES
    assert UserRole.COMPLIANCE_OFFICER in templates._ROLES


def test_shared_templates_gate_includes_clinical_admin() -> None:
    assert UserRole.CLINICAL_ADMIN in shared_templates._ROLES
    assert UserRole.ADMIN in shared_templates._ROLES


def test_prompt_studio_default_roles_include_clinical_admin() -> None:
    flags = FeatureFlagsConfig()
    assert "CLINICAL_ADMIN" in flags.prompt_studio_roles
    assert "ADMIN" in flags.prompt_studio_roles


# ── require_role mechanism: allow when listed, 403 when not ──────────────────


@pytest.mark.asyncio
async def test_require_role_allows_clinical_admin_when_listed() -> None:
    dep = require_role(UserRole.ADMIN, UserRole.CLINICAL_ADMIN)
    user = SimpleNamespace(role=UserRole.CLINICAL_ADMIN)
    assert await dep(user=user) is user


@pytest.mark.asyncio
async def test_require_role_denies_clinical_admin_on_admin_only_gate() -> None:
    # Infra/security endpoints (Feature Flags, Users) gate on ADMIN only; a
    # CLINICAL_ADMIN must be 403'd there.
    dep = require_role(UserRole.ADMIN)
    user = SimpleNamespace(role=UserRole.CLINICAL_ADMIN)
    with pytest.raises(HTTPException) as exc:
        await dep(user=user)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_role_denies_clinical_admin_on_admin_compliance_gate() -> None:
    # AI Providers / Config / Audit gate on ADMIN + COMPLIANCE_OFFICER — still
    # no CLINICAL_ADMIN.
    dep = require_role(UserRole.ADMIN, UserRole.COMPLIANCE_OFFICER)
    user = SimpleNamespace(role=UserRole.CLINICAL_ADMIN)
    with pytest.raises(HTTPException) as exc:
        await dep(user=user)
    assert exc.value.status_code == 403


def test_existing_roles_unaffected_on_elevatable_gate() -> None:
    # CLINICIAN is still denied the curation surfaces (only the named admin
    # roles are granted).
    assert UserRole.CLINICIAN not in templates._ROLES
    assert UserRole.CLINICIAN not in shared_templates._ROLES


# ── Cognito group → role mapping ─────────────────────────────────────────────


def test_cognito_group_maps_to_clinical_admin() -> None:
    assert _resolve_role_from_groups(["CLINICAL_ADMIN"]) is UserRole.CLINICAL_ADMIN
    assert _resolve_role_from_groups(["clinical_admins"]) is UserRole.CLINICAL_ADMIN


def test_admin_group_outranks_clinical_admin() -> None:
    assert _resolve_role_from_groups(["ADMIN", "CLINICAL_ADMIN"]) is UserRole.ADMIN


def test_clinical_admin_outranks_compliance() -> None:
    assert (
        _resolve_role_from_groups(["CLINICAL_ADMIN", "COMPLIANCE_OFFICER"])
        is UserRole.CLINICAL_ADMIN
    )
