# Plan — TE-2

## Task

TE-2 — Load the session's template into Stage 2 (plumbing only).

## Why

Cohort 7 (Template Engine · generation core) is the current priority — Uzziel, 2026-07-17: *the template should be what prompts the transcript **and the frames** into good usable notes; frames must not just be descriptions.*

Today the template governs the transcript half only. In Stage 2 the `Template` object **is not in scope at all** — `run_stage2_vision` holds the `Note` (which carries `.specialty`, a bare string) but never the template's sections, titles, descriptions or `visual_trigger_keywords`. So the frames path has nothing to be "template-aware" *with*.

TE-3 (template-aware capture) and TE-4 (template-formatted merge) both need it. This slice is the plumbing they depend on, isolated so it can land and be verified on its own — no behaviour change, nothing to review but the wiring.

Satisfies backlog `Cohort 7 · TE-2`.

## Approach

Add a **public** resolver in `note_gen` and call it from the Stage-2 route.

`_resolve_stage1_template` (`note_gen/service.py:741`) is private and takes loose args. Stage 2 must not reach into another module's privates, and it must resolve **the same template Stage 1 used** — not re-derive one from `specialty`, which would silently diverge whenever a session pinned a context/custom template.

1. `note_gen/service.py` — new public `resolve_session_template(session, db) -> Template`, composing the two existing pieces: `stored_template_pin(session)` → `_resolve_stage1_template(...)`. One call, no new resolution logic.
2. `api/v1/vision.py` — in `run_stage2_vision`, resolve the template right after `session_row` is loaded (already fetched at `:125-129` for the evidence mode) and hold it in scope.

Nothing consumes it yet. TE-3/TE-4 do.

**Layering.** The resolution happens in the API/orchestration layer (`api/v1/vision.py`), which already imports `note_gen` (`get_latest_note` `:111`, `create_note_version` `:230`). `modules/vision/*` stays free of a `note_gen` dependency, per CLAUDE.md *"Modules never import each other."*

**Failure posture.** `_resolve_stage1_template` already degrades defensively — a deleted/unparseable custom template falls back to the built-in/specialty path rather than raising. Stage 2 inherits that: a template that can't be resolved must never break vision enrichment.

## Acceptance criteria

- [ ] **AC-1:** `resolve_session_template` returns the *same* template Stage 1 used for a session pinned to a **built-in** `template_key` — verified by `test_te2_template_into_stage2.py::test_resolves_same_builtin_template_as_stage1`
- [ ] **AC-2:** same, for a session pinned to a **custom** `custom_template_id` — `::test_resolves_pinned_custom_template`
- [ ] **AC-3:** an unpinned session resolves to the **specialty default** (byte-for-byte the pre-existing path) — `::test_unpinned_session_falls_back_to_specialty`
- [ ] **AC-4:** a **stale/deleted** custom pin degrades to the specialty default and does **not** raise — `::test_stale_custom_pin_degrades_without_raising`
- [ ] **AC-5:** `run_stage2_vision` holds the resolved template in scope — `::test_stage2_resolves_template_in_scope`
- [ ] **AC-6:** **zero behaviour change** — Stage 2's merged note output is byte-identical to before for the existing fixtures; full `tests/unit/` green

## DRY / SOLID check

- **Existing helpers reused:** `stored_template_pin` (`session/service.py:108`), `_resolve_stage1_template` (`note_gen/service.py:741`), `get_latest_note`, `write_audit`. No new resolution logic — the new function only composes two that exist.
- **New helper introduced?** **Yes — one**, and it is justified by a module boundary rather than a third copy: Stage 2 needs template resolution but must not import `note_gen`'s private `_resolve_stage1_template`. Exposing a narrow public entry point (`resolve_session_template`) is the ISP-clean way to cross that boundary. It also becomes the single place "resolve the template this session was built with" lives, which TE-3/TE-4 reuse rather than re-deriving.
- **SRP:** the route does orchestration only (resolve → hold); resolution logic stays in `note_gen`.
- **iOS UI task?** No.

## Out of scope

- Using the template for anything (that's TE-3 capture / TE-4 merge). This slice is deliberately inert.
- Changing captioning, reconciliation, merge, or section routing.
- The `template_engine_enabled` flag — nothing user-visible changes here, so nothing to gate. The flag lands with TE-3, the first slice that alters output.
- Any prompt change.

## Test plan (executable)

1. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_te2_template_into_stage2.py -v` → all AC pass
2. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/ -q` → full suite green (CI runs the whole directory)
3. `cd backend && .venv/Scripts/python.exe -m ruff check app/ tests/` → clean
4. `docker compose -f backend/docker-compose.yml -f backend/docker-compose.override.yml up -d` → `curl -fs localhost:8080/health` → 200
5. `git diff --stat main...HEAD -- ios/ web/` → empty

## Security implications

- **PHI:** none. The template is clinician-authored structure (section ids, titles, capture guidance) — not patient data. Nothing new is logged; no template text reaches logs, errors or API responses in this slice.
- **AI prompts:** none changed. No template text reaches any model in TE-2 — that begins in TE-3, which carries the banlist-screen + fencing requirement (adopted from Faïçal's v2 safety model) precisely because clinician-authored text will then reach a vision prompt.
- **Descriptive mode:** untouched.
- **Audit log:** no new events.
- **Consent / masking / secrets:** untouched.
