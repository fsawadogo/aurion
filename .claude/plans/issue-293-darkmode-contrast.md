# Plan — issue-293 (dark-mode contrast sweep)

## Task
#293 — 19 verified dark-on-dark / invisible-text bugs in dark mode (and a few light-mode inverse-trap items). Root cause: brand-fixed `aurionNavy*` used as a foreground/border on adaptive surfaces (dark slate in dark mode).

## Why
Pilot physicians use dark mode; dark-navy text/controls on dark surfaces are invisible. All fixes are mechanical token swaps (fixed→adaptive, or fixed→fixed-light on navy surfaces) with NO behavior change. Ships in the held iOS TestFlight bundle.

## Approach
Component-first (clears the most sites), then screen-level swaps. Every change verified against the Theme.swift contract: adaptive = aurionBackground/Surface/SurfaceAlt/TextPrimary/TextSecondary/Border/InputBorder/MutedGray; brand-fixed-dark = aurionNavy*; fixed-light-on-navy = aurionOnNavy*.

### Component root causes (`UI/AurionUI.swift`)
- `AurionTextButton` default `var color = .aurionNavy` → `.aurionTextPrimary` (fixes Cancel/Back/Done nav buttons app-wide incl. DashboardView:537,711).
- `AurionField` unfocused stroke `.aurionNavy.opacity(0.18)` → `.aurionInputBorder` (keep gold focus ring).
- `AurionGhostButton` outline `.aurionNavy.opacity(0.18)` → `.aurionBorder`.
- `AurionBottomSheet` grabber `.aurionNavy.opacity(0.18)` → `.aurionMutedGray.opacity(0.5)`.

### Screen-level (dark)
- `Onboarding/VoiceRecordingView.swift` active sentence (204) + failed sentence (206) `.aurionNavy` → `.aurionTextPrimary`; circle indicator (254-256) active→`.aurionTextSecondary`, pending→`.aurionMutedGray`.
- `App/DashboardView.swift:647-650` team checkbox checkmark on gold fill: adaptive `.aurionTextPrimary` (→white in dark, washes on gold) → fixed `.aurionNavy` (navy-on-gold, matches Resume-pill convention).
- `Session/CodingSuggestionsCard.swift:473,482,485` E/M chip label/tint → mid-tone `.aurionBlue`.
- `Onboarding/OnboardingFlowView.swift:111-113` progress track → `.aurionBorder`.
- `Onboarding/WearableSetupView.swift:98-103` breathing-glow color → `.aurionGold` (mid-tone, reads in both modes).
- `NoteReview/CitationChip.swift` clip-badge letter on gold → `.aurionNavy`.
- `Export/ExportView.swift:236` progress track `aurionNavy.opacity(0.1)` → `.aurionSurfaceAlt`; halos (155,207) → `.aurionSurfaceAlt`.

### Screen-level (light-mode inverse trap — `Capture/LivePreviewOverlay.swift`, fixed-navy surface)
- Header title (99-102) → `.white`; version-meta + chevron (104-114) → `.aurionOnNavySecondary`; disclaimer + status strings (143-195) → `.aurionOnNavySecondary`. (Adaptive tokens render dark-in-light on the navy surface — must use fixed-light on-navy tokens, matching CaptureView.)

## Acceptance criteria
- [ ] AC-1: no `aurionNavy`/`aurionNavyLight`/`aurionNavyDark` remains as a FOREGROUND/border/track on an adaptive surface in the touched files (grep proof + diff review).
- [ ] AC-2: `AurionTextButton` default color is `.aurionTextPrimary` (adaptive) — nav-bar text buttons resolve light in dark mode.
- [ ] AC-3: app builds iPhone 17 + iPad Pro 11" (M4).
- [ ] AC-4: the 1 refuted false positive (`ContentView.swift:357-360`) is NOT touched (navy gradient + light text by design).

## DRY / SOLID check
- **Reuse**: existing Theme adaptive tokens; the `AurionFilterChip` fix at AurionUI.swift:455-458 is the precedent. No new tokens, no new components.
- **OCP**: fixing component defaults propagates the fix to all call sites (no per-site branching).
- **iOS UI — mobile-ios-design**: HIG contrast — interactive text/controls must meet contrast in both appearances; brand-fixed dark reserved for ON-light/ON-gold surfaces only.

## Out of scope
- Behavior changes; new components; the non-contrast audit issues (#294-#300). Pure color tokens.

## Test plan (executable)
1. `grep -rn "aurionNavy" <touched files>` → only legitimate background/on-gold/navy-surface uses remain.
2. `xcodebuild build -scheme Aurion -destination 'iPhone 17'` → BUILD SUCCEEDED (CI runs iPad too).
3. Manual: toggle Dark Appearance → Cancel/Back nav buttons, voice-enrollment active sentence, field outlines, export/onboarding progress tracks all visible.

## Security implications
None — pure presentation/color. No PHI/audit/secret/AI/consent path.
