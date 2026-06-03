import SwiftUI

/// Horizontal "Prior encounters with this patient" rail (#61, full slice).
///
/// Mounts on `NoteReviewView` above the prose body whenever the current
/// session carries a non-empty `external_reference_id`. Shows up to five
/// of the most recent prior encounters that share the same identifier
/// — newest first, excluding the current session and any PURGED row.
/// A "See all (N)" link surfaces only when total > 5; tapping it opens
/// the full-screen `PriorEncountersListView`.
///
/// ## Privacy
///
/// The identifier IS PHI. We carry it as a String so the API call has
/// what it needs, and surface it inline in the title ("Prior encounters
/// · MRN-12345"). It is NEVER logged, NEVER passed to
/// `AuditLogger.log(extra:)`, NEVER included in error messages. The
/// PHI test in `PriorEncountersTests` greps this file + the list view
/// for that contract.
///
/// ## States
///
/// 1. **Loading** — three skeleton cards staircase in
/// 2. **Populated** — N ≤ 5 cards, each tappable, "See all (N)" if > 5
/// 3. **Empty** — "First encounter with this patient" callout
/// 4. **Failure** — Retry block (same shape as PatientSummaryCard)
///
/// ## DRY
///
/// The fetcher is parameterized so the test suite can inject a mock
/// without subclassing APIClient. The production caller passes
/// `nil` and gets the real `APIClient.shared.listMySessionsByPatientIdentifier`.
/// Both the rail and the full list resolve to THIS same closure type
/// — see `PriorEncountersListView.swift`.
struct PriorEncountersRail: View {
    let currentSessionId: String
    let identifier: String

    /// Test seam — defaults to the real API client. Tests pass a closure
    /// that returns canned data (or throws) so the rail's branches can
    /// be exercised without a network or backend.
    var fetch: (String) async throws -> [PatientSessionMatch] = {
        try await APIClient.shared.listMySessionsByPatientIdentifier($0)
    }

    /// Invoked when the user taps a card. Default emits the standard
    /// AppNavigation request so the inbox stack handles the push;
    /// tests pass a probe closure to assert the right session id was
    /// surfaced. Open/Closed: the rail doesn't introduce a router — it
    /// fires the SAME event the dashboard recent strip uses.
    var onTap: (String) -> Void = { sessionId in
        AppNavigation.shared.requestNote(sessionID: sessionId)
        AppNavigation.shared.requestTab(.sessions)
    }

    /// Tap on "See all (N)" — drives the parent's sheet binding.
    /// Default is a no-op so the rail compiles standalone in tests.
    var onSeeAll: () -> Void = { }

    @State private var matches: [PatientSessionMatch] = []
    @State private var isLoading = true
    @State private var loadFailed = false

    /// At most this many cards in the rail. Anything past this rolls
    /// into the "See all (N)" link. Matches the UX size sweet spot
    /// for a horizontal scroll on iPhone (~ three cards on a 6.1"
    /// display + a hint of the next).
    private static let maxRailCards = 5

    /// Sessions surfaced in the rail. Filters first
    /// (current session id + PURGED), THEN caps. This ordering matters
    /// because the see-all gate fires off the **filtered** total, not
    /// the raw API response size.
    var displayMatches: [PatientSessionMatch] {
        let filtered = matches.filter {
            $0.sessionId != currentSessionId && $0.state != "PURGED"
        }
        return Array(filtered.prefix(Self.maxRailCards))
    }

    /// Filtered total — the number behind "See all (N)" and the
    /// see-all visibility gate. Both the rail and the list display this
    /// same view of "relevant prior encounters".
    var totalRelevant: Int {
        matches.filter {
            $0.sessionId != currentSessionId && $0.state != "PURGED"
        }.count
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            header
            content
        }
        .padding(.horizontal, 16)
        .padding(.top, 14)
        .padding(.bottom, 8)
        .background(Color.aurionBackground)
        .task(id: identifier) {
            await load()
        }
    }

    // MARK: - Header

    private var header: some View {
        HStack(alignment: .firstTextBaseline, spacing: 8) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.aurionGold)
            // Title carries the identifier inline — same chip pattern as
            // the inbox row so the physician sees "which patient" without
            // a second glance back at the post-encounter row.
            Text(L("priorEncounters.titleWith", identifier))
                .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                .foregroundColor(.aurionTextPrimary)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer()
            if totalRelevant > Self.maxRailCards {
                Button {
                    AurionHaptics.selection()
                    onSeeAll()
                } label: {
                    Text(L("priorEncounters.seeAll", totalRelevant))
                        .aurionFont(12, weight: .semibold, relativeTo: .caption)
                        .foregroundColor(.aurionGold)
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Body content (loading / populated / empty / failure)

    @ViewBuilder
    private var content: some View {
        if isLoading {
            skeletons
        } else if loadFailed {
            retryBlock
        } else if displayMatches.isEmpty {
            emptyState
        } else {
            cardRow
        }
    }

    // MARK: Skeletons

    private var skeletons: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(0..<3, id: \.self) { _ in
                    RoundedRectangle(cornerRadius: AurionRadius.md)
                        .fill(Color.aurionSurfaceAlt)
                        .frame(width: 180, height: 78)
                        .overlay(
                            RoundedRectangle(cornerRadius: AurionRadius.md)
                                .stroke(Color.aurionBorder, lineWidth: 1)
                        )
                }
            }
            .padding(.vertical, 4)
        }
    }

    // MARK: Populated row

    private var cardRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(displayMatches) { match in
                    PriorEncounterCard(match: match) {
                        AurionHaptics.selection()
                        onTap(match.sessionId)
                    }
                }
            }
            .padding(.vertical, 4)
        }
    }

    // MARK: Empty state

    private var emptyState: some View {
        HStack(spacing: 10) {
            Image(systemName: "sparkles")
                .font(.system(size: 13))
                .foregroundColor(.aurionTextSecondary)
            Text(L("priorEncounters.empty"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
            Spacer()
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 12)
        .background(Color.aurionSurfaceAlt)
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
    }

    // MARK: Failure / Retry

    /// Mirrors `PatientSummaryCard.retryState` (PR #186) — same copy
    /// shape and same affordance so the failure UX is consistent
    /// across the review surface. Second occurrence; if a third lands,
    /// extract per §6c.
    private var retryBlock: some View {
        HStack(spacing: 10) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundColor(.aurionAmber)
            Text(L("priorEncounters.loadFailed"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextPrimary)
                .lineLimit(2)
            Spacer()
            Button {
                Task { await load() }
            } label: {
                HStack(spacing: 4) {
                    if isLoading {
                        ProgressView().tint(.aurionTextPrimary)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 11, weight: .semibold))
                    }
                    Text(L("priorEncounters.retry"))
                        .aurionFont(12, weight: .semibold, relativeTo: .caption)
                }
                .foregroundColor(.aurionTextPrimary)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Color.aurionBackground)
                .clipShape(Capsule())
            }
            .disabled(isLoading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color.aurionAmberBg.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
    }

    // MARK: - Data

    /// `internal` so tests can drive a reload without having to mount
    /// the SwiftUI view in a host. Awaits the (possibly injected)
    /// fetcher; on success the rail repopulates with the new list, on
    /// failure it flips to the retry block.
    @MainActor
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
            // PHI guard: the error.localizedDescription may include the
            // request URL, which embeds the identifier. We deliberately
            // do NOT surface the error verbatim — the retry block uses
            // generic copy, and nothing logs the underlying error.
            loadFailed = true
            matches = []
        }
        isLoading = false
    }
}

// MARK: - Card

/// One compact card in the rail. Tap → tap handler.
///
/// Visual contract:
///   * relative timestamp on top (uses ``formatRelativeTime``)
///   * specialty headline below (uses ``localizedSpecialty``)
///   * state pill on the bottom right (reuses ``AurionStatusPill``)
///
/// 180pt fixed width keeps card sizing consistent across iPhone +
/// iPad so the rail's rhythm doesn't shift between size classes.
private struct PriorEncounterCard: View {
    let match: PatientSessionMatch
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(alignment: .leading, spacing: 6) {
                Text(formatRelativeTime(match.createdAt))
                    .aurionFont(11, weight: .medium, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
                    .lineLimit(1)
                Text(localizedSpecialty(match.specialty))
                    .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                    .foregroundColor(.aurionTextPrimary)
                    .lineLimit(2)
                    .multilineTextAlignment(.leading)
                Spacer(minLength: 0)
                AurionStatusPill(
                    kind: sessionStateKind(match.state),
                    labelOverride: sessionStateLabel(match.state)
                )
            }
            .frame(width: 180, height: 78, alignment: .leading)
            .padding(.horizontal, 10)
            .padding(.vertical, 8)
            .background(Color.aurionCardBackground)
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
            .overlay(
                RoundedRectangle(cornerRadius: AurionRadius.md)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        // VoiceOver: announce "Open encounter from <relative time>"
        // rather than just the timestamp + specialty so the action is
        // clear. Specialty + state still get read via the children.
        .accessibilityLabel(Text(
            L("priorEncounters.a11y.tapCard", formatRelativeTime(match.createdAt))
        ))
    }
}
