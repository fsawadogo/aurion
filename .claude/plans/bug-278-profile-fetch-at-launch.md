# Plan — bug-278

## Task
#278 — Quick Start silently falls back to two GENERAL cards (New Patient / Follow-up), losing the physician's real specialty + visit types, whenever `physicianProfile` is nil — which is every fresh app process, because the profile is never fetched at launch.

## Why
`DashboardView.quickStartCards` derives from `appState.physicianProfile` with `?? "general"` / `?? ["new_patient","follow_up"]`. `physicianProfile` is only populated when the Profile tab is opened (or after a profile/team save) — nothing fetches it on cold launch or fresh login. So any fresh process (incl. the relaunch after the stuck-95% screen, which is how this surfaced) shows GENERAL cards. Worse: tapping a fallback card starts a `general`-template session for an orthopedic surgeon — a silent hit to `template_section_completeness` (a headline pilot metric). PR #266 custom visit types vanish under the same fallback.

## Approach
Three layers (investigation-recommended):
1. **Eager fetch** — `AurionApp`'s post-auth `.task(id: isAuthenticated)`: after `remoteConfig.refresh()`, `if appState.physicianProfile == nil { appState.physicianProfile = try? await APIClient.shared.getProfile() }`. Fixes cold launch + the Siri/widget deep-link fallback (`AurionApp.swift:152-154`) in one place.
2. **Defensive re-fetch** — `DashboardView.task` loads the profile when nil (alongside `loadRecentSessions`), so a transient launch-fetch failure self-heals on tab-return / pull-to-refresh.
3. **No misleading defaults** — extract derivation to `static func quickStartCards(for:)` returning `[]` when profile is nil; `quickStartSection` renders shimmer skeleton cards while nil instead of GENERAL placeholders. The `["new_patient","follow_up"]` default is kept ONLY when a profile exists but has empty `consultationTypes` (a real "use defaults" case) — and even then with the profile's real specialty, never "general".

Files: `ios/Aurion/Aurion/App/AurionApp.swift`, `App/DashboardView.swift`, new `AurionTests/DashboardQuickStartTests.swift`.

## Acceptance criteria
- [ ] AC-1: `DashboardView.quickStartCards(for: nil) == []` (no GENERAL fallback when profile missing) — `DashboardQuickStartTests.nilProfileYieldsNoCards`.
- [ ] AC-2: an orthopedic profile with `["new_patient","follow_up"]` → 2 cards, all `specialty == "orthopedic_surgery"` (never "general") — `...orthoProfileKeepsSpecialty`.
- [ ] AC-3: a profile with empty `consultationTypes` → 2 default-type cards but with the profile's real specialty, not "general" — `...emptyTypesUsesRealSpecialty`.
- [ ] AC-4: a profile with a PR-#266 custom visit type → a card carrying that type (custom types survive) — `...customVisitTypePreserved`.
- [ ] AC-5: app builds iPhone 17 + iPad Pro 11" (M4) — CI.

## DRY / SOLID check
- **Existing helpers to reuse**: `APIClient.shared.getProfile()` (existing), `appState.physicianProfile`, `AurionSkeleton` (existing shimmer component used by `SessionsInboxView`), `localizedSpecialty`/`localizedConsultationType` (global). No new network or helper.
- **New helper introduced?**: One — extracting the card derivation to `static quickStartCards(for:)`. Justified: SRP (pull non-trivial mapping out of the view) + creates the testability boundary that locks the fix. Not a duplicate.
- **iOS UI only — mobile-ios-design**: consulted. HIG pattern: show a loading placeholder (skeleton) for content pending a fetch rather than fabricating wrong defaults; reuse the app's existing `AurionSkeleton` shimmer for visual consistency with the inbox.

## Out of scope
- Caching the last-known profile to disk for offline cold launch (note as follow-up).
- The deep-link/Siri inline fallback line itself (`?? "general"`) is left as a last-resort; the eager fetch makes profile non-nil before it runs.

## Test plan (executable)
1. `xcodebuild test -scheme Aurion -destination 'iPhone 17' -only-testing:AurionTests/DashboardQuickStartTests` → green.
2. CI build matrix.

## Security implications
The profile contains the physician's own display name + preferences — no patient PHI. `getProfile()` is an authenticated GET (existing endpoint, bearer token). No audit/secret/AI/consent path touched. `try?` swallows fetch errors into the existing nil-profile (skeleton) state — no error surface added.
