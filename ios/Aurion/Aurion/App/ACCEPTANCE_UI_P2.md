# UI-P2 — Navigation modernization (Acceptance)

## Goal

Modernize the main tab navigation to use Apple's native ``TabView``
with the iOS 18 ``Tab`` API and ``.tabViewStyle(.sidebarAdaptable)``,
so iPad in regular size class automatically gets a native sidebar
without us hand-rolling one.

## What changes

- **MainTabView** — replace the custom switch+`AurionTabBar`
  body with a native `TabView`. iOS 26 renders its background with
  Liquid Glass / translucent material automatically. We provide brand
  via `.tint(.aurionGold)` so the active tab still reads gold.
- **`MainTab` enum** — new `Hashable` route enum
  (`.home | .sessions | .profile | .devices`) replacing the string
  selection. Type-safe; one source of truth for tab identity.
- **ProfileView** — wrap its `List` in a `NavigationStack` so its
  `.navigationTitle("Profile")` actually renders.
- **`AurionTabBar`** stays in the codebase for now — it's still a
  reasonable component if a future surface (admin portal panel,
  modal nav) wants the brand-styled bar.

## Out of scope

- **ContentView's `uiState` dispatch** stays as-is. It's a wizard
  flow (splash → auth → onboarding → setup → capture-or-modal), not
  a navigation stack. Forcing `NavigationStack` would break the
  existing `AurionTransition.fadeSlide` choreography for no gain.
- **NavigationSplitView for sessions list ↔ detail.** Defer to a
  follow-up — needs binding plumbing through `SessionManager` and
  doesn't show benefits unless paired with the search/filter UX
  from Phase 3.

## Files

- `App/MainTabView.swift` — rewrite (~30 lines)
- `App/ProfileView.swift` — wrap body in NavigationStack
- `App/ACCEPTANCE_UI_P2.md` — this file

## Acceptance

```bash
xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build
xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M4)' build
```

Smoke flow:
- iPhone — bottom tab bar with translucent material, gold active tab.
- iPad portrait — same.
- iPad landscape — left sidebar with the four tabs; selected tab's
  destination renders in the detail column.

## DRY / SOLID

- **DRY:** native TabView + `Tab` API means we don't maintain custom
  tab-bar layout code per platform.
- **SRP:** `MainTabView` only routes; brand styling via `.tint()`.
- **DIP:** the tab-content closures depend on `DashboardView`,
  `SessionsInboxView`, etc. — abstractions, not concrete bar layout.

## Risk + mitigation

- **Visual change.** The custom `AurionTabBar` had gold-tinted icons
  + 10pt labels. Native TabView uses system sizes (~22pt icons,
  ~10pt labels). Close enough; `.tint(.aurionGold)` preserves brand.
- **Selection persistence.** `MainTab` enum is `RawRepresentable`
  with String values matching the prior `selection: String`
  identifiers — no migration needed.
