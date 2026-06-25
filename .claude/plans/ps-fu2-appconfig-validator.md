# ps-fu2 — AppConfig validator drift + publish preservation

The portal Feature Flags save (incl. the new Prompt Studio toggle) **502s and
rolls back** — "doesn't stay saved."

## Root cause

`update_feature_flags` publishes a new AWS AppConfig hosted version. The
AppConfig configuration profile has a strict JSON-Schema **validator**
(`infrastructure/appconfig.tf`) with `additionalProperties = false` on the
`feature_flags` block. That validator lists every flag **except**
`prompt_studio_enabled`, `prompt_studio_roles`, and `measurement_enabled`. The
backend always publishes the **full** `FeatureFlagsConfig` dump, so AWS rejects
the create-hosted-version call → backend returns 502 → the page optimistically
flips the toggle then rolls it back.

ps-05 added `prompt_studio_*` to the Pydantic schema and ps-fu added the portal
toggle, but **neither updated the Terraform validator**. `measurement_enabled`
had drifted earlier the same way. Reads work (defaults); only writes are
rejected — and the Feature Flags page had never had a successful prod save, so
the drift was latent.

## Coupled risk (must fix together)

`update_feature_flags` republishes only `providers`, `model_params`, `pipeline`,
`feature_flags` — it **drops** `model_versions` (AI model-id overrides, incl.
the Gemini 3.1 flip #438) and `alerting` (SLA thresholds). Dormant today because
saves *fail*; but the moment the validator accepts the write, a feature-flags
save would **silently reset the Gemini override + alert SLAs**. So the validator
fix and the preservation fix must ship together.

(`measurement` top-level is NOT republished and NOT in the validator root, so it
never appears in the hosted doc — correctly left out.)

## Changes

### Infra — `infrastructure/appconfig.tf`
- Add to the `feature_flags` validator `properties` (NOT `required`, matching the
  existing optional-flag precedent):
  - `measurement_enabled = { type = "boolean" }`
  - `prompt_studio_enabled = { type = "boolean" }`
  - `prompt_studio_roles = { type = "array", items = { type = "string" } }`
- **Needs `terraform apply` to prod** — the validator is Terraform-managed
  (hosted versions are CLI-managed; see the comment block in the file). This is a
  human/ops step (Faical); the bot does not touch prod infra.

### Backend — `app/api/v1/admin/feature_flags.py`
- `update_feature_flags`: republish `alerting` + `model_versions` (the latter with
  `exclude_none=True` so null model ids stay valid under the validator) so a
  feature-flags save preserves operator-set top-level sections. Update the
  docstring.

### Tests — `tests/unit/test_feature_flags_admin.py`
- `test_save_preserves_top_level_sections`: a card-flag save preserves
  `model_versions.gemini` + custom `alerting`.
- `test_appconfig_validator_covers_all_feature_flags`: drift guard — every
  `FeatureFlagsConfig` field must appear in the appconfig.tf `feature_flags`
  validator block (this is the test that would have caught the bug).

## ⚠️ Deploy order (critical)

Deploy the **backend (B) first, then `terraform apply` the validator (A)**.

The currently-live backend already publishes the full `feature_flags` dump but
only 4 top-level sections (no `model_versions`). Today the AWS validator's
rejection of `prompt_studio_enabled` is the *only* thing stopping a
`model_versions`-stripping write. If A is applied while the old (B-less) backend
is still live, the next Feature Flags save succeeds and **resets the Gemini 3.1
override (#438) + alert SLAs**. Backend-first is safe: saves keep 502'ing until A
lands, but nothing resets. (Merge→app-deploy is automatic; `terraform apply` is
manual — so the natural flow is safe as long as the apply waits for the deploy.)

## Verify
- `ruff` + `pytest tests/unit/test_feature_flags_admin.py`.
- `terraform fmt -check` / `validate` on appconfig.tf if available.
- `/simplify` → `/code-review` → PR. Flag the `terraform apply` as the human step.
