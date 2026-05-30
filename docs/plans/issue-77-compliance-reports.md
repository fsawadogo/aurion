# Plan for #77 — Automated compliance reporting (foundation)

## Task
**#77** — Persisted, hash-signed compliance report snapshots so the clinic can hand an institution a verifiable "here's everything from this window". Foundation ships **on-demand audit reports** (one report type, manual trigger, sha256-signed). Scheduling (cron + alert channel from #76), the masking-proof and retention report types, and HSM-backed signing land as follow-ups.

## Why
CLAUDE.md §"Pilot-specific guardrails" plus Law 25 obligations require traceable, exportable proof of: who accessed what, when masking was confirmed, and when raw data was purged. The existing `GET /admin/audit/export` returns CSV but the bytes aren't archived — re-running the export against a moving window doesn't produce the same file. #77 introduces persisted snapshots with a content hash so the report a compliance officer sent to the clinic two months ago can be re-fetched byte-identical.

## Approach
- **Model + migration** (`ComplianceReportModel`, migration 0010): id, `report_type` ("audit" | "masking" | "retention"), since/until, generated_at, generated_by, `content_bytes` (CSV stored inline — fine at pilot scale; S3-backed = follow-up when sizes grow), `sha256` (hex of content), `byte_size`.
- **Service** (`app/modules/compliance/reports_service.py`):
  - `generate(report_type, since, until, generated_by)` → builds the CSV, computes sha256, persists, returns the row.
  - `list(...)` / `get(...)` for the admin endpoints.
  - Audit CSV builder is composed from the existing `scan_audit_events + apply_audit_filters` so reports stay byte-aligned with the manual `/audit/export`.
- **Endpoints** (`app/api/v1/admin/compliance.py`):
  - `POST /admin/compliance/reports` — body `{report_type, since, until}`; triggers generation, returns metadata.
  - `GET /admin/compliance/reports` — paginated list.
  - `GET /admin/compliance/reports/{id}` — metadata detail.
  - `GET /admin/compliance/reports/{id}/download` — streams the persisted CSV bytes with sha256 echoed in `X-Aurion-Sha256` header.
  - ADMIN + COMPLIANCE_OFFICER gated. POST also emits an audit event (`AUDIT_EXPORTED` if it exists, else `TEMPLATE_CHANGED`-style sentinel).
- **Tests**: AsyncMock unit tests covering generate (writes row, computes sha256), list/get, and the audit-CSV byte composition.

## Acceptance criteria
- [ ] **AC-1**: Migration `0010` creates `compliance_reports` table.
- [ ] **AC-2**: `pytest …::TestGenerate::test_generate_persists_and_signs` — row written, sha256 matches `hashlib.sha256(content).hexdigest()`.
- [ ] **AC-3**: `POST /admin/compliance/reports` (admin, body `{"report_type":"audit"}`) → 200 with the new report metadata.
- [ ] **AC-4**: `GET /admin/compliance/reports/{id}/download` → 200, `Content-Type: text/csv`, body identical to the row's `content_bytes`, sha256 in `X-Aurion-Sha256` header.
- [ ] **AC-5**: Non-`ADMIN`/`COMPLIANCE_OFFICER` → 403.
- [ ] **AC-6**: Backend suite stays green (309 → ~314 passing).

## DRY / SOLID check
- **Reused**: `scan_audit_events`, `apply_audit_filters` from `app/api/v1/admin/_shared.py`, the audit-log service, admin-router aggregator, AsyncMock test helper, `require_role`.
- **New?** `ComplianceReportsService` is a new vertical; mirrors `AlertService` / `ProviderUsageService`. Not a duplicate.
- **OCP**: report-type dispatcher inside the service; adding `masking` / `retention` types is one new builder function, no router/model change.

## Out of scope (follow-ups)
- **Scheduling**: cron (or CloudWatch Events / EventBridge) firing the generate path, then notifying via the alerts surface from #76.
- **Masking** + **retention** report types — same scaffolding, different CSV builders.
- **S3-backed content**: when report bytes exceed PG row limits or when audit volume grows past pilot scale.
- **HSM / X.509 signing**: foundation uses sha256 hex; cryptographic signing with a clinic key + RFC 3161 timestamping comes when the institution requires it.
- **Web Portal Compliance Reports page**: list / generate / download UI.

## Test plan
1. `cd backend && python3 -m pytest tests/unit/test_compliance_reports.py -v` → all pass
2. `docker-compose exec aurion-api alembic upgrade head` → 0009 → 0010
3. `curl -X POST -H "Authorization: Bearer <admin>" localhost:8080/api/v1/admin/compliance/reports -d '{"report_type":"audit"}'` → 200 + report metadata
4. `curl -H "Authorization: Bearer <admin>" localhost:8080/api/v1/admin/compliance/reports/<id>/download -o report.csv` → CSV bytes; verify `shasum -a 256 report.csv` matches the metadata
5. `cd backend && python3 -m pytest -q` → 309 → ~314

## Security implications
- **No PHI in the row metadata**: report_type / since / until / hash / byte_size. The `content_bytes` *can* carry PHI if the audit event metadata does, but the audit log itself was already scoped no-PHI in CLAUDE.md §"Non-Negotiable Technical Rules". Treat the content as the same trust level as audit_log itself.
- **Append-only**: the model is INSERT-only for the foundation; no UPDATE/DELETE endpoint. Future deletion (retention) would itself be auditable.
- **Hash echoed in download response**: lets the compliance officer verify the bytes on the wire match what was persisted.
- **Role-gated**: ADMIN + COMPLIANCE_OFFICER only.
