import SwiftUI

/// Full-screen list of every prior encounter for a given patient
/// identifier (#61, full slice).
///
/// Reached from the rail's "See all (N)" link on `NoteReviewView`.
/// Same data source as the rail — calls
/// `APIClient.listMySessionsByPatientIdentifier` (DRY gate, see
/// `PriorEncountersTests`). No 5-cap; renders the full sorted list.
///
/// ## Behaviour
///
/// * pull-to-refresh
/// * Retry block on failure (same pattern as the rail / PatientSummaryCard)
/// * tap a row → navigates to that session (same AppNavigation event
///   path as the rail and the dashboard recent strip)
///
/// ## Privacy
///
/// The identifier renders in the navigation title verbatim (the
/// physician needs to see WHICH patient's list they're looking at).
/// It is NEVER logged or echoed in error messages. The PHI test in
/// `PriorEncountersTests` enforces this contract on this file too.
struct PriorEncountersListView: View {
    let currentSessionId: String
    let identifier: String

    /// Test seam — same shape as `PriorEncountersRail.fetch`. The
    /// production caller passes `nil` and gets the real APIClient.
    var fetch: (String) async throws -> [PatientSessionMatch] = {
        try await APIClient.shared.listMySessionsByPatientIdentifier($0)
    }

    /// Invoked when the user taps a row — default routes through the
    /// shared AppNavigation router so the inbox stack handles the
    /// push (no new routing layer per §6c OCP).
    var onTap: (String) -> Void = { sessionId in
        AppNavigation.shared.requestNote(sessionID: sessionId)
        AppNavigation.shared.requestTab(.sessions)
    }

    /// Sheet dismiss handle — when nil, the sheet stays open after a
    /// tap (useful for tests). The production caller (NoteReviewView)
    /// passes `\.dismiss` so picking a session closes the list and the
    /// inbox push happens behind it.
    @Environment(\.dismiss) private var dismiss

    @State private var matches: [PatientSessionMatch] = []
    @State private var isLoading = true
    @State private var loadFailed = false

    /// Display list — filters to "relevant" prior encounters using the
    /// same rule as the rail (drop current session id + PURGED). Sorted
    /// newest first.
    var displayMatches: [PatientSessionMatch] {
        matches
            .filter { $0.sessionId != currentSessionId && $0.state != "PURGED" }
            .sorted { $0.createdAt > $1.createdAt }
    }

    var body: some View {
        NavigationStack {
            Group {
                if isLoading && matches.isEmpty {
                    loadingState
                } else if loadFailed && matches.isEmpty {
                    retryState
                } else if displayMatches.isEmpty {
                    emptyState
                } else {
                    list
                }
            }
            .navigationTitle(L("priorEncounters.fullList.title", identifier))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("common.done")) { dismiss() }
                }
            }
            .background(Color.aurionBackground)
        }
        .task(id: identifier) {
            await load()
        }
    }

    // MARK: - States

    private var loadingState: some View {
        VStack {
            ProgressView()
            Spacer()
        }
        .frame(maxWidth: .infinity)
        .padding(.top, 32)
    }

    private var emptyState: some View {
        VStack(spacing: 12) {
            Spacer()
            Image(systemName: "tray")
                .font(.system(size: 32, weight: .light))
                .foregroundColor(.aurionTextSecondary)
            Text(L("priorEncounters.fullList.empty"))
                .aurionFont(14, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 32)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var retryState: some View {
        VStack(spacing: 14) {
            Spacer()
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 28))
                .foregroundColor(.aurionAmber)
            Text(L("priorEncounters.loadFailed"))
                .aurionFont(14, relativeTo: .subheadline)
                .foregroundColor(.aurionTextPrimary)
            Button {
                Task { await load() }
            } label: {
                HStack(spacing: 6) {
                    if isLoading {
                        ProgressView().tint(.aurionNavy)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 12, weight: .semibold))
                    }
                    Text(L("priorEncounters.retry"))
                        .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                        .foregroundColor(.aurionNavy)
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 8)
                .background(Color.aurionGold)
                .clipShape(Capsule())
            }
            .disabled(isLoading)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var list: some View {
        List {
            ForEach(displayMatches) { match in
                Button {
                    AurionHaptics.selection()
                    onTap(match.sessionId)
                    dismiss()
                } label: {
                    PriorEncounterRow(match: match, identifier: identifier)
                }
                .listRowBackground(Color.aurionCardBackground)
                .listRowSeparatorTint(Color.aurionBorder)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Color.aurionBackground)
        .refreshable {
            await load()
        }
    }

    // MARK: - Data

    /// `internal` so tests can drive a reload directly. Mirrors the
    /// rail's loader to keep the two surfaces' contract aligned.
    @MainActor
    func load() async {
        isLoading = true
        do {
            let result = try await fetch(identifier)
            matches = result
            loadFailed = false
        } catch {
            // Same PHI guard as the rail — do NOT surface the
            // underlying error verbatim; generic copy + retry button.
            loadFailed = true
            // Don't clobber a previously-good list on a transient
            // refresh failure — the list keeps showing what it had,
            // and the user sees the inline error only via the
            // refresh control state.
            if matches.isEmpty {
                matches = []
            }
        }
        isLoading = false
    }
}

// MARK: - Row

/// One row in the full-list view. Larger format than the rail card —
/// shows full relative date + specialty + state badge + identifier chip
/// (the chip is a reminder of which patient the list is filtered to,
/// matching the inbox-row pattern).
private struct PriorEncounterRow: View {
    let match: PatientSessionMatch
    let identifier: String

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(localizedSpecialty(match.specialty))
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                        .lineLimit(1)
                    // Identifier chip — reused from the inbox row so
                    // the visual contract stays in one place (DRY).
                    InboxIdentifierChip(value: identifier)
                }
                Text(formatRelativeTime(match.createdAt))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionTextSecondary)
                    .lineLimit(1)
            }
            Spacer()
            AurionStatusPill(
                kind: sessionStateKind(match.state),
                labelOverride: sessionStateLabel(match.state)
            )
        }
        .padding(.vertical, 6)
        .contentShape(Rectangle())
    }
}
