import SwiftUI

/// Sessions inbox — list of all past sessions with notes.
/// Physicians access completed notes here to review and copy.
struct SessionsInboxView: View {
    @State private var sessions: [SessionResponse] = []
    @State private var isLoading = true
    @State private var selectedSpecialty: String? = nil
    @State private var error: String?
    @State private var sortNewestFirst = true

    private let specialties = ["All", "Orthopedic Surgery", "Plastic Surgery", "Musculoskeletal", "Emergency Medicine", "General"]

    // MARK: - Computed Properties

    private var filteredSessions: [SessionResponse] {
        var result = sessions
        if let filter = selectedSpecialty, filter != "All" {
            let key = filter.lowercased().replacingOccurrences(of: " ", with: "_")
            result = result.filter { $0.specialty == key }
        }
        if !sortNewestFirst {
            result = result.reversed()
        }
        return result
    }

    private var pendingSessions: [SessionResponse] {
        filteredSessions.filter { $0.state == "AWAITING_REVIEW" }
    }

    private var completedSessions: [SessionResponse] {
        filteredSessions.filter { $0.state != "AWAITING_REVIEW" }
    }

    private func countForSpecialty(_ specialty: String) -> Int {
        if specialty == "All" { return sessions.count }
        let key = specialty.lowercased().replacingOccurrences(of: " ", with: "_")
        return sessions.filter { $0.specialty == key }.count
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Specialty filter chips
                filterChips

                if isLoading {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if filteredSessions.isEmpty {
                    Spacer()
                    EmptyStateView(
                        icon: "list.clipboard",
                        title: "No sessions yet",
                        subtitle: "Start one from the Dashboard"
                    )
                    Spacer()
                } else {
                    sessionsList
                }
            }
            .background(Color.aurionBackground)
            .navigationTitle("Sessions")
            .aurionNavBar()
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button {
                        withAnimation(AurionAnimation.spring) {
                            sortNewestFirst.toggle()
                        }
                    } label: {
                        Image(systemName: sortNewestFirst ? "arrow.down" : "arrow.up")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundColor(.white)
                    }
                }
            }
            .task { await loadSessions() }
        }
    }

    // MARK: - Filter Chips

    private var filterChips: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: AurionSpacing.xs) {
                ForEach(specialties, id: \.self) { specialty in
                    Button {
                        withAnimation(AurionAnimation.spring) {
                            selectedSpecialty = specialty == "All" ? nil : specialty
                        }
                    } label: {
                        HStack(spacing: AurionSpacing.xxs) {
                            Text(specialty)
                                .font(.system(size: 13, weight: isSelected(specialty) ? .semibold : .regular))

                            let count = countForSpecialty(specialty)
                            if count > 0 {
                                Text("\(count)")
                                    .font(.system(size: 10, weight: .bold))
                                    .foregroundColor(isSelected(specialty) ? .aurionGold : .secondary)
                                    .padding(.horizontal, 5)
                                    .padding(.vertical, 1)
                                    .background(
                                        isSelected(specialty)
                                            ? Color.white.opacity(0.2)
                                            : Color.aurionFieldBackground
                                    )
                                    .clipShape(Capsule())
                            }
                        }
                        .foregroundColor(isSelected(specialty) ? .white : .aurionTextPrimary)
                        .padding(.horizontal, AurionSpacing.md)
                        .padding(.vertical, AurionSpacing.xs)
                        .background(isSelected(specialty) ? Color.aurionGold : Color.aurionFieldBackground)
                        .cornerRadius(AurionSpacing.md)
                    }
                }
            }
            .padding(.horizontal, AurionSpacing.lg)
            .padding(.vertical, AurionSpacing.sm)
        }
    }

    // MARK: - Sessions List

    private var sessionsList: some View {
        List {
            // Pending Review section — pinned at top
            if !pendingSessions.isEmpty {
                Section {
                    ForEach(pendingSessions, id: \.id) { session in
                        NavigationLink(destination: SessionNoteView(session: session)) {
                            SessionRow(session: session)
                        }
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: AurionSpacing.xxs, leading: AurionSpacing.lg, bottom: AurionSpacing.xxs, trailing: AurionSpacing.lg))
                    }
                } header: {
                    SectionHeader(title: "Pending Review", count: pendingSessions.count)
                        .padding(.bottom, AurionSpacing.xxs)
                }
            }

            // Completed section
            if !completedSessions.isEmpty {
                Section {
                    ForEach(completedSessions, id: \.id) { session in
                        NavigationLink(destination: SessionNoteView(session: session)) {
                            SessionRow(session: session)
                        }
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: AurionSpacing.xxs, leading: AurionSpacing.lg, bottom: AurionSpacing.xxs, trailing: AurionSpacing.lg))
                    }
                } header: {
                    SectionHeader(title: "Completed", count: completedSessions.count)
                        .padding(.bottom, AurionSpacing.xxs)
                }
            }
        }
        .listStyle(.plain)
        .refreshable { await loadSessions() }
    }

    // MARK: - Helpers

    private func isSelected(_ specialty: String) -> Bool {
        if specialty == "All" { return selectedSpecialty == nil }
        return selectedSpecialty == specialty
    }

    private func loadSessions() async {
        isLoading = true
        do {
            sessions = try await APIClient.shared.listSessions()
        } catch {
            // Show placeholder sessions for Simulator
            sessions = [
                SessionResponse(id: "demo-1", clinicianId: "c1", specialty: "orthopedic_surgery", state: "AWAITING_REVIEW", createdAt: "2026-04-14T10:30:00Z", updatedAt: "2026-04-14T11:00:00Z"),
                SessionResponse(id: "demo-2", clinicianId: "c1", specialty: "plastic_surgery", state: "EXPORTED", createdAt: "2026-04-13T14:00:00Z", updatedAt: "2026-04-13T14:45:00Z"),
                SessionResponse(id: "demo-3", clinicianId: "c1", specialty: "orthopedic_surgery", state: "REVIEW_COMPLETE", createdAt: "2026-04-12T09:15:00Z", updatedAt: "2026-04-12T10:00:00Z"),
                SessionResponse(id: "demo-4", clinicianId: "c1", specialty: "orthopedic_surgery", state: "PURGED", createdAt: "2026-04-11T08:00:00Z", updatedAt: "2026-04-11T09:00:00Z"),
            ]
        }
        isLoading = false
    }
}

// MARK: - Session Row

struct SessionRow: View {
    let session: SessionResponse

    private var displaySpecialty: String {
        session.specialty.replacingOccurrences(of: "_", with: " ").capitalized
    }

    private var displayDate: String {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: session.createdAt) {
            let display = DateFormatter()
            display.dateStyle = .medium
            display.timeStyle = .short
            return display.string(from: date)
        }
        return session.createdAt
    }

    private var stateBadge: (text: String, color: Color) {
        switch session.state {
        case "EXPORTED": return ("Exported", .clinicalNormal)
        case "REVIEW_COMPLETE": return ("Ready", .clinicalInfo)
        case "PURGED": return ("Archived", .clinicalNeutral)
        case "AWAITING_REVIEW": return ("Review", .aurionGold)
        case "PROCESSING_STAGE1": return ("Processing", .clinicalWarning)
        case "PROCESSING_STAGE2": return ("Enriching", .clinicalWarning)
        case "RECORDING": return ("Recording", .clinicalAlert)
        case "PAUSED": return ("Paused", .clinicalWarning)
        default: return (session.state, .clinicalNeutral)
        }
    }

    var body: some View {
        HStack(spacing: AurionSpacing.sm) {
            // Specialty icon
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color.aurionGold.opacity(0.1))
                    .frame(width: 44, height: 44)
                Image(systemName: specialtyIcon)
                    .font(.title3)
                    .foregroundColor(.aurionGold)
            }

            VStack(alignment: .leading, spacing: AurionSpacing.xxs) {
                Text(displaySpecialty)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundColor(.aurionTextPrimary)
                Text(displayDate)
                    .aurionCaption()
            }

            Spacer()

            StatusBadge(text: stateBadge.text, color: stateBadge.color)
        }
        .padding(.vertical, AurionSpacing.xs)
        .padding(.horizontal, AurionSpacing.md)
        .background(Color.aurionCardBackground)
        .cornerRadius(AurionSpacing.sm)
    }

    private var specialtyIcon: String {
        switch session.specialty {
        case "orthopedic_surgery": return "figure.walk"
        case "plastic_surgery": return "bandage"
        case "musculoskeletal": return "figure.run"
        case "emergency_medicine": return "cross.case"
        default: return "stethoscope"
        }
    }
}
