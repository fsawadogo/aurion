# AI-PROMPTS-A — Read-only Transparency page (Phase A)

## Task
AI-PROMPTS-A — surface every system prompt the LLMs use to analyze a
clinical encounter, on a single read-only Transparency page in the web
portal. CLINICIAN + ADMIN/EVAL_TEAM/COMPLIANCE_OFFICER can read; nobody
edits (yet — Phase B will add per-physician overlays).

## Why
Pilot physicians (CREOQ/CLLC, July 2026 demo) need to see how the AI is
told to interpret what they say + show + record. CLAUDE.md mandates
descriptive mode on every AI call; this page makes that boundary
legible to physicians who care about audit but don't read Python.
"Trust the AI" doesn't scale; "show the AI's instructions to the
physician" does.

This is the foundation for Phase B (per-physician append-only
overlays), so the API/schema accommodate `override_text` /
`is_overridden` fields the read-only response will carry as
constant defaults today.

## Approach

### Backend
- New module `app/modules/prompts/registry.py` with a
  `PromptDefinition` Pydantic model and a `PROMPTS` dict keyed by
  stable id.
- Registry IMPORTS the existing prompt constants — no copy-paste. Two
  underscore-prefixed module-level constants are promoted to public
  names so the registry can reach them without monkey-patching:
  - `vision/reconcile.py::_RECONCILE_SYSTEM_PROMPT` →
    `RECONCILE_SYSTEM_PROMPT`
  - `note_gen/critique.py::_CRITIQUE_SYSTEM_PROMPT` →
    `CRITIQUE_SYSTEM_PROMPT`
  Internal usages in those files swap to the public name; nothing
  outside the modules referenced the private names.
- New router `app/api/v1/me/prompts.py` exposes
  `GET /api/v1/me/prompts` to CLINICIAN/ADMIN/EVAL_TEAM/COMPLIANCE_OFFICER.
  The route serializes `PROMPTS` to a list of `PromptResponse`. No DB
  reads, no audit writes (read-only metadata endpoint — see
  CLAUDE.md gate notes below).
- Response schema is forward-compatible: `override_text` and
  `is_overridden` fields are present today as `None` / `False` so
  Phase B can wire the same shape without a breaking change.

### Frontend
- New page `web/app/portal/prompts/page.tsx` — server-side static
  shell + client component that fetches `/api/v1/me/prompts` and
  renders the cards.
- One card per prompt, grouped by category (Notes / Vision /
  Extraction / Live preview). Card collapsible expands to a `<pre>`
  block with the exact system prompt text.
- Search filter input narrows by name + purpose.
- Phase A read-only chip + descriptive-mode callout at the page
  header.
- New "AI Prompts" entry in the `Sidebar.tsx` nav for CLINICIAN +
  ADMIN.
- EN + FR i18n strings under new `AIPrompts` namespace + the
  `Sidebar.nav.aiPrompts` entry.

### Tests
- `backend/tests/integration/test_me_prompts.py` — 8 prompts visible
  to CLINICIAN; ADMIN/EVAL_TEAM/COMPLIANCE_OFFICER also see them;
  every prompt has non-empty system_prompt + purpose + runs_when;
  PHI scan; **descriptive-mode safety gate** (a regression test that
  fails if the literal phrases "do not interpret", "do not diagnose",
  or "describe only" are stripped from the AI-facing prompts).
- `web/tests/AIPromptsPage.spec.tsx` — cards render, search filters,
  expand toggle reveals system prompt, EN+FR catalog parity.

## Acceptance criteria
- [ ] AC-1: `GET /api/v1/me/prompts` returns 8 prompts for a
  CLINICIAN bearer token. Verified by
  `pytest tests/integration/test_me_prompts.py::test_clinician_sees_eight_prompts`.
- [ ] AC-2: Same endpoint returns 8 for ADMIN / EVAL_TEAM /
  COMPLIANCE_OFFICER bearers (parameterized test).
- [ ] AC-3: Every prompt entry has a non-empty `system_prompt`,
  `purpose`, and `runs_when`. Verified by
  `test_every_prompt_has_required_fields`.
- [ ] AC-4: Descriptive-mode language preserved verbatim — phrases
  "describe only", "do not interpret", or "do not diagnose" present
  in note_generation + vision_frame + vision_clip prompts. Verified
  by `test_descriptive_mode_phrases_locked` — this is the safety
  regression test.
- [ ] AC-5: No PHI patterns in the response (no SSN / DOB / patient
  name samples). Verified by `test_no_phi_in_prompts`.
- [ ] AC-6: Sidebar "AI Prompts" entry appears for CLINICIAN +
  ADMIN. Verified by inspecting `web/components/Sidebar.tsx`
  navigation array.
- [ ] AC-7: `/portal/prompts` page renders cards from a mocked API
  response, search filter works, expand toggle exposes the system
  prompt text. Verified by `web/tests/AIPromptsPage.spec.tsx`.
- [ ] AC-8: EN + FR JSON catalogs both contain the `AIPrompts`
  namespace at parity. Verified by `test_locale_parity` inside the
  same Vitest file.

## DRY / SOLID check
- **Existing helpers to reuse**: `get_current_user`, `CurrentUser`,
  `UserRole` (multi-role gate). All 8 prompt constants are already
  module-level — registry imports them directly.
- **New helper introduced?**: yes — `PromptDefinition` Pydantic
  shape + `PROMPTS` dict. This is a NEW abstraction (no prior
  catalog of system prompts exists) so it doesn't violate DRY; it
  REDUCES duplication going forward by giving Phase B a single
  registry to overlay against.
- **iOS UI tasks only — `mobile-ios-design` consulted**: n/a.

## Out of scope
- Phase B per-physician overlay editing (response schema is
  forward-compatible, no editing UI today).
- Surfacing prompts as part of the audit trail.
- LLM provider model identifiers (the page mentions "Powered by"
  but reads from the existing config surface; not a new endpoint).
- Template-authoring prompt — that's an authoring tool prompt, not
  in the encounter-analysis hot path. Out of scope for Phase A.

## Test plan (executable)
1. `cd /Users/fsawadogo/aurion-lanes/ai-prompts/backend && python3 -m pytest tests/integration/test_me_prompts.py -v`
2. `cd /Users/fsawadogo/aurion-lanes/ai-prompts/backend && python3 -m pytest -q`
3. `cd /Users/fsawadogo/aurion-lanes/ai-prompts/backend && python3 -m ruff check .`
4. `cd /Users/fsawadogo/aurion-lanes/ai-prompts/web && npm run lint`
5. `cd /Users/fsawadogo/aurion-lanes/ai-prompts/web && npm run build`
6. `cd /Users/fsawadogo/aurion-lanes/ai-prompts/web && npx vitest run`
7. `ls /Users/fsawadogo/aurion-lanes/ai-prompts/web/out/portal/prompts/index.html`

## Security implications
- **Descriptive-mode boundary**: this PR makes the prompts visible to
  physicians; it must NOT introduce any new prompt that contradicts
  the descriptive-mode constraint. The
  `test_descriptive_mode_phrases_locked` regression test locks that
  invariant into CI.
- **No PHI**: prompts are templates, not patient data. Tests verify.
- **Audit log**: `GET /me/prompts` is read-only metadata — no audit
  writes. Same posture as `/health`, `/templates` listing, etc.
- **Auth**: routes through the existing `get_current_user` JWT
  dependency. The role gate is a single new helper inside the new
  router file — narrow and explicit.
