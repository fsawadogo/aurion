import SwiftUI

/// Main dashboard — shown after onboarding. Start new sessions here.
struct DashboardView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var sessionManager: SessionManager
    @State private var selectedSpecialty = "orthopedic_surgery"
    @State private var recentSessions: [SessionResponse] = []
    @State private var isLoadingSessions = false

    private let specialties = [
        ("orthopedic_surgery", "Orthopedic Surgery"),
        ("plastic_surgery", "Plastic Surgery"),
        ("musculoskeletal", "Musculoskeletal"),
        ("emergency_medicine", "Emergency Medicine"),
        ("general", "General"),
    ]

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 0..<12: return "Good morning, Dr."
        case 12..<17: return "Good afternoon, Dr."
        default: return "Good evening, Dr."
        }
    }

    private var sessionCount: String {
        "\(recentSessions.count)"
    }

    private var avgScore: String {
        guard !recentSessions.isEmpty else { return "—" }
        // Placeholder — real score would come from pilot metrics
        return "—"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    Text(greeting)
                        .aurionHeadline()
                        .frame(maxWidth: .infinity, alignment: .leading)

                    // Welcome card
                    VStack(spacing: 12) {
                        Image(systemName: "waveform.circle.fill")
                            .font(.system(size: 48))
                            .foregroundColor(Color.aurionGold)

                        Text("Ready to capture")
                            .font(.title2)
                            .fontWeight(.bold)
                            .foregroundColor(.white)

                        if appState.hasVoiceProfile {
                            Label("Voice profile active", systemImage: "checkmark.circle.fill")
                                .font(.caption)
                                .foregroundColor(.white.opacity(0.85))
                        } else {
                            Label("No voice profile — speaker separation disabled", systemImage: "info.circle")
                                .font(.caption)
                                .foregroundColor(.white.opacity(0.6))
                        }
                    }
                    .padding(20)
                    .frame(maxWidth: .infinity)
                    .background(AurionGradients.navyBackground)
                    .cornerRadius(16)

                    // Stat cards — live data
                    HStack(spacing: 16) {
                        statCard(icon: "waveform.path", title: "Sessions", value: sessionCount)
                        statCard(icon: "chart.bar.fill", title: "Avg Score", value: avgScore)
                    }

                    // Recent sessions — from API
                    VStack(alignment: .leading, spacing: 12) {
                        Text("RECENT SESSIONS")
                            .aurionSectionHeader()

                        if isLoadingSessions {
                            HStack {
                                Spacer()
                                ProgressView()
                                Spacer()
                            }
                            .padding(.vertical, 20)
                        } else if recentSessions.isEmpty {
                            Text("No sessions yet — start your first one below")
                                .font(.subheadline)
                                .foregroundColor(.secondary)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 20)
                        } else {
                            ForEach(recentSessions.prefix(5), id: \.id) { session in
                                recentSessionRow(session: session)
                            }
                        }
                    }

                    // New session card
                    VStack(alignment: .leading, spacing: 12) {
                        Text("New Session")
                            .font(.headline)
                            .foregroundColor(.aurionTextPrimary)

                        Picker("Specialty", selection: $selectedSpecialty) {
                            ForEach(specialties, id: \.0) { key, name in
                                Text(name).tag(key)
                            }
                        }
                        .pickerStyle(.menu)

                        Button("Start Session") {
                            AurionHaptics.impact(.medium)
                            Task {
                                await sessionManager.startNewSession(specialty: selectedSpecialty)
                            }
                        }
                        .buttonStyle(AurionPrimaryButtonStyle())

                        if let error = sessionManager.error {
                            Text(error)
                                .font(.caption)
                                .foregroundColor(.red)
                                .multilineTextAlignment(.center)
                        }
                    }
                    .aurionElevatedCard()
                }
                .padding(20)
            }
            .background(Color.aurionBackground)
            .navigationTitle("Aurion")
            .aurionNavBar()
            .task { await loadRecentSessions() }
            .refreshable { await loadRecentSessions() }
        }
    }

    // MARK: - Data Loading

    private func loadRecentSessions() async {
        isLoadingSessions = true
        do {
            recentSessions = try await APIClient.shared.listSessions()
        } catch {
            recentSessions = []
        }
        isLoadingSessions = false
    }

    // MARK: - Stat Card

    private func statCard(icon: String, title: String, value: String) -> some View {
        VStack(spacing: 8) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundColor(Color.aurionGold)
            Text(value)
                .font(.title2)
                .fontWeight(.bold)
                .foregroundColor(.aurionTextPrimary)
            Text(title)
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
        .aurionCard()
    }

    // MARK: - Recent Session Row

    private func recentSessionRow(session: SessionResponse) -> some View {
        let displaySpecialty = session.specialty
            .replacingOccurrences(of: "_", with: " ")
            .capitalized
        let displayDate = formatDate(session.createdAt)
        let stateBadge = badgeForState(session.state)

        return HStack {
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
                .background(stateBadge.color.opacity(0.12))
                .cornerRadius(8)
        }
        .aurionCard()
    }

    private func formatDate(_ iso: String) -> String {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: iso) {
            let display = DateFormatter()
            display.dateStyle = .medium
            display.timeStyle = .short
            return display.string(from: date)
        }
        return iso
    }

    private func badgeForState(_ state: String) -> (text: String, color: Color) {
        switch state {
        case "EXPORTED": return ("Exported", .green)
        case "REVIEW_COMPLETE": return ("Ready", .blue)
        case "PURGED": return ("Archived", .secondary)
        case "PROCESSING_STAGE1": return ("Processing", .aurionAmber)
        case "AWAITING_REVIEW": return ("Review", .aurionGold)
        case "CONSENT_PENDING": return ("Pending", .secondary)
        default: return (state, .secondary)
        }
    }
}
