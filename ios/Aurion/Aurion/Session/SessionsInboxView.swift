import SwiftUI

/// Sessions inbox — pixel-perfect port of `screens.jsx → SessionsScreen`.
/// 28pt Aurion title, filter pill row (All / Pending / Completed / Exported)
/// with counts, then a single rounded card containing every session row.
/// "Resume" gold pill replaces the status badge for pending sessions.
struct SessionsInboxView: View {
    @State private var sessions: [SessionResponse] = []
    @State private var isLoading = true
    @State private var sortNewestFirst = true
    @State private var filter: Filter = .all
    /// iPad readable-measure clamp — mirrors ``DashboardView``. Inbox
    /// rows are dense; stretching them edge-to-edge on a 11" iPad makes
    /// the eye sweep too far between specialty name and status pill.
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    /// Searchable text — matches against specialty display name and
    /// state. Empty string → no text filter applied.
    @State private var searchText: String = ""
    /// Client-side date-range narrowing of the inbox. Like text search, it
    /// narrows the displayed list without changing the status-chip counts.
    @State private var dateRange: DateRange = .all
    /// Programmatic nav stack — each entry is a session UUID. We push
    /// onto it when a Spotlight tap arrives (via ``AppNavigation``) so
    /// the user lands directly on the right note instead of having to
    /// hunt for the row.
    @State private var path: [String] = []
    @ObservedObject private var navigation = AppNavigation.shared
    /// Session the user long-pressed "Discard" on, pending confirmation.
    /// Non-nil drives the confirmation dialog; cleared on confirm/cancel.
    @State private var sessionToDiscard: SessionResponse?

    private enum Filter: String, CaseIterable, Hashable {
        case all = "All"
        case pending = "Pending"
        case completed = "Completed"
        case exported = "Exported"
        /// Localized chip label — mirrors ``DateRange.labelKey`` so the
        /// pill never renders the bare English rawValue in French.
        var labelKey: String { "sessions.filter.\(rawValue.lowercased())" }
    }

    /// Preset date windows for the inbox. `since == nil` means no lower
    /// bound (all time).
    private enum DateRange: String, CaseIterable, Hashable {
        case all, today, week, month
        var labelKey: String { "sessions.date.\(rawValue)" }
        var since: Date? {
            let cal = Calendar.current
            let now = Date()
            switch self {
            case .all:   return nil
            case .today: return cal.startOfDay(for: now)
            case .week:  return cal.date(byAdding: .day, value: -7, to: now)
            case .month: return cal.date(byAdding: .day, value: -30, to: now)
            }
        }
    }

    private func inDateRange(_ s: SessionResponse) -> Bool {
        guard let since = dateRange.since else { return true }
        // Unparseable timestamp → don't hide the row. Uses the shared
        // fractional-tolerant parser (Theme.parseISODate) — same logic the
        // dashboard count and relative-time formatter share (#279).
        guard let created = parseISODate(s.createdAt) else { return true }
        return created >= since
    }

    /// Sessions after (1) sort, (2) status filter, (3) text search.
    /// Composing in that order keeps the chip counts accurate when
    /// the user has typed a search query.
    private var filtered: [SessionResponse] {
        let sorted = sortNewestFirst ? sessions : sessions.reversed()
        let statusFiltered: [SessionResponse]
        switch filter {
        case .all: statusFiltered = sorted
        case .pending: statusFiltered = sorted.filter(isPending)
        case .completed: statusFiltered = sorted.filter { $0.state == "REVIEW_COMPLETE" }
        case .exported: statusFiltered = sorted.filter { $0.state == "EXPORTED" || $0.state == "PURGED" }
        }
        let dateFiltered = statusFiltered.filter(inDateRange)
        let query = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !query.isEmpty else { return dateFiltered }
        return dateFiltered.filter { session in
            localizedSpecialty(session.specialty).lowercased().contains(query)
                || session.state.lowercased().contains(query)
        }
    }

    private func count(for f: Filter) -> Int {
        switch f {
        case .all: return sessions.count
        case .pending: return sessions.filter(isPending).count
        case .completed: return sessions.filter { $0.state == "REVIEW_COMPLETE" }.count
        case .exported: return sessions.filter { $0.state == "EXPORTED" || $0.state == "PURGED" }.count
        }
    }

    private func isPending(_ s: SessionResponse) -> Bool {
        ["AWAITING_REVIEW", "PROCESSING_STAGE1", "PROCESSING_STAGE2"].contains(s.state)
    }

    var body: some View {
        NavigationStack(path: $path) {
            VStack(alignment: .leading, spacing: 0) {
                titleHeader
                filterChips
                Group {
                    if isLoading {
                        skeletonList
                    } else if filtered.isEmpty {
                        Spacer()
                        EmptyStateView(
                            icon: "tray",
                            title: filter == .all ? L("sessions.noSessions") : L("sessions.noFiltered", L(filter.labelKey).lowercased()),
                            subtitle: filter == .all ? L("sessions.noSessionsSub") : L("sessions.tryFilter")
                        )
                        .frame(maxWidth: .infinity)
                        Spacer()
                    } else {
                        sessionsList
                    }
                }
            }
            .background(Color.aurionBackground)
            .navigationBarHidden(true)
            .searchable(text: $searchText, placement: .navigationBarDrawer(displayMode: .always), prompt: L("sessions.searchPrompt"))
            .task { await loadSessions() }
            // Value-based destination so Spotlight deep-links can push by
            // session UUID without us having to materialize the full
            // ``SessionResponse`` up-front. If the row isn't in our local
            // list (rare: donation outlived a server-side delete) we fall
            // back to a tombstone view rather than crashing.
            .navigationDestination(for: String.self) { sessionID in
                if let s = sessions.first(where: { $0.id == sessionID }) {
                    SessionNoteView(session: s)
                } else {
                    EmptyStateView(
                        icon: "tray.slash",
                        title: L("sessions.tombstone.title"),
                        subtitle: L("sessions.tombstone.subtitle")
                    )
                    .padding()
                }
            }
            .onChange(of: navigation.pendingNoteSessionID) { _, id in
                guard let id else { return }
                Task {
                    // Ensure the session list is hot so the destination
                    // can resolve `SessionResponse` from the id. If it's
                    // already loaded this is a cache-hit no-op.
                    if sessions.first(where: { $0.id == id }) == nil {
                        await loadSessions()
                    }
                    // Replace the stack — we always want exactly one
                    // detail view on top, never a chain of stacked notes.
                    path = [id]
                    navigation.clearPendingNote()
                }
            }
        }
    }

    // MARK: - Title + filter chips

    private var titleHeader: some View {
        HStack {
            Text(L("sessions.title"))
                .aurionFont(28, weight: .bold, relativeTo: .title)
                .tracking(-0.56)
                .foregroundColor(.aurionTextPrimary)
            Spacer()
            Menu {
                Picker(selection: $dateRange) {
                    ForEach(DateRange.allCases, id: \.self) { range in
                        Text(L(range.labelKey)).tag(range)
                    }
                } label: { EmptyView() }
            } label: {
                Image(systemName: dateRange == .all ? "calendar" : "calendar.badge.checkmark")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(dateRange == .all ? .aurionTextSecondary : .aurionGold)
                    .padding(8)
                    // Keep the 14pt glyph but guarantee a 44pt minimum
                    // touch target (HIG).
                    .frame(minWidth: 44, minHeight: 44)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(L("sessions.dateFilter"))
            .accessibilityValue(L(dateRange.labelKey))

            Button {
                AurionHaptics.selection()
                withAnimation(.aurionIOS) { sortNewestFirst.toggle() }
            } label: {
                Image(systemName: sortNewestFirst ? "arrow.down" : "arrow.up")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.aurionTextSecondary)
                    .padding(8)
                    // Direction flip animates the same arrow rather than
                    // swapping symbols — feels intentional, not flickery.
                    .contentTransition(.symbolEffect(.replace))
                    // 14pt glyph, but a 44pt minimum touch target (HIG).
                    .frame(minWidth: 44, minHeight: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(L("a11y.sortSessions"))
            .accessibilityValue(sortNewestFirst ? L("sessions.sortNewest") : L("sessions.sortOldest"))
            .accessibilityHint(L("sessions.sortHint"))
        }
        .aurionScreenEdge()
        .padding(.top, 10)
        .padding(.bottom, 6)
    }

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(Filter.allCases, id: \.self) { f in
                    AurionFilterChip(label: L(f.labelKey), count: count(for: f), active: filter == f) {
                        withAnimation(.aurionIOS) { filter = f }
                    }
                }
            }
            .aurionScreenEdge()
            .padding(.vertical, 4)
        }
    }

    // MARK: - List

    /// Loading placeholder shaped like the real inbox — six shimmer rows in
    /// the same card so the layout reads as "forming," not "stuck."
    private var skeletonList: some View {
        ScrollView {
            AurionCard(padding: 0) {
                VStack(spacing: 0) {
                    ForEach(0..<6, id: \.self) { i in
                        HStack(spacing: 12) {
                            AurionSkeleton(cornerRadius: AurionRadius.sm)
                                .frame(width: 36, height: 36)
                            VStack(alignment: .leading, spacing: 6) {
                                AurionSkeleton().frame(width: 150, height: 13)
                                AurionSkeleton().frame(width: 90, height: 11)
                            }
                            Spacer()
                            AurionSkeleton(cornerRadius: 11).frame(width: 64, height: 22)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 14)
                        if i < 5 {
                            Rectangle().fill(Color.aurionBorder).frame(height: 1).padding(.leading, 64)
                        }
                    }
                }
            }
            .aurionScreenEdge()
            .padding(.top, 12)
            .frame(maxWidth: horizontalSizeClass == .regular ? 720 : .infinity)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .disabled(true)
    }

    private var sessionsList: some View {
        ScrollView {
            AurionCard(padding: 0) {
                VStack(spacing: 0) {
                    ForEach(Array(filtered.enumerated()), id: \.element.id) { index, session in
                        NavigationLink(value: session.id) {
                            sessionRow(session)
                        }
                        .buttonStyle(.plain)
                        .contextMenu {
                            Button(role: .destructive) {
                                sessionToDiscard = session
                            } label: {
                                Label(L("sessions.discard"), systemImage: "trash")
                            }
                        }
                        if index < filtered.count - 1 {
                            Rectangle().fill(Color.aurionBorder).frame(height: 1).padding(.leading, 64)
                        }
                    }
                }
            }
            .aurionScreenEdge()
            .padding(.top, 12)
            .padding(.bottom, 20)
            .frame(maxWidth: horizontalSizeClass == .regular ? 720 : .infinity)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        // Breathing room above the translucent (iOS 26 glass) tab bar
        // so the last session row doesn't read as clipped.
        .contentMargins(.bottom, 24, for: .scrollContent)
        .refreshable { await loadSessions() }
        .confirmationDialog(
            L("sessions.discardConfirmTitle"),
            isPresented: Binding(
                get: { sessionToDiscard != nil },
                set: { if !$0 { sessionToDiscard = nil } }
            ),
            titleVisibility: .visible,
            presenting: sessionToDiscard
        ) { session in
            Button(L("sessions.discard"), role: .destructive) {
                Task { await discard(session) }
            }
            Button(L("common.cancel"), role: .cancel) { sessionToDiscard = nil }
        } message: { _ in
            Text(L("sessions.discardConfirmMessage"))
        }
    }

    /// Delete a session server-side, then drop it from the local list. On
    /// failure, resync from the server so the inbox reflects reality rather
    /// than optimistically hiding a row that wasn't actually removed.
    private func discard(_ s: SessionResponse) async {
        sessionToDiscard = nil
        do {
            try await APIClient.shared.discardSession(sessionId: s.id)
            withAnimation { sessions.removeAll { $0.id == s.id } }
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            await loadSessions()
        }
    }

    private func sessionRow(_ s: SessionResponse) -> some View {
        let icon: String = {
            switch s.specialty {
            case "orthopedic_surgery": return "figure.walk"
            case "plastic_surgery": return "heart"
            case "musculoskeletal": return "figure.run"
            case "emergency_medicine": return "cross.case"
            default: return "stethoscope"
            }
        }()
        return HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: AurionRadius.sm)
                    .fill(Color.aurionSurfaceAlt)
                    .frame(width: 36, height: 36)
                Image(systemName: icon)
                    .font(.system(size: 16))
                    .foregroundColor(.aurionTextSecondary)
            }
            VStack(alignment: .leading, spacing: 2) {
                HStack(spacing: 6) {
                    Text(localizedSpecialty(s.specialty))
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                        .lineLimit(1)
                    // Patient identifier chip (#61). Only visible when
                    // the physician has actually set one. Monospaced so
                    // visually-similar codes (1/l, 0/O) read cleanly
                    // even at small size. Truncates with ellipsis so a
                    // long identifier doesn't push the row layout out
                    // of shape — full value remains accessible on the
                    // session detail screen.
                    if let identifier = s.externalReferenceId, !identifier.isEmpty {
                        InboxIdentifierChip(value: identifier)
                    }
                }
                Text(formatRelativeTime(s.createdAt))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionTextSecondary)
                    .lineLimit(1)
            }
            Spacer()
            if isPending(s) {
                Text(L("sessions.resume"))
                    .font(.system(size: 12, weight: .semibold))
                    // Brand-navy on gold pill — fixed in both modes.
                    .foregroundColor(.aurionNavy)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color.aurionGold)
                    .clipShape(Capsule())
            } else {
                AurionStatusPill(
                    kind: sessionStateKind(s.state),
                    labelOverride: sessionStateLabel(s.state)
                )
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .contentShape(Rectangle())
    }

    // MARK: - Data

    private func loadSessions() async {
        isLoading = true
        defer { isLoading = false }
        do {
            sessions = try await APIClient.shared.listSessions()
        } catch {
            sessions = [
                SessionResponse(id: "demo-1", clinicianId: "c1", specialty: "orthopedic_surgery", state: "AWAITING_REVIEW", encounterType: "doctor_patient", createdAt: "2026-04-14T10:30:00Z", updatedAt: "2026-04-14T11:00:00Z"),
                SessionResponse(id: "demo-2", clinicianId: "c1", specialty: "plastic_surgery", state: "EXPORTED", encounterType: "doctor_patient", createdAt: "2026-04-13T14:00:00Z", updatedAt: "2026-04-13T14:45:00Z"),
                SessionResponse(id: "demo-3", clinicianId: "c1", specialty: "orthopedic_surgery", state: "REVIEW_COMPLETE", encounterType: "doctor_patient_allied", createdAt: "2026-04-12T09:15:00Z", updatedAt: "2026-04-12T10:00:00Z"),
                SessionResponse(id: "demo-4", clinicianId: "c1", specialty: "orthopedic_surgery", state: "PURGED", encounterType: "doctor_patient", createdAt: "2026-04-11T08:00:00Z", updatedAt: "2026-04-11T09:00:00Z"),
            ]
        }
    }
}


/// Inline chip rendering the session's patient identifier (#61) in
/// the inbox row.
///
/// Visual contract:
///   * monospaced font for character disambiguation (1/l, 0/O)
///   * gold-tinted border + matching gold-50 background so the chip
///     reads as "linked to a chart" without competing with the
///     specialty title for visual weight
///   * truncates with ellipsis at the trailing edge; full value
///     remains accessible on the session detail / post-encounter
///     screen
///   * accessibilityLabel uses the localized hint so VoiceOver
///     announces "Patient identifier MRN-12345" instead of just
///     reading the bare code
struct InboxIdentifierChip: View {
    let value: String

    var body: some View {
        Text(value)
            .font(.system(size: 11, weight: .semibold, design: .monospaced))
            .foregroundColor(.aurionGold)
            .lineLimit(1)
            .truncationMode(.tail)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Color.aurionGold.opacity(0.12))
            .overlay(
                Capsule()
                    .stroke(Color.aurionGold.opacity(0.35), lineWidth: 1)
            )
            .clipShape(Capsule())
            .accessibilityLabel(Text("\(L("patientId.set")) \(value)"))
    }
}
