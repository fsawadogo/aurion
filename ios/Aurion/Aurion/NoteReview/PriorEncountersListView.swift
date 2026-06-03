import SwiftUI

/// Full-screen list of every prior encounter for a given patient
/// identifier (#61, full slice).
///
/// Reached from the rail's "See all (N)" link on `NoteReviewView`.
/// Same data source as the rail — both share `PriorEncountersModel`
/// (DRY gate, see `PriorEncountersTests`). No 5-cap; renders the full
/// sorted list.
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

    /// Backing model — owns the fetch, the sort, the
    /// loading/failure/empty derivations. Constructed by the convenience
    /// init from `NoteReviewView`; tests construct one directly to drive
    /// the assertions without mounting the view.
    @StateObject var model: PriorEncountersModel

    /// Invoked when the user taps a row — inits default this to the
    /// shared AppNavigation router so the inbox stack handles the
    /// push (no new routing layer per §6c OCP).
    var onTap: (String) -> Void

    /// Sheet dismiss handle — when nil, the sheet stays open after a
    /// tap (useful for tests). The production caller (NoteReviewView)
    /// passes `\.dismiss` so picking a session closes the list and the
    /// inbox push happens behind it.
    @Environment(\.dismiss) private var dismiss

    /// Convenience initializer used by `NoteReviewView`. Mirrors the
    /// rail's surface so the call site is identical between the rail
    /// and the list.
    init(
        currentSessionId: String,
        identifier: String,
        fetch: @escaping (String) async throws -> [PatientSessionMatch] = {
            try await APIClient.shared.listMySessionsByPatientIdentifier($0)
        },
        onTap: @escaping (String) -> Void = { sessionId in
            Task { @MainActor in
                AppNavigation.shared.requestNote(sessionID: sessionId)
                AppNavigation.shared.requestTab(.sessions)
            }
        }
    ) {
        _model = StateObject(wrappedValue: PriorEncountersModel(
            currentSessionId: currentSessionId,
            identifier: identifier,
            fetch: fetch
        ))
        self.onTap = onTap
    }

    /// Model-driven initializer — tests construct the model first, then
    /// inject it. Symmetrical with the rail.
    init(
        model: PriorEncountersModel,
        onTap: @escaping (String) -> Void = { sessionId in
            Task { @MainActor in
                AppNavigation.shared.requestNote(sessionID: sessionId)
                AppNavigation.shared.requestTab(.sessions)
            }
        }
    ) {
        _model = StateObject(wrappedValue: model)
        self.onTap = onTap
    }

    var body: some View {
        NavigationStack {
            Group {
                if model.isLoading && model.matches.isEmpty {
                    loadingState
                } else if model.loadFailed && model.matches.isEmpty {
                    retryState
                } else if model.relevantMatches.isEmpty {
                    emptyState
                } else {
                    list
                }
            }
            .navigationTitle(L("priorEncounters.fullList.title", model.identifier))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("common.done")) { dismiss() }
                }
            }
            .background(Color.aurionBackground)
        }
        .task(id: model.identifier) {
            await model.load()
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
                Task { await model.load() }
            } label: {
                HStack(spacing: 6) {
                    if model.isLoading {
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
            .disabled(model.isLoading)
            Spacer()
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private var list: some View {
        List {
            ForEach(model.relevantMatches) { match in
                Button {
                    AurionHaptics.selection()
                    onTap(match.sessionId)
                    dismiss()
                } label: {
                    PriorEncounterRow(match: match, identifier: model.identifier)
                }
                .listRowBackground(Color.aurionCardBackground)
                .listRowSeparatorTint(Color.aurionBorder)
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Color.aurionBackground)
        .refreshable {
            await model.load()
        }
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
