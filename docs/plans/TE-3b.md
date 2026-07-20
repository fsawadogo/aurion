# Plan — TE-3b

## Task

TE-3b — expose `template_engine_enabled` on the admin Feature Flags page so the template engine can actually be switched on.

## Why

**TE-2 (#663) and TE-3 (#664) are merged and unreachable.** The flag they ship behind defaults to `False` and there is no way to change it from the portal, so the engine cannot be demoed, cannot be validated by Marie or Perry, and cannot complete the epic's rollout step 3 (*"flip the flag in dev via Admin → Feature Flags after the receipt is green"*).

My TE-3 plan asserted the admin page "renders flags generically." It does not — `web/app/portal/admin/feature-flags/page.tsx:40` is a hardcoded `FLAG_GROUPS` array, and the flag is absent from `web/types`, `messages/en.json` and `messages/fr.json`. Right now turning the engine on requires a hand-written AppConfig hosted-version.

Satisfies backlog `Cohort 7 · TE-3b`.

## Approach

**Add one entry to the allowlist. Do NOT make the page generic.**

That is the whole design decision, and it goes against the reflex to generalize. The hardcoding is deliberate, not debt: the page docstring (`page.tsx:15-19`) states that every other flag in `FeatureFlagsConfig` — screen capture, note versioning, the video-vision gates, `prompt_studio_roles` — is read-only here because it is *"tied to deeper pipeline behavior or not a simple boolean."* `FLAG_GROUPS` is a curated **allowlist of flags that are safe to flip from a web form**, not an incomplete rendering of the config. Making it generic would surface pipeline gates as innocuous toggles and would render `prompt_studio_roles` (a list) as a broken switch.

So: four edits, mirroring `grounded_synthesis_enabled` exactly.

1. **`web/types/index.ts`** — add `template_engine_enabled: boolean;` to `FeatureFlags`.
2. **`page.tsx` `FLAG_GROUPS`** — a new group after `groundedSynthesis` (both gate note-generation behaviour, so they read together).
3. **`messages/en.json`** — group `title` + `hint`, and the flag's `name` + `description`.
4. **`messages/fr.json`** — the same keys in French.

**Copy carries the warning.** `grounded_synthesis_enabled` sets the precedent — *"Leave OFF until clinical + regulatory sign-off."* The template engine is likewise unproven: TE-3 established only that flag-OFF is byte-identical and that hostile templates cannot break out. Nothing has yet measured whether notes get *better*. The description must say the eval receipt is outstanding, so an admin flipping it knows what they are opting into.

## The one real gap, and the cheap fix

Adding a backend flag needs four coordinated web edits and **nothing enforces it**. A group added without its strings does not crash — `next-intl` resolves a missing key to the key path, so the card would ship reading `FeatureFlags.templateEngine` in the UI. The EN↔FR parity test (`tests/i18n-bootstrap.spec.ts`) catches EN-only drift but not *neither*-catalog drift.

Fix is a test, not an abstraction: assert every flag and group key in `FLAG_GROUPS` resolves in **both** catalogs. That closes the drift class for this page and for every future flag, without touching the allowlist design.

## Acceptance criteria

- [ ] **AC-1:** an ADMIN sees a Template engine toggle on `/portal/admin/feature-flags` reflecting the loaded value — `tests/FeatureFlagsPage.spec.tsx::renders the template engine toggle`
- [ ] **AC-2:** toggling it and saving PUTs `template_engine_enabled: true` and leaves every other flag untouched — `::saves the template engine flag without disturbing others`
- [ ] **AC-3:** every flag + group key in `FLAG_GROUPS` resolves in **both** en and fr — `::every FLAG_GROUPS key exists in both catalogs`
- [ ] **AC-4:** the description warns the engine is unproven / eval receipt outstanding — asserted in AC-1's copy check
- [ ] **AC-5:** `npm run lint` clean, `npx vitest run` green, `npm run build` succeeds

## DRY / SOLID check

- **Existing helpers reused:** `FLAG_GROUPS` / `EDITABLE_FLAGS` / `ToggleSwitch` / `toggle()` / `save()` — all of it already generic over `keyof FeatureFlags`; this adds data, not code. `getFeatureFlags` / `updateFeatureFlags` unchanged.
- **New helper introduced?** None in `app/`. One new spec file.
- **OCP:** the page is already open for extension via `FLAG_GROUPS` — the change is a data addition, exactly as intended by that design.
- **iOS UI task?** No. Zero iOS diff expected.

## Out of scope

- **Making the page generic** — see above; the allowlist is the design.
- **Flipping the flag.** This slice ships the switch, not the decision. The epic gates the flip on an eval receipt in `docs/sign-off/`, which does not exist yet.
- **The eval receipt itself** — separate task; it needs TE-4 to be meaningful, since TE-3 alone still pastes frame captions verbatim.
- **TE-1's detail-level control** — different rail, different slice.

## Test plan (executable)

1. `cd web && npx vitest run tests/FeatureFlagsPage.spec.tsx`
2. `cd web && npx vitest run` → full suite green
3. `cd web && npm run lint` → clean
4. `cd web && npm run build` → static export succeeds
5. `git diff --stat main...HEAD -- ios/ backend/` → empty

## Security implications

- **ADMIN-only, unchanged.** The page is role-gated in the Sidebar and the backend `POST /admin/feature-flags` is `require_role(ADMIN)`. This adds no new endpoint and no new permission.
- **The flag it exposes changes AI prompt composition.** That is the point, and it is why the copy must state the engine is unproven rather than reading like a neutral feature switch.
- **No PHI.** Feature flags are configuration; no patient data is involved on this page.
- **Descriptive mode is unaffected.** TE-3's guidance is screened by `validate_vision_guidance` regardless of this flag; turning the engine on does not relax any safety boundary.
