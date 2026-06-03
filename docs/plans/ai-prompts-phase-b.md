# AI-PROMPTS-B — Per-physician append-only overlays + safety (Phase B)

## Task
AI-PROMPTS-B — let pilot physicians append personal preferences below
each AI system prompt without modifying the descriptive-mode base. The
overlay is per-physician, structurally validated at save time, and
clearly separated from the base in the assembled prompt so the LLM
treats it as preferences, not as an override of the safety boundary.

## Why
Phase A made the prompts visible. Phase B makes the boundary
**editable, but only in the safe direction** — physicians can add
preferences ("Always note bilateral comparison when applicable"; "Use
millimeters not centimeters for wound measurements") without ever
weakening the descriptive-mode guarantee. The base text is
unchangeable; the overlay is appended below a clear separator. A
structural safety check (length cap + banlist) catches the obvious
jailbreak attempts at save time.

Architectural rules locked by the CTO:
- **Append-only** — overlay text appended below the base with a clear
  separator. Base prompt is NEVER modified. Combined = `{base}\n\n--- Physician preferences ---\n{overlay}`.
- **Per-physician scope** — Marie's overlays affect only sessions
  where she is `clinician_id`. Perry's overlays affect only Perry's.
  No clinic-wide overrides.
- **Safety validation at save time** — structural only (length cap +
  banlist) for v1. No LLM-based intent classification yet.
- **Sandbox preview** — shows the assembled prompt text. No LLM round-trip.
- **Audit** — every save/revert writes `PROMPT_OVERRIDE_SET` /
  `PROMPT_OVERRIDE_CLEARED` events. Overlay text NOT in the audit row
  (no PHI risk, no leakage of private clinical phrasing).

## Approach

### Backend

- **Alembic migration `0025_prompt_overrides`** — new table:
  ```sql
  CREATE TABLE prompt_overrides (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    prompt_id    VARCHAR(64) NOT NULL,
    overlay_text TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (owner_id, prompt_id)
  );
  CREATE INDEX ix_prompt_overrides_owner ON prompt_overrides(owner_id);
  ```
  Reversible downgrade.

- **`core/models.py`** — add `PromptOverrideModel` (SQLAlchemy 2.0
  Mapped typed columns matching `PhysicianMacroModel` pattern).

- **`modules/prompts/safety.py`** — `validate_overlay(text: str) -> ValidationResult`.
  Strip whitespace. Empty → `EMPTY`. >1000 chars → `TOO_LONG`.
  Banlist hit (case-insensitive substring) → `BANNED_PHRASE` with
  `matched_phrase` set. Otherwise `OK`. Banlist phrases come from the
  CLAUDE.md descriptive-mode boundary ("ignore previous instructions",
  "you may diagnose", "stop being descriptive", …).

- **`modules/prompts/assembly.py`** — `assemble_prompt(prompt_id, owner_id, db)`:
  ```python
  base = PROMPTS[prompt_id].system_prompt
  overlay = await _get_owner_overlay(db, owner_id, prompt_id)
  if not overlay:
      return base
  return f"{base}\n\n--- Physician preferences ---\n{overlay}"
  ```
  Single DRY source of prompt assembly for the whole codebase.

- **`api/v1/me_prompts.py`** — extend with:
  - `GET /me/prompts` response gains `overlay_text`, `is_overridden`,
    `assembled_preview`. (Renames the forward-looking Phase A
    `override_text` → `overlay_text` for consistency with the rest of
    Phase B; the unused Phase A field is fair game to rename — Phase
    A test asserted `is None` only.)
  - `PATCH /me/prompts/{prompt_id}` (CLINICIAN-only) — validates, upserts, audits `PROMPT_OVERRIDE_SET`, returns updated PromptResponse.
  - `DELETE /me/prompts/{prompt_id}` (CLINICIAN-only) — drops the row, audits `PROMPT_OVERRIDE_CLEARED`, returns base.

- **`core/audit_events.py`** — append `PROMPT_OVERRIDE_SET` /
  `PROMPT_OVERRIDE_CLEARED` to the enum + ALLOWED_AUDIT_KWARGS
  (whitelist: `actor_id`, `prompt_id`, `overlay_length`). Update lock
  test.

- **Provider methods** — additive `system_prompt: str | None = None`
  argument to:
  - `NoteGenerationProvider.generate_note`
  - `VisionProvider.caption_frame`
  - `VisionProvider.caption_clip`
  When `None`, providers use the existing constant (backward-compat).
  When set, providers use the override. Liskov holds — additive only.

- **8 consumer wiring sites** (where we replace raw constant with
  `assemble_prompt(...)`):
  1. `note_gen/service.py::generate_stage1_note` — `prompt_id="note_generation"`, owner = session's `clinician_id` (looked up via `session_id`)
  2. `vision/service.py::caption_visual_evidence` (frame path) — `prompt_id="vision_frame"`
  3. `vision/service.py::caption_visual_evidence` (clip path) — `prompt_id="vision_clip"`
  4. `vision/reconcile.py::reconcile_captions` — `prompt_id="conflict_reconciliation"`
  5. `patient_summary/service.py::generate_summary` — `prompt_id="patient_summary"`
  6. `orders/service.py::extract_from_note` — `prompt_id="orders_extraction"`
  7. `coding/service.py::extract_from_note` — `prompt_id="coding_suggestions"`
  8. `live_preview/service.py::generate_preview` — `prompt_id="live_preview"`

  At each site, the service layer fetches `session.clinician_id` and
  passes the assembled prompt down. `generate_text` (orders / coding /
  patient summary) gets the assembled system prompt directly as its
  `system` arg.

- **`critique_note` (Phase A pre-existing, NOT in registry)** — left
  unchanged. The critique prompt isn't in PROMPTS and has no overlay.
  Documented as deliberate scope.

### Frontend

- **`web/types/index.ts`** — extend `AIPrompt`: add `overlay_text`,
  `is_overridden`, `assembled_preview`. Removes Phase A's
  forward-looking `override_text` (renamed for consistency).

- **`web/lib/portal-api.ts`** — `patchMyPromptOverride(promptId,
  overlayText)` + `deleteMyPromptOverride(promptId)` thin wrappers.

- **`web/components/portal/PromptCard.tsx`** — extend:
  - "Override active" badge when `is_overridden`
  - "Edit preferences" button → opens editor modal (CLINICIAN only — chip stays read-only otherwise)
  - "Reset to default" button when overridden (confirm)

- **`web/components/portal/PromptOverrideEditor.tsx`** — new modal:
  - Base prompt (read-only monospace pre)
  - Your preferences (textarea + char count)
  - Live preview of combined prompt (re-renders on type)
  - Tips list (3-4 safe examples)
  - Save / Reset / Cancel
  - Banned-phrase inline error banner with `matched_phrase` echo

- **`web/messages/{en,fr}.json`** — extend `AIPrompts` namespace.

### Tests

- `backend/tests/unit/test_prompt_assembly_safety.py`:
  - validate_overlay accepts well-formed text
  - rejects each banned phrase (one assertion per)
  - rejects > 1000 chars + empty
  - assemble_prompt returns base when no overlay
  - assemble_prompt returns base + overlay with the separator
  - **base immutability** — base text exactly present at start of assembled
- `backend/tests/integration/test_prompt_overrides.py`:
  - PATCH happy path, returns updated PromptResponse
  - PATCH safety failure → 400 with matched_phrase
  - DELETE removes row + audits
  - **per-physician isolation** — Marie's overlay doesn't bleed into Perry's assembled prompt
  - audit detail does NOT contain overlay text
- `web/tests/PromptOverrideEditor.spec.tsx`:
  - opens empty / pre-filled
  - live preview updates
  - char count updates
  - save success / banned-phrase failure
  - reset confirm / cancel
  - i18n EN + FR coverage

## DRY/SOLID gates (§6c)

- **DRY** — one `assemble_prompt`, one banlist, one `validate_overlay`. No duplicated assembly logic in providers.
- **SRP** — assembly = read base + overlay. Safety = validate. Endpoint = serialize + audit. Card = display. Editor = capture + preview.
- **Open/Closed** — add a banned phrase → one tuple entry. Add a 9th prompt → registry entry only.
- **LSP** — `PromptResponse` shape is additive-only between overridden and non-overridden. Provider methods get an additive optional `system_prompt` argument.
- **DIP** — assembly takes the DB session (doesn't construct it). Audit via the injected `write_audit` helper.

## CLAUDE.md gates

- **Descriptive-mode boundary preserved** — base text is the boundary; overlay appends. Phase A `test_descriptive_mode_phrases_locked` still passes (bases unchanged).
- **No PHI in audit details** — audit event records `actor_id + prompt_id + overlay_length`. Test asserts overlay text isn't echoed in audit row.
- **No PHI in error messages** — `matched_phrase` echo is the banned phrase (not patient content), so safe.
- **Audit append-only** — only INSERT into the audit log.

## Acceptance criteria (matrix)

| # | What | How verified |
|---|------|--------------|
| AC-1 | Marie sets overlay on `note_generation`. Her next Stage 1 call sees base + overlay. | Integration test, PATCH then assemble_prompt round-trip |
| AC-2 | Perry's `note_generation` for the same session is base-only — no leakage. | Integration test `test_one_physicians_overlay_does_not_leak` |
| AC-3 | Banned phrase rejected with 400 + `matched_phrase`. | Integration test, all banlist entries |
| AC-4 | Empty / >1000 char overlays rejected with 400. | Unit test |
| AC-5 | DELETE returns to base; row removed; audit emits CLEARED. | Integration test |
| AC-6 | Phase A safety test `test_descriptive_mode_phrases_locked` still passes. | Existing test, unchanged base text |
| AC-7 | Audit row for SET does NOT contain overlay text. | Integration test |
| AC-8 | Web editor saves, previews live, surfaces banned-phrase errors with matched_phrase. | Vitest |
| AC-9 | EN + FR i18n parity for all new keys. | Vitest + grep |
| AC-10 | Per-physician override flows through every consumer site. | 8 wiring sites updated; existing Stage 1/2 happy-path integration tests still pass |

## Out of scope (Phase C)

- LLM-based intent classifier on the overlay
- Clinic-wide / specialty-wide overlays
- Sandbox preview that actually calls the LLM
- Versioning / history of overlay edits
- iOS surfacing of the override status
