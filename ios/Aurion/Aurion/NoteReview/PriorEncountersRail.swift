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
/// The identifier IS PHI. We carry it via the model so the API call has
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
/// All data plumbing lives on `PriorEncountersModel` — same model the
/// `PriorEncountersListView` consumes. The rail and the list never
/// duplicate the filter/sort/load logic.
struct PriorEncountersRail: View {

    /// Backing model — owns the fetch, the sort, the
    /// loading/failure/empty derivations. Tests construct one of these
    /// directly so the assertions don't rely on a mounted view tree.
    @StateObject var model: PriorEncountersModel

    /// Invoked when the user taps a card. The inits set the default to
    /// the AppNavigation router; tests pass a probe closure to assert
    /// the right session id was surfaced. Open/Closed: the rail doesn't
    /// introduce a router — it fires the SAME event the dashboard
    /// recent strip uses.
    var onTap: (String) -> Void

    /// Tap on "See all (N)" — drives the parent's sheet binding. Inits
    /// default this to a no-op so the rail compiles standalone in tests.
    var onSeeAll: () -> Void

    /// Convenience initializer used by `NoteReviewView`. Wraps the model
    /// construction so callers don't have to allocate it explicitly.
    /// The `fetch` parameter stays open so the SwiftUI preview / smoke
    /// tests can still inject a canned closure here.
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
        },
        onSeeAll: @escaping () -> Void = { }
    ) {
        _model = StateObject(wrappedValue: PriorEncountersModel(
            currentSessionId: currentSessionId,
            identifier: identifier,
            fetch: fetch
        ))
        self.onTap = onTap
        self.onSeeAll = onSeeAll
    }

    /// Model-driven initializer — tests construct the model first, then
    /// inject it. Keeps the rail's surface symmetrical with the list
    /// view's `model:` overload.
    init(
        model: PriorEncountersModel,
        onTap: @escaping (String) -> Void = { sessionId in
            Task { @MainActor in
                AppNavigation.shared.requestNote(sessionID: sessionId)
                AppNavigation.shared.requestTab(.sessions)
            }
        },
        onSeeAll: @escaping () -> Void = { }
    ) {
        _model = StateObject(wrappedValue: model)
        self.onTap = onTap
        self.onSeeAll = onSeeAll
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
        .task(id: model.identifier) {
            await model.load()
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
            Text(L("priorEncounters.titleWith", model.identifier))
                .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                .foregroundColor(.aurionTextPrimary)
                .lineLimit(1)
                .truncationMode(.tail)
            Spacer()
            if model.totalRelevant > PriorEncountersModel.maxRailCards {
                Button {
                    AurionHaptics.selection()
                    onSeeAll()
                } label: {
                    Text(L("priorEncounters.seeAll", model.totalRelevant))
                        .aurionFont(12, weight: .semibold, relativeTo: .caption)
                        .foregroundColor(.aurionGold)
                        // Enlarge the tap target to the 44pt minimum
                        // without inflating the visible glyph.
                        .padding(.leading, 8)
                        .frame(minHeight: 44)
                        .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Body content (loading / populated / empty / failure)

    @ViewBuilder
    private var content: some View {
        if model.isLoading {
            skeletons
        } else if model.loadFailed {
            retryBlock
        } else if model.railMatches.isEmpty {
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
                    // Shimmer placeholder (matches SessionNoteView /
                    // SessionsInboxView) so the rail reads as "forming,"
                    // not "stuck." AurionSkeleton supplies its own
                    // adaptive fill + clip.
                    AurionSkeleton(cornerRadius: AurionRadius.md)
                        .frame(width: 180, height: 78)
                }
            }
            .padding(.vertical, 4)
        }
    }

    // MARK: Populated row

    private var cardRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(model.railMatches) { match in
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
                Task { await model.load() }
            } label: {
                HStack(spacing: 4) {
                    if model.isLoading {
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
            .disabled(model.isLoading)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(Color.aurionAmberBg.opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
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
