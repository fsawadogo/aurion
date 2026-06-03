import Combine
import Foundation
import SwiftUI

/// Backing data model shared by `PriorEncountersRail` and
/// `PriorEncountersListView` (#61, full slice).
///
/// Both surfaces show the same data (sessions sharing a patient
/// identifier) — the rail caps at five for a horizontal preview, the
/// list view shows the full sorted set. Extracting the data plumbing
/// here gives us a single place that owns:
///
///   * the fetcher closure (test seam)
///   * the current/PURGED filter rule
///   * the newest-first sort
///   * the loading / failure flags
///   * the `displayMatches` and `totalRelevant` derivations
///
/// DRY (§6c): one model, two views. SRP: the model owns data; the views
/// own visual presentation. The test surface drives the model directly,
/// which side-steps the SwiftUI `@State`-on-unmounted-view storage
/// pitfall (state vanishes on a non-rendered view value, but
/// `ObservableObject` keeps its own reference-typed storage).
///
/// ## Privacy
///
/// `identifier` IS PHI. It is held in memory only for as long as the
/// model is alive (one screen). It is NEVER logged, NEVER passed to
/// `AuditLogger.log(extra:)`, NEVER included in an error message that
/// could surface in a crash report. The PHI test in
/// `PriorEncountersTests` greps this file and both view files for the
/// banned logging primitives.
@MainActor
final class PriorEncountersModel: ObservableObject {

    // MARK: - Inputs

    /// Session currently being reviewed — excluded from `displayMatches`
    /// since we're already on that session's note.
    let currentSessionId: String

    /// Patient identifier the lookup is filtered to. Required so the
    /// fetch URL has the right path component.
    let identifier: String

    /// Fetcher closure — defaults to the real API client; tests inject
    /// canned data / failures via this seam.
    let fetch: (String) async throws -> [PatientSessionMatch]

    // MARK: - Published state

    /// Raw list from the API after sort. Filter happens at the
    /// derivation layer below so callers can choose the cap (rail = 5,
    /// list = none).
    @Published private(set) var matches: [PatientSessionMatch] = []

    /// True between `load()` start and end. Drives the skeleton state on
    /// the rail and the ProgressView on the list view.
    @Published private(set) var isLoading: Bool = true

    /// True if the most recent `load()` threw. Drives the retry block.
    /// Reset to false on a successful subsequent load.
    @Published private(set) var loadFailed: Bool = false

    // MARK: - Constants

    /// Rail cap. Matches the UX sweet spot for a horizontal scroll on
    /// iPhone (~ three cards on a 6.1" display + a hint of the next).
    /// The list view does NOT cap.
    static let maxRailCards = 5

    // MARK: - Init

    init(
        currentSessionId: String,
        identifier: String,
        fetch: @escaping (String) async throws -> [PatientSessionMatch] = {
            try await APIClient.shared.listMySessionsByPatientIdentifier($0)
        }
    ) {
        self.currentSessionId = currentSessionId
        self.identifier = identifier
        self.fetch = fetch
    }

    // MARK: - Derivations

    /// "Relevant" prior encounters — drop the current session id and any
    /// PURGED row, sort newest-first. Same rule applies to both surfaces.
    var relevantMatches: [PatientSessionMatch] {
        matches.filter {
            $0.sessionId != currentSessionId && $0.state != "PURGED"
        }
    }

    /// Capped at five — what the rail renders. Newest-first comes from
    /// the source `matches` list (sorted in `load`).
    var railMatches: [PatientSessionMatch] {
        Array(relevantMatches.prefix(Self.maxRailCards))
    }

    /// Filtered total. Drives the "See all (N)" gate (visible iff
    /// `totalRelevant > maxRailCards`) and the same label.
    var totalRelevant: Int {
        relevantMatches.count
    }

    // MARK: - Loader

    /// Refresh the list. Sets `isLoading` true for the duration; on
    /// success overwrites `matches` with the newest-first sort; on
    /// failure flips `loadFailed` and clears the list.
    ///
    /// PHI guard: the underlying error is NEVER surfaced verbatim. We
    /// drop it on the floor and let the retry block render generic
    /// copy. `error.localizedDescription` would echo the request URL,
    /// which carries the identifier — bypassing that path entirely
    /// keeps the identifier off any crash log / error reporter.
    func load() async {
        isLoading = true
        do {
            let result = try await fetch(identifier)
            // Newest first — backend already sorts this way, but we
            // re-sort on the client to be defensive against a future
            // reordering that would break the UX without a backend
            // version bump.
            matches = result.sorted { $0.createdAt > $1.createdAt }
            loadFailed = false
        } catch {
            loadFailed = true
            matches = []
        }
        isLoading = false
    }
}
