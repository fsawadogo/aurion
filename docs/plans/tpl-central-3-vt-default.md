# Plan — tpl-central-3 (#577): per-visit-type default template resolution (backend)

## Task
#577 (epic #574). Add a per-visit-type **default** context so a session created
with `consultation_type` but **no `context_id`** resolves the visit type's
default template instead of falling straight to the specialty default.

Storage decision (Uzziel, 2026-06-30): **`is_default: bool` flag on the
context** (≤1 per visit type). No DB migration — `contexts_per_visit_type` is a
JSON Text column, so the field is additive and old rows parse as `false`.

## Why
Today `resolve_context_template_key` short-circuits at the top
(`if not context_id or not consultation_type: return None, None, False`), so
omitting `context_id` never even reads the profile — a visit type without an
explicit context pick always degrades to specialty. The default lets a clinician
make one context per visit type the go-to.

## Approach (backend only)
- **`backend/app/api/v1/profile.py`** — `VisitTypeContext`:
  - add `is_default: bool = False`.
  - enforce **≤1 default per visit type** in `_validate_contexts_per_visit_type`
    (the field validator that sees the whole list per VT); >1 → `ValueError`
    (422), value not echoed. The per-context `_validate` can't see siblings, so
    the count rule lives at the list level.
  - `is_default` rides the existing `model_dump()` serialize + raw GET, so PUT/GET
    round-trip it with no other API change.
- **`backend/app/modules/session/service.py`** — `resolve_context_template_key`:
  - change the short-circuit to `if not consultation_type: return None, None, False`.
  - fetch the profile (now needed for both paths), parse the map, get the VT's
    context list.
  - **explicit path** (`context_id` set): find by id — unchanged, incl. the
    "provided-but-missing → specialty default" behavior.
  - **default path** (`context_id` omitted): pick the first context with
    `is_default == True`; none → `(None, None, False)` (specialty fallback).
  - the matched context (either path) flows through the SAME existing template
    resolution (`template_key` → `template_ref` → specialty), so a stale default
    pin coerces + flags `coerced_stale` exactly like an explicit one.
  - Behavior change: an old client omitting `context_id` now triggers ONE extra
    indexed `SELECT` (by clinician_id) to check for a default. Session-create is
    not a hot path; acceptable.

## Acceptance criteria
- [ ] AC-1: session with `consultation_type` + no `context_id` + a VT default → resolves the default context's template (snapshotted).
- [ ] AC-2: no default set (or no profile / VT absent) → unchanged specialty fallback.
- [ ] AC-3: an explicit `context_id` still wins over / ignores the default.
- [ ] AC-4: a default context pinning a stale template coerces to specialty + flags `coerced_stale`.
- [ ] AC-5: PUT /profile rejects >1 `is_default` per visit type (422); GET round-trips the flag.
- [ ] AC-6: unit + integration tests; full backend suite + ruff green.

## DRY / SOLID
Reuses the existing match→template resolution + coercion + audit path; the only
new logic is *how the match is chosen* when `context_id` is absent. One new
field + one list-level validator + one branch. No migration, no new mechanism.

## Out of scope
- Web/iOS UI to SET a default ("set as default" toggle) — follow-up (issue notes
  "Optional pre-select cue = future Swift"). The web already round-trips unknown
  context fields at runtime (it passes parsed objects through), so a web profile
  save won't wipe an is_default set elsewhere; the web TYPE + control are a
  separate web-lane task.
- Pinning shared/Library templates (owned-only, unchanged — fork via #575).

## Test plan (executable)
1. `backend/.venv/Scripts/python -m pytest tests/unit/test_session_context_template.py tests/unit/test_context_custom_template.py -q`
   - UPDATE `test_no_context_id_short_circuits_without_db` — context_id=None now
     hits the DB to look for a default (contract changed); the no-DB short-circuit
     now only holds for `consultation_type is None` (already covered separately).
   - ADD: default resolves built-in; default resolves custom ref; no-default →
     fallback; explicit id wins over default; stale default coerces.
2. Profile validation test: PUT with 2 `is_default=true` in one VT → 422.
3. `backend/.venv/Scripts/python -m pytest -q` (full suite) + `ruff check .`
4. Health: `curl localhost:8080/health` still ok after a local API rebuild (or run targeted tests only — no runtime contract break for existing clients).

## Security implications
- No new PHI: `is_default` is a non-PHI boolean; resolution logs stay count-only
  (the existing `SESSION_TEMPLATE_KEY_COERCED` is kwarg-less). No secrets/auth
  change. Ownership re-check on a custom `template_ref` default is unchanged
  (still owner-scoped via `_resolve_custom_template_ref`).
