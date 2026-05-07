# Aurion iOS UI Kit

Click-thru prototype of all 12 core screens from the brief, wired together so you can walk the physician's loop end-to-end.

## Files
- `index.html` — entry. Renders the `IOSDevice` frame with a top-bar nav to jump between screens.
- `ios-frame.jsx` — iOS device chrome (status bar, dynamic island, home indicator). Starter component.
- `components.jsx` — primitives: `GoldBtn`, `GhostBtn`, `Card`, `StatusBadge`, `Avatar`, `Logo`, `Hex`, `Icon`, `ProgressBar`, `Field`, `ListItem`, `AurionTabBar`, `AurionNavBar`, `BottomSheet`, color tokens (`AURION.*`).
- `screens.jsx` — screen components: `LoginScreen`, `ProfileSetupScreen`, `DashboardScreen`, `EncounterTypeScreen`, `PreEncounterScreen`, `CaptureScreen`, `PostEncounterScreen`, `NoteReadyScreen`, `NoteReviewScreen`, `SessionsScreen`, `ProfileTabScreen`, `DevicesScreen`.

## Flow
The default click-thru path follows the physician's core loop:

`Login → Profile Setup (5 steps) → Dashboard → Encounter Type → Pre-Encounter → Consent → Capture → Post-Encounter → Note Ready → Note Review → back to Dashboard`

Tabs (`Home` / `Sessions` / `Profile` / `Devices`) cross-link inside the prototype.

## Notes
- iPad split-view variants are not built; the brief is iPhone-first.
- All screens are **mocks** — text inputs accept input but state is local. Real data wiring is out of scope.
- Icons are Lucide-style inline SVGs (SF Symbols substitute). See root `README.md` → Iconography.
