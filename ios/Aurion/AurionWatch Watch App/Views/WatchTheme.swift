import SwiftUI

/// #65 — minimal Aurion brand tokens for the watch target, mirroring the
/// iOS `Theme.swift` gold/navy so the wrist reads as the same product.
/// (The per-physician accent from #418 is phone/portal-only for v1; the
/// watch uses brand gold.)
enum WatchTheme {
    static let gold = Color(red: 201 / 255, green: 168 / 255, blue: 76 / 255)   // #C9A84C
    static let goldLight = Color(red: 229 / 255, green: 208 / 255, blue: 130 / 255)
    static let recording = Color(red: 217 / 255, green: 53 / 255, blue: 43 / 255) // #D9352B
    static let paused = Color(red: 217 / 255, green: 148 / 255, blue: 31 / 255)   // #D9941F
}

/// Localized string for the watch target. Keys live in the AurionWatch
/// target's own `Localizable.strings`; ship EN + FR at parity before the
/// pilot (CLAUDE.md / premium-UI memory). Falls back to the key's English
/// default passed in `_ value` until the catalog is added.
func WL(_ key: String, _ value: String) -> String {
    NSLocalizedString(key, value: value, comment: "")
}
