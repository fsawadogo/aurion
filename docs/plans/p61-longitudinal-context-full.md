# #61 — Longitudinal Patient Context (Full Slice)

> **Status**: in-flight
> **Branch**: `lane-backend/p61-longitudinal-context-full`
> **Issue**: #61 LONGITUDINAL PATIENT CONTEXT — FULL SLICE
> **Scope**: vertical slice — backend + iOS + web in a single PR
> **Foundation already merged**: PR #164 (encrypted identifier column,
> `PATCH /sessions/{id}/identifier`, `GET /me/patients/{identifier}/sessions`),
> PR #179/#180 (iOS identifier set/clear + inbox row chip), PR #223 (web
> `/portal/patients/[identifier]` detail page), PR #224 (iOS
> `PriorEncountersRail` + `PriorEncountersListView` on `NoteReviewView`).

---

## Problem statement

The LLM does not see prior-encounter context at note-generation time. Each
visit is generated cold. The rail shows the physician their prior visits,
but the model itself never reads them, so the documentation can't reference
prior findings even when the physician did so verbally ("same shoulder pain
since the last visit"). This PR feeds prior context into Stage 1 note-gen
in a way that preserves descriptive mode and per-physician scope.

## What ships in this slice

### Backend

* `backend/app/modules/longitudinal_context/` — new module:
  * `PriorEncounterSummary` dataclass — `(session_id, date, specialty,
    chief_complaint_excerpt, key_claims)`. Assessment text is **deliberately
    excluded** so the model can't echo a prior diagnostic impression as if
    it had reached one itself.
  * `PriorContextBlock` — list + total seen.
  * `async get_prior_context(clinician_id, patient_identifier,
    current_session_id, db, *, limit=3)` — last `limit` non-PURGED
    sessions for this clinician + identifier, excluding the current
    session. Returns `None` if identifier empty (cold-start signal);
    returns a block with `total_seen=0` if identifier set but no prior
    found.
  * `render_prior_context_block(block) -> str` — deterministic text
    block appended to the **user** message (not system) so the system
    prompt's descriptive-mode boundary stays unambiguous.
* New deterministic-hash column on `sessions`:
  * `external_reference_id_hash: bytes | null` (32-byte HMAC-SHA256), indexed.
  * Alembic migration `2026_06_04_0027_session_external_reference_id_hash.py`
    — add column + index + data-migration that hashes existing rows.
  * `backend/app/core/identifier_hash.py::hash_identifier(plaintext) -> bytes`
    — pure function, single source of truth.
  * HMAC key from new Secrets Manager secret
    `aurion/${env}/identifier-hmac-key`. Terraform adds the secret
    resource alongside the existing provider-api-key block.
* Indexed-hash lookup replaces the linear-scan in BOTH consumer sites:
  * `GET /me/patients/{identifier}/sessions` (existing endpoint)
  * `get_prior_context` (new)
* `PATCH /sessions/{id}/identifier` recomputes the hash alongside
  encrypt/IV on every set.
* `generate_stage1_note` integration:
  * Reads current session's identifier (already on `SessionModel`).
  * Calls `get_prior_context(clinician_id, identifier, current_session_id, db)`.
  * If block non-None, appends rendered text to the user message AND
    concatenates a one-sentence reinforcement to the system prompt **at
    call time** ("When prior visits are listed, you may reference them
    factually — only state what the prior note recorded.").
  * The registry base stays untouched so
    `test_descriptive_mode_phrases_locked` keeps passing.
  * After Stage 1 completes, sets
    `note.prior_context_used = {encounters_referenced, last_encounter_date}`
    — counts + date only, **no PHI**.
* `AuditEventType.LONGITUDINAL_CONTEXT_LOADED` — detail keys exactly
  `{actor_id, current_session_id, encounters_count, last_encounter_date}`.
  No identifier value, no clinical content, no prior session IDs.
* `pipeline.longitudinal_context_max_encounters` — integer 1-10,
  default 3. Added to `infrastructure/appconfig.tf` validator +
  content and `backend/app/modules/config/schema.py::PipelineConfig`.

### iOS

* `Note` model gains optional `priorContextUsed: PriorContextUsed?` —
  decodes from `note.prior_context_used`.
* `NoteReviewView` shows a "Context-aware" badge in the header when
  `note.priorContextUsed.encountersReferenced > 0`. Tap navigates to
  the existing `PriorEncountersListView`.
* Strings via `Localizable.strings` (EN + FR).
* `AurionTests/PriorEncountersTests.swift` extended.

### Web

* `web/types/index.ts::Note` gains
  `prior_context_used: { encounters_referenced: number;
  last_encounter_date: string | null } | null`.
* `web/components/portal/NoteContextBadge.tsx` (new) — gold-tinted chip
  "Context: N prior visits" in the note review header when count > 0.
  Clickable → `/portal/patients/{identifier}`.
* `web/app/portal/notes/[id]/NoteReviewClient.tsx` — mount the badge in
  the header alongside `PatientIdentifierEditor`.
* i18n in `web/messages/{en,fr}.json` under new `LongitudinalContext`
  namespace: `badge.contextAware`, `badge.priorVisitsCount`,
  `badge.tapToView`.
* `web/tests/NoteContextBadge.spec.tsx` (new) — render/hide gates,
  navigation, EN/FR parity.

## DRY/SOLID gates (workflow §6c)

* ONE `get_prior_context`. ONE `render_prior_context_block`. ONE
  `hash_identifier`.
* `note_gen` calls into `longitudinal_context`; never the reverse.
* `PriorEncounterSummary` shared between API response surface + note-gen
  rendering — no parallel shapes.
* Indexed-hash lookup converts BOTH call sites in this PR. No "migrate
  later" lingering linear-scan code.
* The runtime "append prior-context sentence to system prompt" pattern
  lives in ONE place inside `generate_stage1_note`.

## CLAUDE.md gates

* **Per-physician scope is hard**: every query filters
  `clinician_id == current_clinician.user_id`. A dedicated test asserts
  Marie's prior never reaches Perry's session even when both use the
  same patient identifier (different physicians, different panels).
* **Descriptive mode preserved**: base prompt unchanged; the appended
  sentence reinforces, doesn't loosen. `assessment` section is
  explicitly dropped from the rendered prior context so the model can't
  echo a prior diagnostic impression.
* **Audit append-only**: only inserts; no PHI in detail keys (count +
  date only).
* **No PHI in logs / errors**: load failures return structured errors
  that never echo the identifier value.

## Verification gate (§8)

1. Alembic up → down → up reversible
2. `pytest tests/integration/test_longitudinal_context.py
   tests/unit/test_identifier_hash.py
   tests/integration/test_me_patient_sessions_indexed_lookup.py -v` →
   all pass
3. `pytest -q` full suite → baseline 974 → expect 990+
4. `ruff check .` → clean
5. Phase A regression `test_descriptive_mode_phrases_locked` STILL
   passes
6. `cd web && npm run lint` clean
7. `cd web && npm run build` clean
8. `cd web && npx vitest run` → all pass including
   `NoteContextBadge.spec.tsx`
9. `cd ios/Aurion && xcodebuild test -scheme Aurion -destination
   'platform=iOS Simulator,name=iPhone 15'
   -only-testing:AurionTests/PriorEncountersTests` → all pass
10. `cd infrastructure && terraform validate` clean; `terraform plan
    -var-file=environments/dev.tfvars` shows only expected additions

## Out of scope

* Backfilling prior context onto historical Stage 1 notes — only new
  notes get the contextual augmentation.
* Cross-clinician longitudinal view (a different physician's prior
  notes for the same patient identifier). Per-physician panel is the
  current design constraint.
* The portal patient timeline already shipped in #223 / #224; no
  layout changes here.

## Deferred

* Future iteration could let physicians toggle "use prior context" per
  session; today the read is automatic when an identifier is set on
  the current session.

## Backlog

* Surface prior-context usage in the audit detail view of the web
  portal (event row already present; UI line is the deferred work).
