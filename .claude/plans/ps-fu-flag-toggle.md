# ps-fu — Prompt Studio flag toggle + "not enabled" state

Follow-up to the #524 MVP. After ps-06 shipped, the Studio page renders but
the API 403s because `prompt_studio_enabled` ships dark and **there is no way
to turn it on from the portal** — the admin Feature Flags page can't toggle it,
and the page shows a misleading "you don't have permission" 403.

## Problem

1. **The flag isn't writable from the portal.** ps-05 added
   `prompt_studio_enabled` + `prompt_studio_roles` to `FeatureFlagsConfig`
   (the AppConfig schema) but **not** to the admin `FeatureFlagsResponse`
   (the GET/POST model the portal binds to). Consequences:
   - GET `/admin/feature-flags` never returns the flag → the page can't show it.
   - POST does `FeatureFlagsConfig.model_validate(body.model_dump())`; since the
     two fields are absent from the body, **every save silently resets them to
     defaults** (`prompt_studio_enabled=False`, `prompt_studio_roles=["ADMIN"]`).
     So even if an operator enabled it in AWS, the next portal flag save would
     turn Prompt Studio back off. This breaks the "Mirrors `FeatureFlagsConfig`
     field-for-field" invariant the response model's own docstring claims.
2. **Misleading 403 copy.** The Studio page's docstring already promises a
   "not enabled" state on 403, but `load()` just renders the generic
   `humanizeError` ("You don't have permission to view this") — reads like a
   role denial when it's actually the feature being off.

## Changes

### Backend
- `app/api/v1/admin/feature_flags.py`
  - Add `prompt_studio_enabled: bool` + `prompt_studio_roles: list[str]` to
    `FeatureFlagsResponse` (restores the field-for-field mirror).
  - Set both in `_build_response` (copy the roles list, don't alias config).
- `tests/unit/test_feature_flags_admin.py`
  - Extend `_all_flags_response` base dict with the two new fields (defaults).
  - Add a GET test asserting the flag round-trips (mirrors the video-vision
    master-flag test).

### Web
- `types/index.ts` — add `prompt_studio_enabled: boolean` to `FeatureFlags`
  (needed so it's a `keyof FeatureFlags` for the editable-flag list).
- `app/portal/admin/feature-flags/page.tsx` — generalize the single hard-coded
  "Note-review cards (iOS)" section into **flag groups** so the Studio toggle
  lands under its own "Workspace tools" heading instead of being mislabeled an
  iOS card. `EDITABLE_FLAGS` derives from the groups; save/diff logic unchanged.
- `app/portal/admin/prompt-studio/page.tsx` — catch `ApiError` 403 in `load()`,
  set a `disabled` state, render the promised "not enabled — turn it on in
  Feature Flags" card, and hide the Create button while disabled.
- `messages/{en,fr}.json` — `FeatureFlags.workspaceTools(+Hint)` +
  `FeatureFlags.flags.prompt_studio_enabled.{name,description}`;
  `AdminPromptStudio.notEnabledTitle/Body`. Full en/fr parity.
- `tests/PromptStudioPage.spec.tsx` — add a 403 → not-enabled-state case.

## Out of scope
- `prompt_studio_roles` stays config-only (a list, not a boolean toggle) — it
  round-trips through the response so portal saves no longer wipe it, but the UI
  doesn't edit it.
- The web `FeatureFlags` type is already missing three unrelated backend flags
  (`clip_video_interpretation_enabled`, `frame_by_frame_video_enabled`,
  `media_review_retention_enabled`) — pre-existing drift that round-trips at
  runtime; full type sync is a separate cleanup.

## Verify
- Backend: `ruff check` + `pytest tests/unit/test_feature_flags_admin.py`.
- Web: `eslint` + `vitest` (FeatureFlags + PromptStudio specs, i18n parity).
- `/simplify` (no P1) → `/code-review` → `/open-pr`.
