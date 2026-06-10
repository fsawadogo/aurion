## Task
#76-thresholds — Alert-detector thresholds runtime-configurable via AppConfig

## Why
Issue #76 scope line: "Configurable thresholds". CLAUDE.md: "No hardcoded
config values. Everything through AppConfig" — the #408 detectors shipped
with env-var thresholds (deploy-coupled); AppConfig makes them changeable
in < 30 s with no redeploy, matching every other pipeline tunable.

## Approach
- `backend/app/modules/config/schema.py`: new `AlertingConfig`
  (`sla_stage1_ms` default 30000, `sla_stage2_ms` default 300000,
  `purge_gap_hours` default 24 — Field bounds mirror the detector clamps)
  + `alerting: AlertingConfig = Field(default_factory=AlertingConfig)` on
  `AppConfigSchema`. Old hosted content (no `alerting` key) parses to
  defaults — byte-identical behavior, no content push required.
- `backend/app/modules/alerts/detectors.py`: thresholds resolve
  **env override > AppConfig > schema default** via one `_threshold()`
  resolver (replaces the three copies of the env-read — DRY extract at
  third occurrence). Env stays the ops escape hatch.
- `infrastructure/appconfig.tf`: validator gains an OPTIONAL `alerting`
  properties block (root `required` unchanged; `additionalProperties =
  false` inside the block). `terraform apply` to dev (authorized) so
  future content updates carrying the block validate.

## Acceptance criteria
- [ ] AC-1: config WITHOUT `alerting` parses → defaults 30000/300000/24,
      verified by `pytest tests/unit/test_config_schema.py -k alerting`
- [ ] AC-2: config WITH an `alerting` block overrides values; out-of-range
      values fail validation, verified by the same test module
- [ ] AC-3: detectors use AppConfig values when env unset AND env var wins
      when set, verified by `pytest tests/unit/test_alert_detectors.py`
- [ ] AC-4: `terraform fmt -check` + `terraform validate` pass with the
      validator change
- [ ] AC-5: full backend unit suite green (`python3 -m pytest tests/unit -q`)

## DRY / SOLID check
- **Existing helpers to reuse**: `get_config()` (appconfig_client),
  `PipelineConfig` Field-bounds pattern, detectors' `_env_int`,
  `write_audit` untouched (CONFIG_CHANGED already covers AppConfig edits).
- **New helper introduced?**: yes — `_threshold()` in detectors, and it IS
  the extraction of a third copy (three env-read call sites collapse into
  one resolver). `AlertingConfig` extends the schema via a new section
  (OCP), not branches.
- **iOS UI tasks only — `mobile-ios-design` consulted**: n/a (backend +
  infra only).

## Out of scope
- Pushing new AppConfig hosted content (defaults preserve today's
  behavior; content is CLI-managed per memory — SigV4 em-dash gotcha).
- Email sink (blocked on SES, #399) and Slack-secret provisioning (ops).
- Moving `AURION_ALERT_DETECTORS_ENABLED` / the poll interval into
  AppConfig — operational kill-switches stay env, mirroring the EMR
  worker and report scheduler.

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_config_schema.py tests/unit/test_alert_detectors.py -q`
2. `cd backend && python3 -m pytest tests/unit -q`
3. `cd infrastructure && terraform fmt -check && terraform validate`
4. `terraform plan -var-file=environments/dev.tfvars` → validator-only diff; apply (dev-authorized)
5. `curl -fs https://api-dev.aurionclinical.com/health` → 200 after the post-merge deploy

## Security implications
None new. Thresholds are non-PHI tuning values; AppConfig changes are
already audited (CONFIG_CHANGED); the detectors remain read-only scans +
alert-row inserts. No AI prompts, consent gate, masking path, or audit-log
write path touched.
