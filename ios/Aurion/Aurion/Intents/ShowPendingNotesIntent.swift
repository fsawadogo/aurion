import AppIntents

/// "Hey Siri, show my pending Aurion notes" — opens the app and switches
/// the main tab bar to the Sessions inbox, where AWAITING_REVIEW rows
/// surface at the top. No params.
///
/// This is a navigation intent, not a data-returning one — the inbox is
/// physician-eyes-only (PHI in note titles), so we don't expose the list
/// via ``IntentResult``. Siri just opens the app to the right place.
struct ShowPendingNotesIntent: AppIntent {
    static var title: LocalizedStringResource = "Show Pending Notes"

    static var description: IntentDescription =
        "Open Aurion to your Sessions inbox so you can review notes awaiting sign-off."

    static var openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult {
        AppNavigation.shared.requestTab(.sessions)
        return .result()
    }
}
