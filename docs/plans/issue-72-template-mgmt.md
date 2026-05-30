# Plan for #72 — Template + visual-trigger keyword management (foundation)

## Task
**#72** — Admin CRUD over specialty templates (and their visual-trigger
keywords). Foundation slice ships the **storage + API**; runtime
integration (in-memory cache + poller mirroring `provider_overrides`)
is the next slice. Once that ships, an admin save reflects in the
running pipeline within ~10s without redeploy.

## Why
The 5 MVP templates live as JSON files in `backend/app/modules/note_gen/templates/`. The trigger-classifier reads `visual_trigger_keywords` lists from those same JSONs, but those lists are intentionally empty pre-pilot (CLAUDE.md §"Questions Before You Start" Q4 — "population happens post-pilot"). To populate them — and to edit section guidance without a code change — admins need a runtime CRUD surface. #72 ships that.

## Approach
- **Model + migration**: `TemplateOverrideModel` keyed by `template_key`,
  carrying the full `Template` JSON. Migration `0008_template_overrides`.
- **Service**: `app/modules/note_gen/template_overrides.py` — async
  helpers `list_overrides`, `get_override`, `upsert_override`,
  `delete_override`. Mirrors the `provider_overrides` shape so the next
  PR can drop in a `start_template_override_polling()` cleanly.
- **Endpoint**: `GET /api/v1/admin/templates` (list with merge status),
  `GET /api/v1/admin/templates/{key}` (effective template), `PUT
  /api/v1/admin/templates/{key}` (admin upsert), `DELETE
  /api/v1/admin/templates/{key}` (revert to disk default). ADMIN +
  COMPLIANCE_OFFICER gated.
- **Validation**: PUT body validated against the existing `Template`
  Pydantic schema before persistence — invalid override never lands.
- **Audit**: PUT and DELETE emit `TEMPLATE_CHANGED` audit events (enum
  already exists).
- **Out of scope (next slice)**: runtime integration (cache + poller +
  `load_templates` merge). This PR's PUT writes the override to DB but
  the running app's note-generation still reads disk templates.
  Documented in the deferred-concerns section so reviewers aren't
  surprised.

## Acceptance criteria
- [ ] **AC-1**: migration `0008` creates the `template_overrides` table.
- [ ] **AC-2**: `pytest tests/unit/test_template_overrides.py` — service
      helpers persist/read/delete correctly.
- [ ] **AC-3**: `GET /api/v1/admin/templates` (admin) → 200 with the 5
      MVP templates, `is_override: false` for each.
- [ ] **AC-4**: `PUT /api/v1/admin/templates/musculoskeletal` (admin,
      modified body) → 200; subsequent `GET …/musculoskeletal` shows
      `is_override: true` and the new content; `TEMPLATE_CHANGED` audit
      event written.
- [ ] **AC-5**: `PUT` with invalid Template JSON → 422 (Pydantic
      rejects before persistence).
- [ ] **AC-6**: `DELETE /api/v1/admin/templates/musculoskeletal` (admin)
      → 204; subsequent GET shows `is_override: false`.
- [ ] **AC-7**: All endpoints require ADMIN or COMPLIANCE_OFFICER; other
      roles → 403.
- [ ] **AC-8**: Backend suite stays green (292 → 297+).

## DRY / SOLID check
- **Existing helpers reused**: `Depends(get_db)`, `require_role`,
  `write_audit`, `AuditEventType.TEMPLATE_CHANGED`, the `Template`
  Pydantic model, the admin-router aggregator pattern.
- **New helper introduced?** `template_overrides` module — yes, but
  mirrors `provider_overrides` (a working pattern); not a third copy
  of an existing helper.
- **SRP**: model = persistence, service = CRUD logic, router = HTTP.
- **OCP**: future runtime integration plugs in via the cache pattern
  without touching the CRUD service.
- **DIP**: db injected; service is stateless.

## Out of scope (follow-up issues)
- Runtime integration: in-memory override cache + poller (mirror
  `provider_overrides.start_polling`), `load_templates` merge.
- Web Portal UI: Templates page with diff view and keyword editor.
- Per-section keyword editor (vs. full-template JSON PUT).
- Versioning of overrides (only the current value is kept).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_template_overrides.py -v`
   → all pass
2. `docker-compose exec aurion-api alembic upgrade head` → 0007 → 0008
3. `curl -H "Authorization: Bearer <admin>" localhost:8080/api/v1/admin/templates`
   → list of 5 templates, all `is_override: false`
4. `curl -X PUT -H "Authorization: Bearer <admin>" -d '{...modified template JSON...}'
   localhost:8080/api/v1/admin/templates/musculoskeletal` → 200
5. `curl -X DELETE …/musculoskeletal` → 204
6. `cd backend && python3 -m pytest -q` → 297+ pass, no regressions

## Security implications
- **No PHI in templates**: templates are clinical-documentation
  scaffolds (section names, prompts, keyword lists). No patient data.
- **Audit trail**: every override write/delete emits `TEMPLATE_CHANGED`
  with `updated_by` so compliance can trace authorship.
- **Role-gated**: ADMIN + COMPLIANCE_OFFICER only.
- **Validation**: invalid Template payloads rejected before persistence
  — a malformed JSON can't corrupt the override store.
