# Visit type → template mapping (two-tier: org default + clinician override)

**Goal.** When a clinician picks a visit type ("note visit") on iOS, the right
template is already applied — no per-encounter template picking. The mapping is
authored in the web portal (a new **Visit Types** tab on the Templates page) and
resolves **server-side**, so iOS needs no release.

**Decisions (from Uzziel).**
- **Flat match** — one template per visit type (not per-context). The richer
  per-context pin stays available but is not required.
- **Two-tier** — an **admin org default** per visit type, which a **clinician can
  override** for themselves.
- **UI** — a "Visit Types" tab on the Templates page (PR2).

## How it resolves (server-side, `resolve_context_template_key`)

Precedence at session create (consultation_type known). First hit wins:

1. **Context pin** — the picked context pins a `template_key`/`template_ref` *(exists today)*
2. **Clinician visit-type default** — the visit type's `is_default` context's template *(exists today, #577)*
3. **Org visit-type default** — the admin-set org map *(NEW)*
4. **Specialty default** — `get_template(specialty)` floor *(exists today)*

iOS already sends `consultation_type` + `context_id`, so the whole ladder resolves
server-side. Web "Upload Video" is unaffected (it's a direct template pick, no visit type).

Back-compat: with no org row, step 3 is a no-op and behaviour is byte-identical to today.

## PR1 — backend (this PR)

The only genuinely-new layer is the **org default** (steps 1–2 already exist).

1. **Model** `OrgVisitTypeTemplateModel` (`core/models.py`), table
   `org_visit_type_templates`: `visit_type` (PK, str), `template_key` (str|null),
   `custom_template_id` (uuid|null), `updated_by` (uuid), `updated_at`. One row per
   visit type; single-org (no `org_id` for the pilot). `template_key` XOR
   `custom_template_id` enforced at the API layer.
2. **Migration** `0047` (down_revision `0046`) — create the table.
3. **Repo** `modules/note_gen/org_visit_type_templates.py` — `list_org_defaults`,
   `get_org_default`, `upsert_org_default`, `delete_org_default` (mirrors
   `template_overrides`).
4. **Resolver** (`modules/session/service.py`) — extract today's body into
   `_resolve_clinician_context_template(...)`; `resolve_context_template_key` returns
   the clinician result when it yields a template, else consults
   `_resolve_org_default_template(db, consultation_type)`, else `(None, None, coerced)`.
   Org built-in `template_key` re-validated against `list_available_templates`; org
   `custom_template_id` re-validated via `custom_templates.get_shared` (must still be a
   shared/Library template) — stale/private → coerced to specialty default.
5. **Admin API** `api/v1/admin/visit_type_templates.py` — `GET /admin/visit-type-templates`
   (list), `PUT /admin/visit-type-templates/{visit_type}` (upsert),
   `DELETE /admin/visit-type-templates/{visit_type}` (clear). Gated
   `require_role(ADMIN, COMPLIANCE_OFFICER, CLINICAL_ADMIN)` (same set as system
   templates, #578). Validates `template_key` ∈ built-ins **XOR** `custom_template_id`
   is an existing **shared** template. Audit on write. Registered in `admin/__init__.py`.

### Acceptance criteria
- Org default set + clinician has none → org template resolves.
- Clinician default set → clinician wins over org.
- Neither → specialty default `(None, None)` (unchanged).
- Org `custom_template_id` that is private/deleted → rejected at PUT; if it goes stale
  later → resolver coerces to specialty default (never errors session create).
- Admin endpoints 403 for a plain clinician.
- Full existing session/context/profile suites stay green (back-compat).

### Security
- Org map writes are admin-gated. Org custom-template refs must be **shared** (org-usable),
  never a private clinician template → no cross-tenant template leak.
- Resolver never raises; every "can't resolve" path degrades to specialty default.

## Out of scope (PR2 / later)
- **PR2 (web):** the "Visit Types" tab — per visit type a template selector; admins also
  set the org default; clinicians see "inheriting org default: X" until they override.
- Org-defined visit types (a fixed org list). Today visit types are per-clinician; the org
  map keys off the visit-type key, so custom clinician visit types simply have no org default.
- A visit-type picker on web "Upload Video".
