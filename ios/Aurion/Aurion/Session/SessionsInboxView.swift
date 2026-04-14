import SwiftUI

/// Sessions inbox — list of all past sessions with notes.
/// Physicians access completed notes here to review and copy.
struct SessionsInboxView: View {
    @State private var sessions: [SessionResponse] = []
    @State private var isLoading = true
    @State private var selectedSpecialty: String? = nil
    @State private var error: String?

    private let specialties = ["All", "Orthopedic Surgery", "Plastic Surgery", "Musculoskeletal", "Emergency Medicine", "General"]

    var filteredSessions: [SessionResponse] {
        guard let filter = selectedSpecialty, filter != "All" else { return sessions }
        let key = filter.lowercased().replacingOccurrences(of: " ", with: "_")
        return sessions.filter { $0.specialty == key }
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Specialty filter
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(specialties, id: \.self) { specialty in
                            Button {
                                withAnimation(AurionAnimation.spring) {
                                    selectedSpecialty = specialty == "All" ? nil : specialty
                                }
                            } label: {
                                Text(specialty)
                                    .font(.caption)
                                    .fontWeight(isSelected(specialty) ? .semibold : .regular)
                                    .foregroundColor(isSelected(specialty) ? .white : .aurionTextPrimary)
                                    .padding(.horizontal, 14)
                                    .padding(.vertical, 6)
                                    .background(isSelected(specialty) ? Color.aurionGold : Color.aurionFieldBackground)
                                    .cornerRadius(16)
                            }
                        }
                    }
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                }

                if isLoading {
                    Spacer()
                    ProgressView()
                    Spacer()
                } else if filteredSessions.isEmpty {
                    Spacer()
                    VStack(spacing: 16) {
                        Image(systemName: "list.clipboard")
                            .font(.system(size: 48))
                            .foregroundColor(.secondary.opacity(0.4))
                        Text("No sessions yet")
                            .font(.headline)
                            .foregroundColor(.secondary)
                        Text("Start one from the Dashboard")
                            .font(.subheadline)
                            .foregroundColor(.secondary.opacity(0.7))
                    }
                    Spacer()
                } else {
                    List(filteredSessions, id: \.id) { session in
                        NavigationLink(destination: SessionNoteView(session: session)) {
                            SessionRow(session: session)
                        }
                        .listRowSeparator(.hidden)
                        .listRowInsets(EdgeInsets(top: 4, leading: 20, bottom: 4, trailing: 20))
                    }
                    .listStyle(.plain)
                    .refreshable { await loadSessions() }
                }
            }
            .background(Color.aurionBackground)
            .navigationTitle("Sessions")
            .aurionNavBar()
            .task { await loadSessions() }
        }
    }

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
                SessionResponse(id: "demo-1", clinicianId: "c1", specialty: "orthopedic_surgery", state: "EXPORTED", createdAt: "2026-04-14T10:30:00Z", updatedAt: "2026-04-14T11:00:00Z"),
                SessionResponse(id: "demo-2", clinicianId: "c1", specialty: "plastic_surgery", state: "REVIEW_COMPLETE", createdAt: "2026-04-13T14:00:00Z", updatedAt: "2026-04-13T14:45:00Z"),
                SessionResponse(id: "demo-3", clinicianId: "c1", specialty: "orthopedic_surgery", state: "PURGED", createdAt: "2026-04-12T09:15:00Z", updatedAt: "2026-04-12T10:00:00Z"),
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
        case "EXPORTED": return ("Exported", .green)
        case "REVIEW_COMPLETE": return ("Ready", .blue)
        case "PURGED": return ("Archived", .secondary)
        case "AWAITING_REVIEW": return ("Pending", .aurionAmber)
        default: return (session.state, .secondary)
        }
    }

    var body: some View {
        HStack(spacing: 14) {
            // Specialty icon
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(Color.aurionGold.opacity(0.1))
                    .frame(width: 44, height: 44)
                Image(systemName: specialtyIcon)
                    .font(.title3)
                    .foregroundColor(.aurionGold)
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(displaySpecialty)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundColor(.aurionTextPrimary)
                Text(displayDate)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()

            Text(stateBadge.text)
                .font(.caption2)
                .fontWeight(.medium)
                .foregroundColor(stateBadge.color)
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(stateBadge.color.opacity(0.1))
                .cornerRadius(8)
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 16)
        .background(Color.aurionCardBackground)
        .cornerRadius(12)
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
