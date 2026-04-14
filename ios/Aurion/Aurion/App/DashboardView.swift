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

    // MARK: - Computed Properties

    private var greeting: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 0..<12: return "Good morning, Dr."
        case 12..<17: return "Good afternoon, Dr."
        default: return "Good evening, Dr."
        }
    }

    private var totalSessionCount: Int {
        recentSessions.count
    }

    private var thisWeekCount: Int {
        let calendar = Calendar.current
        let now = Date()
        let formatter = ISO8601DateFormatter()
        return recentSessions.filter { session in
            guard let date = formatter.date(from: session.createdAt) else { return false }
            return calendar.isDate(date, equalTo: now, toGranularity: .weekOfYear)
        }.count
    }

    private var pendingCount: Int {
        recentSessions.filter { $0.state == "AWAITING_REVIEW" }.count
    }

    private var avgScore: String {
        guard !recentSessions.isEmpty else { return "--" }
        return "--"
    }

    /// Mock weekly data for the mini chart (Mon-Sun)
    private var weeklyBarHeights: [CGFloat] {
        [0.4, 0.7, 0.5, 0.9, 0.6, 0.3, 0.2]
    }

    private let weekDayLabels = ["M", "T", "W", "T", "F", "S", "S"]

    // MARK: - Body

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: AurionSpacing.xl) {

                    // Greeting
                    Text(greeting)
                        .aurionDisplay()
                        .frame(maxWidth: .infinity, alignment: .leading)

                    // Welcome card
                    welcomeCard

                    // Metric cards — 2x2 grid
                    metricGrid

                    // Mini weekly chart
                    weeklyChart

                    // Recent sessions
                    recentSessionsSection

                    // New session card
                    newSessionCard
                }
                .padding(AurionSpacing.lg)
            }
            .background(Color.aurionBackground)
            .navigationTitle("Aurion")
            .aurionNavBar()
            .task { await loadRecentSessions() }
            .refreshable { await loadRecentSessions() }
        }
    }

    // MARK: - Welcome Card

    private var welcomeCard: some View {
        VStack(spacing: AurionSpacing.sm) {
            Image(systemName: "waveform.circle.fill")
                .font(.system(size: 44))
                .foregroundColor(Color.aurionGold)

            if totalSessionCount > 0 {
                Text("You've captured \(totalSessionCount) session\(totalSessionCount == 1 ? "" : "s")")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(.white)
            } else {
                Text("Ready to capture")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(.white)
            }

            if appState.hasVoiceProfile {
                Label("Voice profile active", systemImage: "checkmark.circle.fill")
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.85))
            } else {
                Label("No voice profile -- speaker separation disabled", systemImage: "info.circle")
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.6))
            }
        }
        .padding(AurionSpacing.xl)
        .frame(maxWidth: .infinity)
        .background(AurionGradients.navyBackground)
        .cornerRadius(16)
    }

    // MARK: - Metric Grid

    private var metricGrid: some View {
        let columns = [
            GridItem(.flexible(), spacing: AurionSpacing.md),
            GridItem(.flexible(), spacing: AurionSpacing.md),
        ]

        return LazyVGrid(columns: columns, spacing: AurionSpacing.md) {
            MetricCard(
                title: "Sessions",
                value: "\(totalSessionCount)",
                icon: "waveform.path"
            )
            MetricCard(
                title: "This Week",
                value: "\(thisWeekCount)",
                icon: "calendar"
            )
            MetricCard(
                title: "Pending",
                value: "\(pendingCount)",
                icon: "clock.arrow.circlepath",
                trend: pendingCount > 0 ? "\(pendingCount)" : nil
            )
            MetricCard(
                title: "Avg Score",
                value: avgScore,
                icon: "chart.bar.fill"
            )
        }
    }

    // MARK: - Weekly Chart

    private var weeklyChart: some View {
        VStack(alignment: .leading, spacing: AurionSpacing.sm) {
            SectionHeader(title: "This Week")

            HStack(alignment: .bottom, spacing: AurionSpacing.xs) {
                ForEach(0..<7, id: \.self) { index in
                    VStack(spacing: AurionSpacing.xxs) {
                        RoundedRectangle(cornerRadius: 3)
                            .fill(
                                LinearGradient(
                                    colors: [Color.aurionGold, Color.aurionGoldLight],
                                    startPoint: .bottom,
                                    endPoint: .top
                                )
                            )
                            .frame(height: weeklyBarHeights[index] * 48)

                        Text(weekDayLabels[index])
                            .aurionMicro()
                    }
                    .frame(maxWidth: .infinity)
                }
            }
            .frame(height: 64)
        }
        .aurionCard()
    }

    // MARK: - Recent Sessions

    private var recentSessionsSection: some View {
        VStack(alignment: .leading, spacing: AurionSpacing.sm) {
            SectionHeader(title: "Recent Sessions", count: recentSessions.isEmpty ? nil : recentSessions.count)

            if isLoadingSessions {
                HStack {
                    Spacer()
                    ProgressView()
                    Spacer()
                }
                .padding(.vertical, AurionSpacing.lg)
            } else if recentSessions.isEmpty {
                EmptyStateView(
                    icon: "waveform.path.ecg",
                    title: "No sessions yet",
                    subtitle: "Start your first clinical session below"
                )
            } else {
                ForEach(recentSessions.prefix(5), id: \.id) { session in
                    recentSessionRow(session: session)
                }
            }
        }
    }

    // MARK: - New Session Card

    private var newSessionCard: some View {
        VStack(alignment: .leading, spacing: AurionSpacing.sm) {
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
                    .foregroundColor(.clinicalAlert)
                    .multilineTextAlignment(.center)
            }
        }
        .aurionElevatedCard()
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

    // MARK: - Recent Session Row

    private func recentSessionRow(session: SessionResponse) -> some View {
        let displaySpecialty = session.specialty
            .replacingOccurrences(of: "_", with: " ")
            .capitalized
        let displayDate = formatDate(session.createdAt)
        let badge = badgeForState(session.state)

        return HStack(spacing: AurionSpacing.sm) {
            VStack(alignment: .leading, spacing: AurionSpacing.xxs) {
                Text(displaySpecialty)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundColor(.aurionTextPrimary)
                Text(displayDate)
                    .aurionCaption()
            }
            Spacer()
            StatusBadge(text: badge.text, color: badge.color)
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
        case "EXPORTED": return ("Exported", .clinicalNormal)
        case "REVIEW_COMPLETE": return ("Ready", .clinicalInfo)
        case "PURGED": return ("Archived", .clinicalNeutral)
        case "PROCESSING_STAGE1": return ("Processing", .clinicalWarning)
        case "PROCESSING_STAGE2": return ("Enriching", .clinicalWarning)
        case "AWAITING_REVIEW": return ("Review", .aurionGold)
        case "RECORDING": return ("Recording", .clinicalAlert)
        case "PAUSED": return ("Paused", .clinicalWarning)
        case "CONSENT_PENDING": return ("Consent", .clinicalNeutral)
        default: return (state, .clinicalNeutral)
        }
    }
}
