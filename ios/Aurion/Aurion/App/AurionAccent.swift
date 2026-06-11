import SwiftUI

/// #418 — physician accent color for the iOS app chrome.
///
/// The five keys mirror the backend `_ACCENT_PALETTE` validator and the
/// web portal (`web/lib/accent.ts` / `globals.css`) 1:1, so a clinician's
/// chosen color reads the same on phone and portal. "gold" is the product
/// default; its values are byte-identical to the brand gold the app has
/// always shipped, so a default user's UI is unchanged.
///
/// The Theme gold tokens (`Color.aurionGold` / `Light` / `Dark` / `Bg` and
/// the gold gradients) read `AurionAccent.current`, so selecting an accent
/// recolors every gold-token surface at once — the iOS equivalent of the
/// portal's CSS-variable swap. Compliance surfaces (CONFLICTS amber,
/// masking, audit navy, semantic red/green/blue) use separate tokens and
/// are deliberately NOT routed through the accent.
enum AurionAccent: String, CaseIterable, Identifiable {
    case gold, teal, indigo, rose, slate

    var id: String { rawValue }

    /// 500-step base — the primary accent (buttons, active rails, icons).
    var base: Color {
        switch self {
        case .gold:   return Color(red: 201/255, green: 168/255, blue: 76/255)   // #C9A84C
        case .teal:   return Color(red: 20/255,  green: 184/255, blue: 166/255)  // #14B8A6
        case .indigo: return Color(red: 99/255,  green: 102/255, blue: 241/255)  // #6366F1
        case .rose:   return Color(red: 244/255, green: 63/255,  blue: 94/255)   // #F43F5E
        case .slate:  return Color(red: 100/255, green: 116/255, blue: 139/255)  // #64748B
        }
    }

    /// 300-step light — gradient top / highlight.
    var light: Color {
        switch self {
        case .gold:   return Color(red: 229/255, green: 208/255, blue: 130/255)  // #E5D082
        case .teal:   return Color(red: 94/255,  green: 234/255, blue: 212/255)  // #5EEAD4
        case .indigo: return Color(red: 165/255, green: 180/255, blue: 252/255)  // #A5B4FC
        case .rose:   return Color(red: 253/255, green: 164/255, blue: 175/255)  // #FDA4AF
        case .slate:  return Color(red: 203/255, green: 213/255, blue: 225/255)  // #CBD5E1
        }
    }

    /// 600-step dark — gradient bottom / pressed.
    var dark: Color {
        switch self {
        case .gold:   return Color(red: 181/255, green: 149/255, blue: 61/255)   // #B5953D
        case .teal:   return Color(red: 13/255,  green: 148/255, blue: 136/255)  // #0D9488
        case .indigo: return Color(red: 79/255,  green: 70/255,  blue: 229/255)  // #4F46E5
        case .rose:   return Color(red: 225/255, green: 29/255,  blue: 72/255)   // #E11D48
        case .slate:  return Color(red: 71/255,  green: 85/255,  blue: 105/255)  // #475569
        }
    }

    /// Soft adaptive card background (the "warmer/cooler than canvas"
    /// accent-card surface). Gold keeps its EXACT legacy cream/slate so the
    /// default user's cards render byte-identical; the others use analogous
    /// light/dark hue tints.
    var softBg: Color {
        switch self {
        case .gold:
            return Color(
                light: Color(red: 251/255, green: 246/255, blue: 230/255),  // #FBF6E6 (legacy)
                dark:  Color(red: 44/255,  green: 38/255,  blue: 26/255)    // #2C261A (legacy)
            )
        case .teal:
            return Color(
                light: Color(red: 224/255, green: 250/255, blue: 246/255),
                dark:  Color(red: 18/255,  green: 44/255,  blue: 41/255)
            )
        case .indigo:
            return Color(
                light: Color(red: 233/255, green: 235/255, blue: 253/255),
                dark:  Color(red: 27/255,  green: 28/255,  blue: 48/255)
            )
        case .rose:
            return Color(
                light: Color(red: 253/255, green: 232/255, blue: 235/255),
                dark:  Color(red: 48/255,  green: 28/255,  blue: 32/255)
            )
        case .slate:
            return Color(
                light: Color(red: 237/255, green: 240/255, blue: 245/255),
                dark:  Color(red: 32/255,  green: 36/255,  blue: 42/255)
            )
        }
    }

    /// Parse a stored/backend value, falling back to the gold default for
    /// nil or any out-of-palette string (defensive — the backend validates
    /// on write, but a stale cache shouldn't paint a broken theme).
    static func from(_ raw: String?) -> AurionAccent {
        guard let raw, let accent = AurionAccent(rawValue: raw) else { return .gold }
        return accent
    }

    // MARK: - Current selection (single source for the Theme tokens)

    /// UserDefaults key holding the selected accent rawValue. Written by
    /// `AppState.accentColor`; read here so the nonisolated Theme color
    /// getters resolve without touching `@MainActor` state.
    static let defaultsKey = "aurion.accent_color"

    /// The accent the Theme tokens resolve against right now. Reads the
    /// persisted preference (UserDefaults is in-memory cached, so this is
    /// cheap even on a hot render path). Defaults to gold.
    static var current: AurionAccent {
        from(UserDefaults.standard.string(forKey: defaultsKey))
    }
}
