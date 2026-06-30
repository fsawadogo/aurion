# Plan — tpl-central-4 (#578): CLINICAL_ADMIN super-user role + elevated curation

## Task
#578 (epic #574), lane-full. Add an elevatable super-user role (Perry, Marie)
that can curate the template Library + publish prompts — but NOT touch
infra/security/regulatory (Feature Flags, AI Providers, Config, Users, PHI,
Audit). Web `UserRole` type + EN label already include `CLINICAL_ADMIN`.

## Backend
- **Migration** (required — `users.role` is a Postgres ENUM `user_role`): new
  Alembic revision `ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'CLINICAL_ADMIN'`,
  mirroring the `session_state` STAGE1_FAILED migration's autocommit pattern.
  Also add `CLINICAL_ADMIN` to the baseline enum value list so a fresh DB
  creates the type complete.
- `app/core/types.py`: add `CLINICAL_ADMIN = "CLINICAL_ADMIN"` to `UserRole`.
- `app/modules/auth/service.py` `_resolve_role_from_groups`: recognize a
  `CLINICAL_ADMIN`/`CLINICAL_ADMINS` Cognito group (legacy path), ranked just
  below ADMIN.
- **Grant on elevatable endpoints ONLY:**
  - `admin/templates.py` `_ROLES`: add `CLINICAL_ADMIN`.
  - `admin/shared_templates.py` `_ROLE` → tuple incl. `CLINICAL_ADMIN`; switch
    its `require_role(_ROLE)` calls to `require_role(*_ROLES)`.
  - Prompt Studio publish: add `CLINICAL_ADMIN` to the default
    `prompt_studio_roles` (AppConfig schema default) so it's curation-capable
    by default (still flag-gated + runtime-overridable).
- **Leave untouched** (verified by recon): feature_flags, providers, config,
  users, audit, compliance. `require_role` is an OR-set with no hierarchy, so
  not adding the role = 403 for those (the AC's negative requirement holds for
  free).
- Role becomes assignable immediately via Users admin (Pydantic validates
  against the enum; no allowlist). No org-default profile endpoints exist →
  nothing to gate there.

## Web (this PR; #579 later consolidates the nav)
- `components/Sidebar.tsx`: add `CLINICAL_ADMIN` to the `roles` of the
  elevatable items — `systemTemplates`, `sharedTemplates`, `promptStudio`.
  Leave infra items (featureFlags, providers, config, users, audit, …) as-is.
- `messages/fr.json`: add the `CLINICAL_ADMIN` role label if missing (EN exists).

## Acceptance criteria
- [ ] AC-1: a CLINICAL_ADMIN can reach System Templates, Shared Templates, Prompt Studio publish (200).
- [ ] AC-2: a CLINICAL_ADMIN is 403 on Feature Flags, AI Providers, Config, Users, PHI/Audit.
- [ ] AC-3: CLINICIAN + ADMIN behavior unchanged.
- [ ] AC-4: role assignable via Users admin; migration adds the enum value.
- [ ] AC-5: backend role-gate tests (allow elevatable, deny infra) + web nav test; full suite + ruff + eslint/tsc green.

## DRY / SOLID
Reuses `require_role` + the existing nav-filter + the existing migration pattern.
New = one enum value + one migration + role-set additions on 3 surfaces + nav.

## Out of scope
- Consolidating System+Shared nav into one Library entry → #579 (stacked on this).
- Any infra/security endpoint role change. Org-default profile admin endpoints (don't exist).

## Test plan
1. Backend: `pytest tests/.../test_*admin*` + new role-gate tests (CLINICAL_ADMIN allowed on templates/shared-templates; denied on feature-flags/users/config). `ruff check`.
2. Web: `vitest` Sidebar nav test (CLINICAL_ADMIN sees curation items, not infra); `eslint` + `tsc`.
3. Migration: apply locally / confirm it's autocommit-safe; baseline enum updated.

## Security implications
- Deliberately scopes elevation to curation only; infra/PHI/users/audit stay
  ADMIN/COMPLIANCE-gated (the core RBAC boundary). The migration only adds an
  enum value (no data change). No secrets.
