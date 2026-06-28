## Task
GS-7 (#549) — feature flag `grounded_synthesis_enabled` (default OFF)

## Why
First slice of the v3.2 Grounded Synthesis epic (#552). Everything that relaxes
descriptive-only output (GS-1/3/4/5) must ship DARK behind one flag so the pilot's
live behaviour stays descriptive until clinical/regulatory sign-off (GS-9, CLAUDE.md
"Single Most Important Constraint"). This task adds ONLY the flag + plumbing — no
prompt change — so it is safe to merge now and is the hook GS-1/GS-3/GS-4 gate on.

## Approach
Mirror the existing `specialty_style_in_prompt_enabled` flag exactly:
- `backend/app/modules/config/schema.py` — add `grounded_synthesis_enabled: bool = False`
  to `FeatureFlagsConfig` (default OFF).
- `infrastructure/appconfig.tf` — add `grounded_synthesis_enabled = { type = "boolean" }`
  to the validator's `feature_flags` properties (additionalProperties=false → REQUIRED,
  else portal saves 502, cf. #530).
- `backend/app/api/v1/admin/feature_flags.py` — surface in `FeatureFlagsResponse` +
  `_build_response` so the portal can toggle it (the single switch flipped after GS-9).
No prompt assembly change in this PR — the read sites land with GS-1/GS-3.

## Acceptance criteria
- [ ] AC-1: `FeatureFlagsConfig().grounded_synthesis_enabled is False`, verified by `tests/unit/test_grounded_synthesis_flag.py`
- [ ] AC-2: the AppConfig validator's `feature_flags` props include `grounded_synthesis_enabled`, verified by the existing schema↔validator drift test (`tests/unit/test_feature_flags_admin.py`) staying green
- [ ] AC-3: `FeatureFlagsResponse` round-trips the new flag (GET/save), verified by `test_grounded_synthesis_flag.py`
- [ ] AC-4: no Stage-1 prompt change — assembled descriptive prompt is unaffected (no read site added yet), verified by `test_note_gen` / `test_specialty_prompts` staying green

## DRY / SOLID check
- **Existing helpers to reuse**: `FeatureFlagsConfig` (Pydantic), the `specialty_style_in_prompt_enabled` flag pattern, `_build_response`, the appconfig.tf validator block. No new helper.
- **New helper introduced?**: no — one field added to each of three existing surfaces, mirroring an established flag.
- **iOS UI tasks only**: n/a (backend only).

## Out of scope
- Any prompt-text change (GS-1, GS-3), validator-anchor change (GS-4), examples (GS-2), CLAUDE.md (GS-5), multi-anchor schema (GS-6). This PR is the inert flag only.
- Flipping the flag ON (gated on GS-9 sign-off).

## Test plan (executable)
1. `cd backend && python3 -m pytest tests/unit/test_grounded_synthesis_flag.py tests/unit/test_feature_flags_admin.py -q`
2. `cd backend && python3 -m pytest tests/unit/test_note_gen.py tests/unit/test_specialty_prompts.py -q` (no prompt drift)
3. `python3 -c "from app.modules.config.schema import FeatureFlagsConfig; assert FeatureFlagsConfig().grounded_synthesis_enabled is False"`

## Security implications
- No PHI, no audit-write path change. No AI prompt change → **descriptive mode fully preserved** (flag OFF, no read site). Provider registry untouched. The flag is the mechanism that KEEPS descriptive mode the default while the rest of the epic lands dark.
