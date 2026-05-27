import Foundation

/// Lightweight runtime localization.
/// Stores the active bundle for the selected language. Updated when AppState.appLanguage changes.
enum Localization {
    private(set) nonisolated(unsafe) static var bundle: Bundle = loadBundle(for: "en")
    /// Two-letter code of the active language ("en" / "fr"). Drives both the
    /// number-formatting locale used by `String(format:)` and the plural rule
    /// in ``Lplural`` — keeping those in step with the selected UI language
    /// rather than the device region.
    private(set) nonisolated(unsafe) static var languageCode: String = "en"
    /// Locale matching the selected language, used so `%d`/`%f` formatting
    /// (grouping separators, decimal marks) follows the UI language.
    static var locale: Locale { Locale(identifier: languageCode) }

    static func setLanguage(_ code: String) {
        bundle = loadBundle(for: code)
        languageCode = code
    }

    private static func loadBundle(for code: String) -> Bundle {
        guard let path = Bundle.main.path(forResource: code, ofType: "lproj"),
              let b = Bundle(path: path) else {
            return Bundle.main
        }
        return b
    }
}

/// Shorthand: `L("dashboard.greeting.morning")`
func L(_ key: String) -> String {
    Localization.bundle.localizedString(forKey: key, value: key, table: nil)
}

/// Format variant: `L("setup.step", 2, 5)` → "Step 2 of 5".
/// Looks up the localized format string, then substitutes the arguments.
/// Formats with the *selected language's* locale (not `Locale.current`) so a
/// French UI on an en-region device still groups large numbers the French way.
func L(_ key: String, _ args: CVarArg...) -> String {
    String(format: Localization.bundle.localizedString(forKey: key, value: key, table: nil),
           locale: Localization.locale,
           arguments: args)
}

/// Plural-aware lookup. Appends `.one`/`.many` to `base` and substitutes
/// `count`. Centralizes the singular/plural rule so it stays consistent and
/// language-correct: English treats only 1 as singular ("0 frames"), while
/// French (CLDR `one` covers 0 and 1) treats 0 as singular too ("0 image").
func Lplural(_ base: String, _ count: Int) -> String {
    let isSingular = Localization.languageCode == "fr" ? (count <= 1) : (count == 1)
    return L(isSingular ? "\(base).one" : "\(base).many", count)
}
