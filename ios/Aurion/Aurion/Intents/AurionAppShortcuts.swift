import AppIntents

/// Registers Aurion's App Intents with the system so they surface in:
/// - Siri ("Hey Siri, start an Aurion orthopedic session")
/// - Shortcuts app (as suggested + manual shortcuts)
/// - Spotlight search ("aurion start session")
/// - The Action button on iPhone 15 Pro+ (user-assignable)
///
/// iOS reads this provider at install time and on every Bundle update.
/// No `Info.plist` changes needed — the type conformance is the only
/// registration point.
struct AurionAppShortcuts: AppShortcutsProvider {
    /// Tint the shortcut chip in Siri / Spotlight to match the brand.
    /// Maps to the system-defined ``ShortcutTileColor`` palette (not the
    /// app's `aurionGold` token — Apple controls the available choices).
    static var shortcutTileColor: ShortcutTileColor = .yellow

    @AppShortcutsBuilder
    static var appShortcuts: [AppShortcut] {
        // App Intents requires every utterance to embed `\(.applicationName)`
        // exactly once — Siri uses it as the speakable anchor that
        // disambiguates the request across installed apps.
        AppShortcut(
            intent: StartSessionIntent(),
            phrases: [
                "Start an \(.applicationName) session",
                "Start a session with \(.applicationName)",
                "Begin recording with \(.applicationName)",
            ],
            shortTitle: "Start Session",
            systemImageName: "record.circle"
        )

        AppShortcut(
            intent: ShowPendingNotesIntent(),
            phrases: [
                "Show my pending \(.applicationName) notes",
                "Open pending notes in \(.applicationName)",
                "Review my \(.applicationName) notes",
            ],
            shortTitle: "Pending Notes",
            systemImageName: "list.bullet.rectangle"
        )
    }
}
