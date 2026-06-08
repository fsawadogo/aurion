import Foundation

/// Reads the marketing version + build number from the app bundle and formats
/// the discreet "Version X (build Y)" label shown on the Profile and Login
/// footers. Kept pure (no SwiftUI) so the formatting can be unit-tested
/// without spinning up a view or reaching into the live `Bundle.main`.
enum AppVersion {

    /// `CFBundleShortVersionString` — the user-facing marketing version
    /// (e.g. "1.0"). Falls back to a single dash when the key is absent so
    /// the label never renders the literal "(null)".
    static var short: String {
        (Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String) ?? "\u{2014}"
    }

    /// `CFBundleVersion` — the monotonically-incrementing build number
    /// (e.g. "42"). Same dash fallback as ``short``.
    static var build: String {
        (Bundle.main.infoDictionary?["CFBundleVersion"] as? String) ?? "\u{2014}"
    }

    /// Localized "Version X (build Y)" string for the live bundle.
    static var displayLabel: String {
        label(short: short, build: build)
    }

    /// Pure formatter — takes the two raw bundle values and produces the
    /// localized label. Exposed (rather than inlined into ``displayLabel``)
    /// so tests can pin the format without depending on the bundle's actual
    /// version, which changes every release.
    static func label(short: String, build: String) -> String {
        L("version.label", short, build)
    }
}
