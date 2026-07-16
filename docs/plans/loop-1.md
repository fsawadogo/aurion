# Plan — loop-1

## Task

loop-1 — `regenerate-note` must confirm before discarding work Stage 1 cannot rebuild.

## Why

Cohort 6 (Template Functional Loop) is the current priority, set by the 2026-07-15 weekly: *"la sélection de modèles et le formatage de sortie"*. Step 3 of that loop — switch template → regenerate — is broken today.

`approve_note` (`note_gen/service.py:1448`) raises `UnresolvedConflictError` when any `conflict_*` claim is unresolved. That enforces CLAUDE.md's success criterion **"CONFLICTS resolution: 100% resolved before approval"**. Regenerate rebuilds the note from the transcript alone and drops those claims, so **a note that could not be signed becomes signable**. The route has no `require_state` gate, so this is reachable from `AWAITING_REVIEW` and `PROCESSING_STAGE2`. It is live behind `note_options_enabled` / per-user `prompt_testing_enabled`.

Separately, an omitted `template_key` fell through to the **specialty default** rather than the template the session was created with — silently swapping the physician's template on a plain re-run.

## Approach

Re-merging is impossible — verified before designing:
- Frame captions are never persisted. `FrameCaption` is Pydantic-only (`core/types.py:287`); no table, no migration.
- Screen claims have no orchestrator (no `run_screen_for_session` analogue to `run_stage2_vision`).
- `export` calls `purge_frames`, so post-export Stage 2 can never be re-run at all.

So the honest fix is a **confirm-or-409 gate**, not restoration. Files:

- `api/v1/sessions.py` — `confirm_discard` on the request; loss gate; session-pin template default; `NOTE_REGENERATED` audit.
- `modules/note_gen/service.py` — new `regenerate_discard_summary()` beside `unresolved_conflict_claim_ids`; `stats_trigger` param on `generate_stage1_note`.
- `modules/session/service.py` — new `stored_template_pin()`.
- `api/v1/transcription.py` — repoint 2 call sites (the DRY extraction).
- `core/audit_events.py` + `tests/unit/test_audit_events.py` — register the event.

Subagents: none available (`.claude/agents/` does not exist — §7 subagents were never generated). Implemented inline; review delegated to two independent general-purpose agents (correctness + compliance).

## Acceptance criteria

- [ ] AC-1: A Stage-2 note + no `confirm_discard` → **409**, `detail.would_discard.visual_claims == 1`, note-gen never awaited, no commit — `pytest tests/unit/test_regenerate_note.py::test_regenerate_409s_rather_than_silently_dropping_stage2`
- [ ] AC-2: An unresolved conflict is reported separately from `visual_claims` — `::test_regenerate_409_reports_unresolved_conflicts_separately`
- [ ] AC-3: `confirm_discard=true` → proceeds, audits `discarded_work=True` + counts — `::test_regenerate_proceeds_when_discard_confirmed`
- [ ] AC-4: A lossless Stage-1 note needs no confirmation — `::test_regenerate_needs_no_confirmation_when_lossless`
- [ ] AC-5: An omitted template reuses the session's pin (`plastic_surgery`), NOT the specialty (`orthopedic_surgery`) — `::test_regenerate_without_a_template_reuses_the_session_pin`
- [ ] AC-6: A body template replaces the pin wholesale (never both to note-gen) — `::test_body_template_replaces_the_session_pin_wholesale`
- [ ] AC-7: An unknown `template_key` → 422, note-gen never awaited, **no audit row** — `::test_regenerate_rejects_unknown_template_key`, `::test_regenerate_never_audits_unvalidated_client_text`
- [ ] AC-8: The 409 body carries no claim text; all `would_discard` values are `int` — `::test_regenerate_409_detail_carries_no_claim_text`
- [ ] AC-9: Audit kwargs ⊆ `ALLOWED_AUDIT_KWARGS[NOTE_REGENERATED]` — `::test_regenerate_audit_kwargs_are_whitelisted`
- [ ] AC-10: Full `tests/unit/` green + ruff clean
- [ ] AC-11: **Mobile-ready** — `git diff --stat main...HEAD -- ios/ web/` is empty; the 409 contract is client-agnostic JSON
- [ ] AC-12: Stack boots — `docker compose up -d && curl localhost:8080/health` → 200

## DRY / SOLID check

- **Existing helpers reused**: `get_owned_session_or_404`, `write_audit`, `get_latest_note`, `is_unresolved_conflict_claim`, `unresolved_conflict_claim_ids`, `list_available_templates`, `get_config`, `create_note_version(stats_trigger=)`.
- **New helper introduced?**: **Yes, and it is the third copy** — `transcription.py:194` and `:435` both read the session template pin via `getattr(session, "template_key", None)` / `custom_template_id`. The regenerate route is the third site → extracted to `session.service.stored_template_pin`, both prior sites converted. `regenerate_discard_summary` is genuinely new (no prior implementation), and sits in `note_gen/service.py` beside the conflict-rule functions it depends on.
- **iOS UI tasks only**: n/a — no iOS files touched.

## Out of scope

- Turning `note_options_enabled` on.
- The web change-template UI (`regenerateNote` exists at `lib/api.ts:479` with zero call sites) → loop-4.
- Any note-content / verbosity change → Cohort 5.
- Re-injecting persisted measurement citations (recoverable, unlike captions) — counted in `would_discard` for now.

## Test plan (executable)

1. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/test_regenerate_note.py -v` → 25 passed
2. `cd backend && .venv/Scripts/python.exe -m pytest tests/unit/ -q` → full suite green (CI runs `tests/unit/`; targeted runs miss cross-cutting flag/audit fixtures)
3. `cd backend && .venv/Scripts/python.exe -m ruff check app/ tests/` → All checks passed
4. `docker compose -f backend/docker-compose.yml -f backend/docker-compose.override.yml up -d && curl -fs localhost:8080/health` → 200
5. `git diff --stat main...HEAD -- ios/ web/` → empty
6. `xcodebuild` → n/a, no iOS files in the diff

## Security implications

- **Touches PHI?** Reads the latest note to count claims. Output is counts only — `regenerate_discard_summary` only ever does `counts[key] += 1`; no claim text, ids, or section titles can reach the 409 body or the audit row. Asserted by AC-8.
- **Audit log?** Yes — new `NOTE_REGENERATED`, append-only. **`template_key` reaches an append-only store, where a PHI string is permanent by design**, and `ALLOWED_AUDIT_KWARGS` validates kwarg *names*, never values → the 422 validation (AC-7) is the only thing keeping the row PHI-free. A custom template's `key` IS physician-authored (`custom_templates/service.py:308`), so a client confusing it for a built-in key is a realistic trigger. A custom template is therefore reported as a bool only.
- **AI prompts?** None added or changed. `stats_trigger` is a plain audit label.
- **Consent gate?** Unchanged; route stays owner-scoped.
- **Secrets?** None touched.
