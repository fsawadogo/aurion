# Plan: P1-7 — Per-session `visual_evidence_mode` override (vertical slice)

> Source plan: `~/.claude/plans/dual-mode-visual-evidence.md` ·
> Phase 1 PR breakdown (see "Phased rollout"). This PR completes the
> last item from the Phase-1 list — the per-session override knob that
> lets the eval team flip mode without touching AppConfig.

## Task

Wire the `visual_evidence_mode` value into the existing
`session.provider_overrides` dict so the eval team can flip mode for a
single session via the create-session API. Feature-gated by
`feature_flags.per_session_visual_evidence_mode_override`.

## Why

P1-1..P1-6 shipped all the wiring for dual-mode visual evidence with
default `frames_only`. Today the only way to flip a session to
`clips_only` is an AppConfig change that hits every active user. The
eval-team workflow (per dual-mode plan §"Phased rollout", Phase 2)
needs to A/B 20 sample sessions against the same source material —
flipping AppConfig globally is the wrong knob.

`per_session_visual_evidence_mode_override` already exists as a
feature flag (P1-1) but nothing currently gates on it. This PR makes
the flag actually mean something.

## Acceptance criteria

- [ ] **AC-1**: `POST /sessions` with `provider_overrides:{visual_evidence_mode:"clips_only"}` succeeds with 201 and the response surfaces the override. Verified by `tests/integration/test_session_mode_override.py::test_create_session_with_visual_evidence_mode_override_roundtrips`.
- [ ] **AC-2**: `POST /sessions` with `visual_evidence_mode:"INVALID"` returns 422 (Pydantic validation). Verified by `test_invalid_visual_evidence_mode_rejected`.
- [ ] **AC-3**: Unknown keys in `provider_overrides` (e.g. `{foo:"bar"}`) are rejected with 422. Verified by `test_unknown_override_key_rejected`.
- [ ] **AC-4**: When `per_session_visual_evidence_mode_override=False` and the request carries `visual_evidence_mode`, the route returns 400 with the documented error string. Verified by `test_override_disabled_returns_400`.
- [ ] **AC-5**: Successful override emits `VISUAL_EVIDENCE_MODE_OVERRIDE_SET` to the audit log with `{actor_id, actor_role, mode}` and no PHI. Verified by `test_override_set_emits_audit_event`.
- [ ] **AC-6**: `resolve_evidence_mode` returns the session override when present and the AppConfig default when absent. Verified by `tests/unit/test_visual_evidence_mode_resolution.py`.
- [ ] **AC-7**: iOS `extractEvidence` reads the session-level override first, then falls back to `RemoteConfig.shared.pipeline.visualEvidenceMode`. Verified by `AurionTests/SessionModeOverrideTests`.

## Approach

### Backend

1. **Schema (`backend/app/api/v1/sessions.py`)**
   - Add `ProviderOverridesSchema(BaseModel)` with closed key set: `transcription`, `note_generation`, `vision`, `vision_clip`, `visual_evidence_mode` (the last typed as `Optional[VisualEvidenceMode]`).
   - Use `model_config = ConfigDict(extra="forbid")` to reject unknown keys.
   - `CreateSessionRequest.provider_overrides: Optional[ProviderOverridesSchema] = None`.

2. **Flag gate**: in `create_session_route`, fetch AppConfig once via `get_config()`; if the flag is False and the body includes `visual_evidence_mode`, raise `HTTPException(400, "per-session visual_evidence_mode override is disabled in this environment")`.

3. **Storage bug fix**: `modules/session/service.py:105` currently does `str(provider_overrides)` which produces Python repr (`{'visual_evidence_mode': 'clips_only'}`). That's not valid JSON. Switch to `json.dumps(...)` so round-trips work. This is the actual data-path bug that's invisible today because nothing reads the field back.

4. **Audit emission**: `create_session_route` emits `VISUAL_EVIDENCE_MODE_OVERRIDE_SET` after `SESSION_CREATED`, gated on `body.provider_overrides.visual_evidence_mode` being set. Whitelist: `{session_id, mode, actor_id, actor_role}`.

5. **`_to_response`**: deserialize stored JSON → dict; expose on `SessionResponse.provider_overrides: Optional[dict]`.

6. **Vision dispatch (`modules/vision/service.py`)**: new helper `resolve_evidence_mode(session, app_config) -> VisualEvidenceMode`. ONE call site, ONE function. Invalid raw string raises ValueError; the caller catches + falls back to AppConfig default + logs a warning.

### iOS

7. **`Network/APIClient.swift`**: `ProviderOverrides` codable type with snake_case CodingKeys for all 5 keys (all optional). `SessionResponse` gains `providerOverrides: ProviderOverrides?`.

8. **`Session/SessionManager.swift`**: `extractEvidence` (or a new `resolveEvidenceMode` helper) reads `session?.providerOverrides?.visualEvidenceMode` first; falls back to `RemoteConfig.shared.pipeline.visualEvidenceMode` when absent or unparseable.

9. **`Session/SessionState.swift::CaptureSession`**: store `providerOverrides: ProviderOverrides?`. Adopted from `SessionResponse` in `startNewSession` and `adoptSession`.

### Tests

10. **`tests/integration/test_session_mode_override.py`** — full route coverage per AC-1..AC-5.

11. **`tests/unit/test_visual_evidence_mode_resolution.py`** — resolver behavior per AC-6.

12. **`AurionTests/SessionModeOverrideTests.swift`** — iOS dispatcher per AC-7.

## DRY / SOLID check

- **Existing helpers reused**: `get_config()` for AppConfig, `write_audit` from `_helpers`, the existing `ALLOWED_AUDIT_KWARGS` pattern for the new event, existing `VisualEvidenceMode` enum, the existing `_caption_single` dispatch loop in `vision/service.py`.
- **New helper introduced?**: Yes — `resolve_evidence_mode`. This is the SECOND copy of the override-or-default pattern (the first is `_caption_single` reading the global config directly), and pre-emptively becomes the ONE call site so the override read is centralized before any third copy emerges.
- **OCP**: adding a new override key in the future = one field on `ProviderOverridesSchema` + one field on iOS `ProviderOverrides`. No new branching in the dispatch loop.
- **LSP**: resolver returns the same `VisualEvidenceMode` enum the AppConfig pipeline returns — dispatch loop treats both inputs identically.
- **SRP**: schema validation in Pydantic, audit emit in the route layer (next to SESSION_CREATED), dispatch in vision service.
- **DIP**: AppConfig via `get_config()`, never instantiated inline.

## Out of scope

- Admin API for global `visual_evidence_mode` switching (already lives in AppConfig — `level 1` switching path per CLAUDE.md).
- Per-physician/per-specialty defaults — Phase 3 work per the dual-mode plan.
- Web portal UI for setting per-session overrides — eval team uses the API directly during Phase 2.
- iOS UI for selecting the override at session creation — eval-team-only knob today.

## Test plan (executable)

1. `cd /Users/fsawadogo/aurion-lanes/p1-7-override/backend && python3 -m pytest tests/integration/test_session_mode_override.py tests/unit/test_visual_evidence_mode_resolution.py -v` → all pass
2. `cd /Users/fsawadogo/aurion-lanes/p1-7-override/backend && python3 -m pytest -q` → full suite passes
3. `cd /Users/fsawadogo/aurion-lanes/p1-7-override/backend && python3 -m ruff check .` → clean
4. `cd /Users/fsawadogo/aurion-lanes/p1-7-override && xcodebuild -project ios/Aurion/Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build` → BUILD SUCCEEDED
5. `cd /Users/fsawadogo/aurion-lanes/p1-7-override && xcodebuild -project ios/Aurion/Aurion.xcodeproj -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M5)' build` → BUILD SUCCEEDED
6. `xcodebuild test -only-testing:AurionTests/SessionModeOverrideTests …` → all pass

## Security implications

- **Audit append-only**: new event type added; whitelist enforces no PHI fields. `actor_id` is the clinician UUID — already in many other event types, not PHI.
- **No PHI in logs**: resolver logs the `mode` enum value + session_id (UUID); no transcript content, no patient identifier.
- **Feature flag gates the path**: when flag is False, request returns 400 deterministically. AppConfig change picked up within polling window (~30 s).
- **AI calls via registry**: unchanged — this PR routes between existing provider methods, never instantiates one inline.
