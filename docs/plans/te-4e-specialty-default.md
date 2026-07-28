# Plan — TE-4e · Specialty templates → profile default, out of the dropdowns

## Task
te-4e — Remove the flat 8-specialty `BUILT_IN_TEMPLATE_KEYS` list from the note-review
"Change template" dropdown and the visit-type context editor; offer only **"my specialty
default"** (resolved from `PhysicianProfile.primary_specialty`) + the clinician's **custom
templates**. Web-lane only, no backend change.

## Why
Backlog `.claude/state/backlog.md` (TE-4e), scope-locked by Uzziel 2026-07-20: *"specialty
templates should be associated to default profile, not part of a drop down … profile-default
wins EVERYWHERE, no forcing a specialty on upload — specialty is a profile property
(`primary_specialty`), period."* The pilot clinicians (Perry = plastic, Marie = ortho) each
have a stable specialty; it is a profile property, not a per-note choice. TE-4d (PR #670) already
made the *upload* flow take specialty from the profile with no picker; TE-4e finishes the same
rule on the two remaining specialty-picker dropdowns.

## Approach
Purely web. The profile is already served by `getMyProfile()` → `GET /api/v1/profile`
(`web/lib/portal-api.ts:65`) returning `primary_specialty` (`web/types/index.ts:1059`), and
`regenerateNote` already accepts `{ template_key }`. `primary_specialty` is constrained by the
profile editor to `orthopedic_surgery | plastic_surgery | musculoskeletal | emergency_medicine |
general` — every one a valid template key with a localized label in the existing `Specialties`
i18n namespace (`web/messages/{en,fr}.json:771`). So "my specialty default" resolves as: fetch
profile → `primary_specialty` is the option `value` (sent verbatim as `template_key`),
`tSpec(primary_specialty)` is its label. `BUILT_IN_TEMPLATE_KEYS` stays defined/exported (still
used by out-of-scope `VideoImportClient` + `VisitTypesTab`); TE-4e only stops the two named
surfaces from *rendering it as options*.

**Files to touch:**
1. `web/app/portal/notes/[id]/NoteReviewClient.tsx` — the "Change template" `<select>` (aria
   "Note template"). Remove the `BUILT_IN_TEMPLATE_KEYS` import + the now-dead
   `tTemplates = useTranslations("Profile.contexts.templates")`; add `getMyProfile` to the
   portal-api import + `tSpec = useTranslations("Specialties")`; add
   `const [mySpecialty, setMySpecialty] = useState<string|null>(null)` and fetch it in the
   existing mount effect (fail-soft `.catch`). Replace the 8-key built-in optgroup with a single
   `{mySpecialty && <option value={mySpecialty}>{t("toolbar.specialtyDefault",{specialty:tSpec(mySpecialty)})}</option>}`.
   Placeholder + custom optgroup + `onChange` unchanged (a non-`custom:` value →
   `doRegenerate({ template_key: v })`).
2. `web/components/portal/VisitTypeContextsEditor.tsx` — the `value=""` option is *already*
   "Use my specialty default" (`t("defaultTemplate")`). Delete `templateOptions` + its `.map`,
   delete `builtInKeySet` + the built-in branch of `selectTemplate` (reduces to: `""` → clear
   both pointers; a custom id → set `template_ref`, clear `template_key`). Keep the default
   option, custom optgroup, and stale-ref graceful placeholder. `BUILT_IN_TEMPLATE_KEYS` stays
   defined/exported. A context with a legacy built-in `template_key` now shows "Use my specialty
   default" and self-heals on next edit (exactly the scope-locked intent).
3. `web/messages/{en,fr}.json` — add `NoteReview.toolbar.specialtyDefault`
   (EN `"My specialty default ({specialty})"` / FR `"Ma spécialité par défaut ({specialty})"`),
   remove the now-orphan `NoteReview.toolbar.builtInGroup`, reword `Profile.contexts.description`
   ("pin each to a built-in template" → "…to one of your custom templates"). All mirrored EN+FR.

## Acceptance criteria
1. `NoteReviewPage.spec.tsx > "changing the template regenerates"` — with `getMyProfile` mocked to
   `primary_specialty:"orthopedic_surgery"`, selecting "My specialty default (Orthopedic Surgery)"
   (value `"orthopedic_surgery"`) still calls `regenerateNote("sess-1",{template_key:"orthopedic_surgery"})`.
2. New `NoteReviewPage.spec.tsx` case — `queryByRole("option",{name:/plastic surgery/i})` and
   `/family medicine/i` are `null`; `findByRole("option",{name:/my specialty default/i})` resolves.
3. `NoteReviewProgress.spec.tsx` stays green after adding `getMyProfile` to its mock (proves the
   added fetch doesn't crash the mount).
4. `VisitTypeContexts.spec.tsx` — the per-context select now has exactly `1` option
   ("Use my specialty default"); `queryByRole("option",{name:/orthopedic surgery/i})` is `null`.
5. `VisitTypeContexts.spec.tsx > "…Custom templates optgroup…"` — count assertion
   `1 + BUILT_IN_TEMPLATE_KEYS.length + CUSTOM_TEMPLATES.length` → `1 + CUSTOM_TEMPLATES.length`;
   custom "Knee Protocol" option still present.
6. `VisitTypeContexts.spec.tsx` empty-library case — count `1 + BUILT_IN_TEMPLATE_KEYS.length` → `1`.
7. `VisitTypeContexts.spec.tsx` mutual-exclusion + stale-ref tests stay green.
8. `VisitTypeContexts.spec.tsx > "has a localized name for every built-in template key"` stays
   green untouched (proves `BUILT_IN_TEMPLATE_KEYS` + `Profile.contexts.templates.*` preserved).
9. `i18n-bootstrap.spec.ts` EN/FR parity stays green (`specialtyDefault` added, `builtInGroup`
   removed in both).
10. `VisitTypesTab.spec.tsx` stays green **untouched** (out-of-scope TE-4f surface unaffected).
11. `npx next lint` exit 0 (no unused symbols) and `npm run build` exit 0.

**Required test edits (to keep the suite green):**
- `NoteReviewPage.spec.tsx` + `NoteReviewProgress.spec.tsx`: add `getMyProfile: vi.fn()` to the
  `vi.mock("@/lib/portal-api")` factory + import + `mockResolvedValue({primary_specialty:…})` in
  each `beforeEach`; in the regenerate test `await findByRole(option, /my specialty default/i)`
  before selecting.
- `VisitTypeContexts.spec.tsx`: apply the count/name changes (AC 4-6); delete the two obsolete
  built-in-selection tests (no built-in option exists to `selectOptions`). Keep the
  `BUILT_IN_TEMPLATE_KEYS` import (AC-8 loop).

## DRY / SOLID check
- **Reuse (grep-proven):** `getMyProfile()` (portal-api.ts:65, already used by VideoImportClient/
  VisitTypesTab); `listMyCustomTemplates()` (already fetched in NoteReviewClient); `Specialties`
  i18n via `useTranslations("Specialties")` (established pattern in dashboard/VideoImportClient);
  `Profile.contexts.defaultTemplate` reused verbatim; `humanSpecialty` unchanged.
- **New helper introduced?** No. Net new = one i18n key + one `useState` + one fetch line, minus
  one removed i18n key + two removed dead locals. `BUILT_IN_TEMPLATE_KEYS` stays the single source
  of truth for the surfaces still legitimately listing built-ins.
- **iOS UI task?** N/A (web).

## Out of scope
- Upload-flow specialty (TE-4d, PR #670 merged) — `VideoImportClient` already uses
  `profile.primary_specialty`; its `BUILT_IN_TEMPLATE_KEYS.includes(...)` label check left as-is.
- Templates → Visit Types tab (`VisitTypesTab.tsx`) — separate backlog item **TE-4f**.
- Backend / API / `regenerateNote` / template-resolution — none needed.
- iOS — none.
- Deleting/renaming `BUILT_IN_TEMPLATE_KEYS` or the `Profile.contexts.templates.*` catalog.
- Data migration of contexts carrying a legacy built-in `template_key` (they self-heal on edit).

## Test plan (executable)
1. `cd web && npx vitest run tests/NoteReviewPage.spec.tsx tests/NoteReviewProgress.spec.tsx tests/VisitTypeContexts.spec.tsx tests/VisitTypesTab.spec.tsx tests/i18n-bootstrap.spec.ts`
2. `cd web && npx vitest run` (full suite — the verify gate)
3. `cd web && npx next lint`
4. `cd web && npm run build`
5. Visual: (a) My Profile → visit-type context select shows only "Use my specialty default" +
   Custom templates; (b) `/portal/notes/[id]` "Change template" shows placeholder + "My specialty
   default (…)" + My templates, and selecting it regenerates; (c) FR locale reads
   "Ma spécialité par défaut (Chirurgie orthopédique)".

## Security implications
None. UI-only. `primary_specialty` is a fixed non-PHI enum; labels are static catalog strings; the
added `getMyProfile()` hits an endpoint the portal already calls (no new endpoint/data class,
nothing in URLs/query strings/logs). Custom-template `display_name`s already ride these render
paths today, unchanged. No AI prompts, no audit events, no auth/role change.
