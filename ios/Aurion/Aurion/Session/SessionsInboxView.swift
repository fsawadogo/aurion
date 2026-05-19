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
    /// Programmatic nav stack — each entry is a session UUID. We push
    /// onto it when a Spotlight tap arrives (via ``AppNavigation``) so
    /// the user lands directly on the right note instead of having to
    /// hunt for the row.
    @State private var path: [String] = []
    @ObservedObject private var navigation = AppNavigation.shared

    private enum Filter: String, CaseIterable, Hashable {
        case all = "All"
        case pending = "Pending"
        case completed = "Completed"
        case exported = "Exported"
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
        let query = searchText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !query.isEmpty else { return statusFiltered }
        return statusFiltered.filter { session in
            session.specialty.displayFormatted.lowercased().contains(query)
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
                        Spacer(); ProgressView().frame(maxWidth: .infinity); Spacer()
                    } else if filtered.isEmpty {
                        Spacer()
                        EmptyStateView(
                            icon: "tray",
                            title: filter == .all ? "No sessions yet" : "No \(filter.rawValue.lowercased()) sessions",
                            subtitle: filter == .all ? "Start one from the Dashboard" : "Try a different filter"
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
            .searchable(text: $searchText, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search by specialty or status")
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
                        title: "Session not available",
                        subtitle: "This note may have been purged or signed out from another device."
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
            Text("Sessions")
                .font(.system(size: 28, weight: .bold))
                .tracking(-0.56)
                .foregroundColor(.aurionTextPrimary)
            Spacer()
            Button {
                withAnimation(.aurionIOS) { sortNewestFirst.toggle() }
            } label: {
                Image(systemName: sortNewestFirst ? "arrow.down" : "arrow.up")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.aurionTextSecondary)
                    .padding(8)
                    // Direction flip animates the same arrow rather than
                    // swapping symbols — feels intentional, not flickery.
                    .contentTransition(.symbolEffect(.replace))
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Sort sessions")
            .accessibilityValue(sortNewestFirst ? "Newest first" : "Oldest first")
            .accessibilityHint("Double-tap to reverse the sort order.")
        }
        .aurionScreenEdge()
        .padding(.top, 10)
        .padding(.bottom, 6)
    }

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(Filter.allCases, id: \.self) { f in
                    AurionFilterChip(label: f.rawValue, count: count(for: f), active: filter == f) {
                        withAnimation(.aurionIOS) { filter = f }
                    }
                }
            }
            .aurionScreenEdge()
            .padding(.vertical, 4)
        }
    }

    // MARK: - List

    private var sessionsList: some View {
        ScrollView {
            AurionCard(padding: 0) {
                VStack(spacing: 0) {
                    ForEach(Array(filtered.enumerated()), id: \.element.id) { index, session in
                        NavigationLink(value: session.id) {
                            sessionRow(session)
                        }
                        .buttonStyle(.plain)
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
                Text(s.specialty.displayFormatted)
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundColor(.aurionTextPrimary)
                    .lineLimit(1)
                Text(formatRelativeTime(s.createdAt))
                    .font(.system(size: 12))
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
