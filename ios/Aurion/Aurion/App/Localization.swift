import Foundation

/// Lightweight runtime localization.
/// Stores the active bundle for the selected language. Updated when AppState.appLanguage changes.
enum Localization {
    private(set) nonisolated(unsafe) static var bundle: Bundle = loadBundle(for: "en")

    static func setLanguage(_ code: String) {
        bundle = loadBundle(for: code)
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
