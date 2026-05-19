# UI-P1 — Color tokens + literal sweep (Acceptance)

## Scope

Tokenize the 24 inline `Color(red: …)` callsites that share six
repeated RGB triples. The remaining ~30 literals are one-of-a-kind
decoration colors that don't yet justify a token; left in place.

## New tokens (`Theme.swift`)

| Token | RGB | Replaces | Used on |
|---|---|---|---|
| `aurionOnNavySecondary` | 183, 192, 214 | 7 sites | Labels/links on dark navy gradient (login, register) |
| `aurionMutedGray` | 154, 160, 172 | 5 sites | Secondary text on light bg (profile, dashboard, AurionUI internals) |
| `aurionInputBorder` | 198, 202, 210 | 3 sites | Unchecked option / checkbox borders |
| `aurionOnNavyError` | 255, 180, 180 | 3 sites | Soft error text on dark navy gradient |
| `aurionOnNavyFootnote` | 133, 144, 174 | 2 sites | Footer fine-print on dark navy gradient |

`Color(red: 74/255, green: 81/255, blue: 96/255)` (4 sites) is identical
to the existing `aurionStatusArchived` token — just point the callsites
at it; no new token needed.

## Out of scope

- Font modifiers — the existing `aurionTitle/aurionHeadline/aurionBody`
  family is hardcoded `.system(size:)` not Dynamic-Type-aware. Phase 5
  picks them up alongside the accessibility sweep.
- One-off RGB literals (single usage per shade). Leaving until they
  earn a token.

## Files touched

- `ios/Aurion/Aurion/App/Theme.swift` — add 5 tokens
- `ios/Aurion/Aurion/App/ContentView.swift` — login/register sweep (~14 sites)
- `ios/Aurion/Aurion/App/DashboardView.swift` — 1 site
- `ios/Aurion/Aurion/App/ProfileView.swift` — 1 site
- `ios/Aurion/Aurion/App/PhysicianProfileSetupView.swift` — 2 sites
- `ios/Aurion/Aurion/Capture/CaptureView.swift` — 1 site
- `ios/Aurion/Aurion/UI/AurionUI.swift` — 3 sites

## Acceptance

```bash
grep -rE 'Color\(red: (183|154|198|255|133)/255' \
  ios/Aurion/Aurion --include="*.swift" \
  | grep -v 'Theme.swift'
# → 0 hits (apart from the token definitions in Theme.swift)

xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPhone 17' build
xcodebuild -scheme Aurion -destination 'platform=iOS Simulator,name=iPad Pro 11-inch (M4)' build
```

## DRY / SOLID

- **DRY:** every repeating literal collapses to one definition.
- **OCP:** adding a new shade adds a token, no edits to existing call sites.
- **No behaviour change:** the rendered colors are byte-identical.
