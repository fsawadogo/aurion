# Plan — tpl-central-2 (#576): close the visit-type context parity gap (web)

## Task
#576 (epic #574). Scope decision (Uzziel, 2026-06-30): **no new page.** The
web already manages visit types + per-context template pinning live inside
`/portal/profile` (`ConsultationTypesEditor` + `VisitTypeContextsEditor`,
shipped in #313/W1 + #320/W2). The only gap vs iOS + the backend contract is
the per-context **`description`** field — backend persists & returns it
(`VisitTypeContext.description: Optional[str]`, ≤500 chars), iOS edits it, but
the web type omits it and the editor drops it on round-trip. Close that gap and
close #576 as covered.

## Why
`web/types VisitTypeContext` has no `description`, so the existing Profile page
silently discards any description the backend/iOS set. Adding it reaches feature
parity and stops the web from clobbering iOS-authored context notes on save.

## Scope confirmation (already shipped — no change needed)
- Create custom visit type, add/edit/delete contexts, 30-cap → `ConsultationTypesEditor` + `VisitTypeContextsEditor`.
- Pin a template per context (specialty default + 8 built-ins + the caller's **owned** custom templates) with `template_key` XOR `template_ref` mutual exclusion → backend only allows **owned** refs (`get_owned`), so "fork a Library template (#575) → pin your copy" is the intended path. Editor already offers owned-only. Correct as-is.
- GET/PUT `/profile` round-trip → `getMyProfile` / `updateMyProfile`. No backend change.

## Approach (web only)
- `web/types/index.ts`: add `description?: string | null` to `VisitTypeContext`
  (covers read + the `PhysicianProfileUpdate` write path, same type).
- `web/components/portal/VisitTypeContextsEditor.tsx`: render an optional
  multiline `<textarea>` per context under the label+template row — `maxLength=500`,
  `value={ctx.description ?? ""}`, `onChange → updateContext(vt, id, {description: v === "" ? null : v})`.
  New contexts get `description: null`. Mirrors iOS (optional free-text, 500-char clamp).
- `web/messages/{en,fr}.json` (`Profile.contexts`): add `descriptionPlaceholder`
  + `descriptionAria` (mirrors existing `labelAria`/`templateAria`). NB the
  namespace already has a fieldset-level `description` key — do not collide.
- `web/tests/VisitTypeContexts.spec.tsx`: +tests — a description textarea renders
  per context; typing fires `onChange` with the new `description`; clearing sends `null`.

## Acceptance criteria
- [ ] AC-1: each context row shows an optional description textarea (≤500 chars), pre-filled from `ctx.description`.
- [ ] AC-2: editing it updates `contexts_per_visit_type[vt][i].description`; clearing sets it to `null`; it round-trips through PUT `/profile`.
- [ ] AC-3: `description` added to the web `VisitTypeContext` type; en/fr keys in lockstep.
- [ ] AC-4: eslint + tsc clean; vitest green (existing + new editor tests).

## DRY / SOLID
Reuses the existing controlled-input editor, `updateContext`, the i18n namespace,
and the profile page's PUT path. New = one optional field + 2 i18n keys + tests.
No new mechanism, no backend change, no new page.

## Out of scope
- A dedicated `/portal/visit-types` page (scope decision: keep in Profile).
- Pinning shared/Library templates directly (backend allows owned refs only — fork first via #575).
- Client-side replication of the backend's `validate_user_text` content rules; `maxLength=500` client cap + server 422 (surfaced via `humanizeError` on save).

## Test plan (executable)
1. `cd web && npx vitest run tests/VisitTypeContexts.spec.tsx tests/i18n-bootstrap.spec.ts`
2. `cd web && npx eslint components/portal/VisitTypeContextsEditor.tsx types/index.ts`
3. `cd web && npx tsc --noEmit` → no new errors
4. Live: `localhost:3000` → `perry@creoq.ca`/`perry` → Profile → expand a visit type → add a context → type a description → Save → reload → description persists.

## Security implications
- Web-only; enforcement stays server-side. Context labels + descriptions can be
  PHI — they ride only the parent's PUT body, never a client log (the editor
  already honours this; the textarea follows the same path).
