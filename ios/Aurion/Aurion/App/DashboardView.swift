import SwiftUI

/// Main dashboard — shown after onboarding. Start new sessions here.
struct DashboardView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var sessionManager: SessionManager
    @State private var selectedSpecialty = "orthopedic_surgery"
    @State private var showingNewSession = false

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
        case 0..<12:
            return "Good morning, Dr."
        case 12..<17:
            return "Good afternoon, Dr."
        default:
            return "Good evening, Dr."
        }
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    // Greeting
                    Text(greeting)
                        .aurionHeadline()
                        .frame(maxWidth: .infinity, alignment: .leading)

                    // Welcome card — navy gradient background
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

                    // Stat cards row
                    HStack(spacing: 16) {
                        statCard(icon: "waveform.path", title: "Sessions", value: "12")
                        statCard(icon: "chart.bar.fill", title: "Avg Score", value: "94%")
                    }

                    // Recent sessions section
                    VStack(alignment: .leading, spacing: 12) {
                        Text("RECENT SESSIONS")
                            .aurionSectionHeader()

                        recentSessionRow(
                            specialty: "Orthopedic Surgery",
                            date: "Apr 10, 2026",
                            score: 96
                        )
                        recentSessionRow(
                            specialty: "Plastic Surgery",
                            date: "Apr 9, 2026",
                            score: 91
                        )
                        recentSessionRow(
                            specialty: "Orthopedic Surgery",
                            date: "Apr 8, 2026",
                            score: 94
                        )
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
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    NavigationLink(destination: SettingsView()) {
                        Image(systemName: "gear")
                    }
                }
            }
            .aurionNavBar()
        }
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

    private func recentSessionRow(specialty: String, date: String, score: Int) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(specialty)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundColor(.aurionTextPrimary)
                Text(date)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            Spacer()
            Text("\(score)%")
                .font(.subheadline)
                .fontWeight(.semibold)
                .foregroundColor(score >= 90 ? Color.aurionGold : .secondary)
                .padding(.horizontal, 10)
                .padding(.vertical, 4)
                .background(
                    (score >= 90 ? Color.aurionGold : Color.secondary)
                        .opacity(0.12)
                )
                .cornerRadius(8)
        }
        .aurionCard()
    }
}

// MARK: - Settings

struct SettingsView: View {
    @EnvironmentObject var appState: AppState
    @State private var showDeleteConfirmation = false

    var body: some View {
        List {
            Section("Voice Profile") {
                if appState.hasVoiceProfile {
                    Label("Voice profile enrolled", systemImage: "checkmark.circle.fill")
                        .foregroundColor(.green)

                    Button("Re-record Voice Profile") {
                        // Run enrollment flow again
                    }

                    Button("Delete Voice Profile", role: .destructive) {
                        showDeleteConfirmation = true
                    }
                } else {
                    Label("No voice profile", systemImage: "mic.slash")
                        .foregroundColor(.secondary)

                    Button("Set Up Voice Profile") {
                        appState.isOnboardingComplete = false
                    }
                }
            }

            Section("About") {
                HStack {
                    Text("Version")
                    Spacer()
                    Text("0.1.0")
                        .foregroundColor(.secondary)
                }
            }
        }
        .navigationTitle("Settings")
        .aurionNavBar()
        .alert("Delete Voice Profile", isPresented: $showDeleteConfirmation) {
            Button("Delete", role: .destructive) {
                KeychainHelper.shared.deleteVoiceEmbedding()
                AuditLogger.log(event: .voiceProfileDeleted)
                appState.checkVoiceEnrollment()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will remove your voice profile. Speaker separation will be disabled.")
        }
    }
}
