import Foundation
import Combine

/// Carries an App Intent's request for "start a session of specialty X
/// with consultation type Y". Built from the same string identifiers
/// the dashboard's quick-start cards use, so the existing flow can
/// pick it up without a parallel pipeline.
struct PendingQuickStart: Hashable {
    let specialty: String
    let consultationType: String
}

/// Cross-cutting navigation bus that App Intents, Spotlight donations,
/// and deep-link handlers publish to. The app's main views observe
/// the published state and react.
///
/// Why a singleton + ``ObservableObject``: App Intents run in the app
/// process but outside the SwiftUI view tree — they can't reach
/// ``@EnvironmentObject`` directly. A ``@MainActor`` singleton is the
/// canonical bridge in Apple's own App Intents examples.
///
/// Consumers:
///   - ``DashboardView`` watches ``pendingQuickStart`` and triggers
///     the same encounter-type sheet flow a card tap would.
///   - ``MainTabView`` watches ``pendingTab`` and applies it to its
///     selection.
///   - ``ContentView`` watches ``pendingNoteSessionID`` and routes
///     into note review when a Spotlight result is tapped.
@MainActor
final class AppNavigation: ObservableObject {
    static let shared = AppNavigation()

    /// NSUserActivity type for an Aurion clinical session. Reverse-DNS
    /// of the bundle so Spotlight doesn't collide with another app's
    /// donations. Used by ``SessionNoteView`` to donate and by
    /// ``AurionApp.onContinueUserActivity`` to receive the deep-link.
    static let sessionActivityType = "app.aurion.clinical.session"

    @Published var pendingQuickStart: PendingQuickStart?
    @Published var pendingTab: MainTab?
    /// Set when a Spotlight result (or universal link) requests a
    /// specific session's note. The dashboard / inbox consumer is
    /// responsible for clearing it once the view has navigated.
    @Published var pendingNoteSessionID: String?

    private init() {}

    func requestQuickStart(specialty: String, consultationType: String) {
        pendingQuickStart = PendingQuickStart(
            specialty: specialty,
            consultationType: consultationType
        )
    }

    func requestTab(_ tab: MainTab) {
        pendingTab = tab
    }

    func requestNote(sessionID: String) {
        pendingNoteSessionID = sessionID
    }

    func clearPendingQuickStart() { pendingQuickStart = nil }
    func clearPendingTab() { pendingTab = nil }
    func clearPendingNote() { pendingNoteSessionID = nil }
}
