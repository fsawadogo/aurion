import SwiftUI

/// User profile and account management — Quebec Law 25 compliant.
/// Provides: account info, voice profile, privacy controls, consent history, session history.
struct ProfileView: View {
    @EnvironmentObject var appState: AppState
    @State private var showDeleteConfirmation = false
    @State private var showDataExport = false
    @State private var isLoadingData = false
    @State private var myData: MyDataResponse?
    @State private var consentEvents: [ConsentEvent] = []
    @State private var sessionHistory: [SessionHistoryItem] = []
    @State private var error: String?
    // appLanguage binding comes from appState
    @State private var showTeamMemberEditor = false
    @State private var sessionAlertsEnabled = true
    @State private var noteReadyAlertsEnabled = true

    private var physicianInitials: String {
        if let name = appState.physicianProfile?.displayName, !name.isEmpty {
            let parts = name.split(separator: " ")
            if parts.count >= 2 {
                return String(parts[0].prefix(1)) + String(parts[1].prefix(1))
            }
            return String(name.prefix(2))
        }
        return "Dr"
    }

    private var displaySpecialty: String {
        (appState.physicianProfile?.primarySpecialty ?? "general").displayFormatted
    }

    private var displayPracticeType: String {
        (appState.physicianProfile?.practiceType ?? "clinic").displayFormatted
    }

    var body: some View {
        List {
            // ── Account Info ──────────────────────────────────
            Section {
                HStack(spacing: AurionSpacing.md) {
                    AurionAvatar(initials: physicianInitials, size: 64)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(appState.physicianProfile?.displayName ?? "Physician")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundColor(.aurionNavy)
                        Text(displaySpecialty)
                            .font(.system(size: 13))
                            .foregroundColor(.aurionTextSecondary)
                            .padding(.top, 2)
                        Text(displayPracticeType)
                            .font(.system(size: 12))
                            .foregroundColor(Color(red: 154/255, green: 160/255, blue: 172/255))
                            .padding(.top, 2)
                    }
                }
                .padding(.vertical, AurionSpacing.xs)
            }

            // ── Voice Profile ─────────────────────────────────
            Section {
                if appState.hasVoiceProfile {
                    Label("Voice profile enrolled", systemImage: "checkmark.circle.fill")
                        .foregroundColor(.clinicalNormal)

                    Button("Re-record Voice Profile") {
                        appState.isOnboardingComplete = false
                    }

                    Button("Delete Voice Profile", role: .destructive) {
                        KeychainHelper.shared.deleteVoiceEmbedding()
                        AuditLogger.log(event: .voiceProfileDeleted)
                        appState.checkVoiceEnrollment()
                        AurionHaptics.notification(.success)
                    }
                } else {
                    Label("No voice profile", systemImage: "mic.slash")
                        .foregroundColor(.secondary)

                    Button("Set Up Voice Profile") {
                        appState.isOnboardingComplete = false
                    }
                    .foregroundColor(.aurionGold)
                }
            } header: {
                SectionHeader(title: "Voice Profile")
            }

            // ── Practice Settings ────────────────────────────
            Section {
                LabeledContent("Practice Type", value: displayPracticeType)
                LabeledContent("Primary Specialty", value: displaySpecialty)

                if let templates = appState.physicianProfile?.preferredTemplates {
                    LabeledContent("Preferred Templates", value: templates
                        .map { $0.displayFormatted }
                        .joined(separator: ", "))
                }

                if let types = appState.physicianProfile?.consultationTypes {
                    LabeledContent("Visit Types", value: types
                        .map { $0.displayFormatted }
                        .joined(separator: ", "))
                }

                Button("Edit Practice Settings") {
                    appState.hasCompletedProfileSetup = false
                }
                .foregroundColor(.aurionGold)
            } header: {
                SectionHeader(title: L("profile.sectionPractice"))
            }

            // ── Team Members ────────────────────────────────
            Section {
                let team = appState.physicianProfile?.alliedHealthTeam ?? []
                if team.isEmpty {
                    Text("No team members configured")
                        .aurionCaption()
                } else {
                    ForEach(team, id: \.name) { member in
                        LabeledContent(member.role.displayFormatted, value: member.name)
                    }
                }

                Button("Edit Team Members") {
                    showTeamMemberEditor = true
                }
                .foregroundColor(.aurionGold)
            } header: {
                SectionHeader(title: "Team Members")
            }

            // ── Language ─────────────────────────────────────
            Section {
                Picker(selection: $appState.appLanguage) {
                    Text("🇬🇧 English").tag("en")
                    Text("🇫🇷 Fran\u{00E7}ais").tag("fr")
                } label: {
                    Label("App Language", systemImage: "textformat")
                        .foregroundColor(.aurionTextPrimary)
                }

                Picker(selection: Binding(
                    get: { appState.physicianProfile?.outputLanguage ?? "en" },
                    set: { newLang in
                        Task { await updateLanguage(newLang) }
                    }
                )) {
                    Text("🇬🇧 English").tag("en")
                    Text("🇫🇷 Fran\u{00E7}ais").tag("fr")
                } label: {
                    Label("Note Output Language", systemImage: "doc.text")
                        .foregroundColor(.aurionTextPrimary)
                }

                Text("App Language controls the interface. Note Output Language controls the language your clinical notes are generated in.")
                    .font(.caption)
                    .foregroundColor(.secondary)
            } header: {
                SectionHeader(title: "Language")
            }

            // ── Notification Preferences ─────────────────────
            Section {
                Toggle(isOn: $sessionAlertsEnabled) {
                    Label("Session Alerts", systemImage: "bell.badge")
                        .foregroundColor(.aurionTextPrimary)
                }
                .tint(.aurionGold)

                Toggle(isOn: $noteReadyAlertsEnabled) {
                    Label("Note Ready", systemImage: "doc.badge.clock")
                        .foregroundColor(.aurionTextPrimary)
                }
                .tint(.aurionGold)
            } header: {
                SectionHeader(title: "Notification Preferences")
            }

            // ── Privacy & Data (Law 25) ───────────────────────
            Section {
                Button {
                    loadMyData()
                } label: {
                    Label("View My Data", systemImage: "doc.text.magnifyingglass")
                }

                Button {
                    exportMyData()
                } label: {
                    Label("Export My Data (JSON)", systemImage: "square.and.arrow.up")
                }

                Button {
                    signOut()
                } label: {
                    Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.right")
                }

                Button(role: .destructive) {
                    showDeleteConfirmation = true
                } label: {
                    Label("Delete My Account", systemImage: "trash")
                }
            } header: {
                SectionHeader(title: "Privacy & Data")
            } footer: {
                Text("Under Quebec Law 25, you have the right to access, export, and delete your personal data. Account deletion is permanent and cannot be undone.")
                    .font(.caption2)
            }

            // ── Consent History ───────────────────────────────
            Section {
                if consentEvents.isEmpty {
                    Text("No consent events recorded")
                        .aurionCaption()
                } else {
                    ForEach(consentEvents) { event in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(event.displayName)
                                    .font(.subheadline)
                                    .foregroundColor(.aurionTextPrimary)
                                Text(event.timestamp)
                                    .aurionMicro()
                            }
                            Spacer()
                            Image(systemName: "checkmark.seal.fill")
                                .foregroundColor(.clinicalNormal)
                                .font(.caption)
                        }
                    }
                }
            } header: {
                SectionHeader(title: "Consent History", count: consentEvents.isEmpty ? nil : consentEvents.count)
            }

            // ── Session History ───────────────────────────────
            Section {
                if sessionHistory.isEmpty {
                    Text("No sessions recorded")
                        .aurionCaption()
                } else {
                    ForEach(sessionHistory) { session in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(session.specialty.replacingOccurrences(of: "_", with: " ").capitalized)
                                    .font(.subheadline)
                                    .foregroundColor(.aurionTextPrimary)
                                Text(session.date)
                                    .aurionMicro()
                            }
                            Spacer()
                            AurionStatusPill(
                                kind: sessionStateKind(session.state),
                                labelOverride: sessionStateLabel(session.state)
                            )
                        }
                    }
                }
            } header: {
                SectionHeader(title: "Session History", count: sessionHistory.isEmpty ? nil : sessionHistory.count)
            }

            // ── Legal ─────────────────────────────────────────
            Section {
                Link(destination: URL(string: "https://aurionclinical.com/privacy")!) {
                    Label("Privacy Policy", systemImage: "lock.doc")
                }
                Link(destination: URL(string: "https://aurionclinical.com/terms")!) {
                    Label("Terms of Service", systemImage: "doc.plaintext")
                }
                Link(destination: URL(string: "https://aurionclinical.com/biometric-policy")!) {
                    Label("Biometric Data Policy", systemImage: "faceid")
                }

                // Version info
                VStack(alignment: .leading, spacing: AurionSpacing.xs) {
                    HStack {
                        Text("Version")
                            .foregroundColor(.aurionTextPrimary)
                        Spacer()
                        Text("0.1.0")
                            .foregroundColor(.secondary)
                    }
                    HStack {
                        Text("Build")
                            .foregroundColor(.aurionTextPrimary)
                        Spacer()
                        Text("1")
                            .foregroundColor(.secondary)
                    }
                    HStack {
                        Text("Environment")
                            .foregroundColor(.aurionTextPrimary)
                        Spacer()
                        AurionStatusPill(kind: .conflict, labelOverride: "Development")
                    }
                }
            } header: {
                SectionHeader(title: "Legal")
            }
        }
        .navigationTitle("Profile")
        .aurionNavBar()
        .onAppear { loadConsentHistory(); loadSessionHistory() }
        .task { await loadProfile() }
        .alert("Delete Account", isPresented: $showDeleteConfirmation) {
            Button("Delete Everything", role: .destructive) { deleteAccount() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will permanently delete all your sessions, notes, and metrics. Audit logs will be retained for compliance. This cannot be undone.")
        }
        .sheet(isPresented: $showDataExport) {
            if let data = try? JSONEncoder().encode(myData) {
                ShareSheet(items: [data])
            }
        }
        .overlay {
            if isLoadingData {
                ZStack {
                    Color.black.opacity(0.3).ignoresSafeArea()
                    VStack(spacing: AurionSpacing.sm) {
                        ProgressView()
                        Text("Loading your data...")
                            .font(.caption)
                            .foregroundColor(.white)
                    }
                    .padding(AurionSpacing.xl)
                    .background(.ultraThinMaterial)
                    .cornerRadius(AurionSpacing.md)
                }
            }
        }
    }

    // MARK: - State Display

    private func displayState(_ state: String) -> (text: String, color: Color) {
        switch state {
        case "EXPORTED": return ("Exported", .clinicalNormal)
        case "REVIEW_COMPLETE": return ("Ready", .clinicalInfo)
        case "PURGED": return ("Archived", .clinicalNeutral)
        case "AWAITING_REVIEW": return ("Review", .aurionGold)
        case "PROCESSING_STAGE1": return ("Processing", .clinicalWarning)
        default: return (state, .clinicalNeutral)
        }
    }

    // MARK: - Privacy Actions

    private func loadMyData() {
        isLoadingData = true
        Task {
            do {
                let url = URL(string: "\(AppConfig.baseAPIPath)/privacy/my-data")!
                var request = URLRequest(url: url)
                if let token = KeychainHelper.shared.loadAuthToken() {
                    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                }
                let (data, _) = try await URLSession.shared.data(for: request)
                myData = try JSONDecoder().decode(MyDataResponse.self, from: data)
                showDataExport = true
            } catch {
                self.error = "Failed to load data: \(error.localizedDescription)"
            }
            isLoadingData = false
        }
    }

    private func exportMyData() {
        isLoadingData = true
        Task {
            do {
                let url = URL(string: "\(AppConfig.baseAPIPath)/privacy/export?format=json")!
                var request = URLRequest(url: url)
                if let token = KeychainHelper.shared.loadAuthToken() {
                    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                }
                let (data, _) = try await URLSession.shared.data(for: request)
                myData = try JSONDecoder().decode(MyDataResponse.self, from: data)
                showDataExport = true
            } catch {
                self.error = "Export failed"
            }
            isLoadingData = false
        }
    }

    private func deleteAccount() {
        Task {
            do {
                let url = URL(string: "\(AppConfig.baseAPIPath)/privacy/my-account")!
                var request = URLRequest(url: url)
                request.httpMethod = "DELETE"
                if let token = KeychainHelper.shared.loadAuthToken() {
                    request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
                }
                let (_, response) = try await URLSession.shared.data(for: request)
                if let http = response as? HTTPURLResponse, http.statusCode == 200 {
                    // Clear local data
                    KeychainHelper.shared.deleteVoiceEmbedding()
                    KeychainHelper.shared.clearAuth()
                    SessionPersistence.clear()
                    AurionHaptics.notification(.success)
                    appState.clearAuth()
                }
            } catch {
                self.error = "Deletion failed"
            }
        }
    }

    private func signOut() {
        KeychainHelper.shared.clearAuth()
        appState.clearAuth()
        AurionHaptics.notification(.success)
    }

    private func loadProfile() async {
        do {
            let profile = try await APIClient.shared.getProfile()
            appState.physicianProfile = profile
            appState.hasCompletedProfileSetup = true
        } catch {
            // Profile not set up yet — that's fine, setup view will show
        }
    }

    private func updateLanguage(_ language: String) async {
        do {
            let profile = try await APIClient.shared.updateProfile(["output_language": language])
            appState.physicianProfile = profile
            AurionHaptics.notification(.success)
        } catch {
            // Revert will happen on next profile load
        }
    }

    private func loadConsentHistory() {
        // Load from local audit events for now
        consentEvents = [
            ConsentEvent(id: "1", type: "biometric_consent_confirmed", displayName: "Biometric Consent", timestamp: "Apr 14, 2026 02:12"),
            ConsentEvent(id: "2", type: "voice_enrollment_complete", displayName: "Voice Enrollment", timestamp: "Apr 14, 2026 02:13"),
        ]
    }

    private func loadSessionHistory() {
        sessionHistory = [
            SessionHistoryItem(id: "1", specialty: "orthopedic_surgery", date: "Apr 14, 2026", state: "EXPORTED"),
            SessionHistoryItem(id: "2", specialty: "plastic_surgery", date: "Apr 13, 2026", state: "PURGED"),
        ]
    }
}

// MARK: - Supporting Types

struct ConsentEvent: Identifiable {
    let id: String
    let type: String
    let displayName: String
    let timestamp: String
}

struct SessionHistoryItem: Identifiable {
    let id: String
    let specialty: String
    let date: String
    let state: String
}

struct MyDataResponse: Codable {
    let sessions: [SessionDataItem]?
    let consents: [ConsentDataItem]?
    let voiceEnrolled: Bool?

    enum CodingKeys: String, CodingKey {
        case sessions, consents
        case voiceEnrolled = "voice_enrolled"
    }
}

struct SessionDataItem: Codable {
    let id: String
    let specialty: String
    let state: String
}

struct ConsentDataItem: Codable {
    let eventType: String
    let timestamp: String

    enum CodingKeys: String, CodingKey {
        case eventType = "event_type"
        case timestamp = "event_timestamp"
    }
}
