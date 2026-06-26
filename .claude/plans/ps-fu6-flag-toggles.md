# ps-fu6 — self-serve Feature Flags toggles (AI Prompts group)

Make the AI-Prompts feature flags flippable from the portal instead of
AppConfig-only, and fix a display bug on the read-only `/config` viewer.

## Context
`prompt_studio_enabled` was *already* a portal toggle (ps-fu, under a
"Workspace tools" group). Faical had to flip it via AppConfig only because the
**save was broken until #530's validator fix** — that's now resolved in prod.
`clinician_prompts_note_only` (ps-fu5) had no portal toggle at all.

## Changes (web only — the backend already accepts both flags, validator applied)
- `feature-flags/page.tsx`: rename the second `FLAG_GROUPS` entry to **"AI Prompts"**
  and add `clinician_prompts_note_only` beside `prompt_studio_enabled`. The
  existing `dirty`/`toggle`/`save` wiring picks it up via `EDITABLE_FLAGS`.
- `types/index.ts`: add `clinician_prompts_note_only: boolean` to `FeatureFlags`
  (needed for the `EDITABLE_FLAGS satisfies keyof FeatureFlags`).
- `messages/en.json` + `fr.json`: rename `workspaceTools*` → `aiPrompts*` and add
  the `clinician_prompts_note_only` flag label (en/fr parity).
- `config/page.tsx`: the read-only viewer rendered **every** feature_flags value
  as a `ToggleSwitch`, so `prompt_studio_roles` (a list) showed as "on". Branch
  on type — booleans render a toggle, the roles list renders as text.

No backend, no terraform — the flag round-trips through the existing
`update_feature_flags` save (FeatureFlagsResponse already has it; the prod
validator already accepts it).

## Verify
- `eslint` clean; `vitest` 342 pass (incl. i18n parity); `tsc` clean on the
  changed files.
- `/simplify` → `/code-review` → PR.
