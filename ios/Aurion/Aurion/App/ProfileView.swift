import SwiftUI

/// User profile and account management — Quebec Law 25 compliant.
/// Provides: account info, voice profile, privacy controls, consent history, session history.
struct ProfileView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var appLock: AppLockManager
    @EnvironmentObject var tour: TourCoordinator
    /// Whether a biometric "remember me" login is saved — drives the Forget
    /// row in Security. Seeded from the Keychain; cleared in place on tap.
    @State private var hasSavedLogin = KeychainHelper.shared.hasBiometricCredential()
    @State private var showDeleteConfirmation = false
    @State private var showDataExport = false
    @State private var isLoadingData = false
    @State private var myData: MyDataResponse?
    @State private var consentEvents: [ConsentEvent] = []
    @State private var sessionHistory: [SessionHistoryItem] = []
    @State private var error: String?
    // appLanguage binding comes from appState
    @State private var showTeamMemberEditor = false
    // Notification preferences are persisted to UserDefaults (mirrors the
    // RecordingPreferences load/persist shape) — previously these were
    // seeded `true` in @State and never read or saved, so flipping the
    // toggles was a no-op that reset on next launch.
    @State private var notificationPrefs = NotificationPreferences.load()
    // Session history is loaded from the real `/sessions` endpoint. These
    // flags drive the loading spinner + retry affordance so the section
    // reads as fetching → real data | empty | failed, never fake rows.
    @State private var isLoadingSessions = false
    @State private var sessionLoadFailed = false

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
        localizedSpecialty(appState.physicianProfile?.primarySpecialty ?? "general")
    }

    private var displayPracticeType: String {
        localizedPracticeType(appState.physicianProfile?.practiceType ?? "clinic")
    }

    var body: some View {
        NavigationStack {
            content
        }
    }

    private var content: some View {
        // `.contentMargins(.bottom, 24, for: .scrollContent)` keeps the
        // last row breathing-room above the translucent tab bar so the
        // final cell doesn't read as clipped under the bar.
        listBody
            .contentMargins(.bottom, 24, for: .scrollContent)
    }

    private var listBody: some View {
        List {
            // Surface data load / export / delete failures, which were
            // previously set but never shown.
            if let error {
                Section {
                    ErrorBanner(error, onDismiss: { self.error = nil })
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                }
            }

            // ── Account Info ──────────────────────────────────
            Section {
                HStack(spacing: AurionSpacing.md) {
                    AurionAvatar(initials: physicianInitials, size: 64)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(appState.physicianProfile?.displayName ?? L("profile.defaultName"))
                            .aurionFont(18, weight: .semibold, relativeTo: .title3)
                            .foregroundColor(.aurionTextPrimary)
                        Text(displaySpecialty)
                            .aurionFont(13, relativeTo: .footnote)
                            .foregroundColor(.aurionTextSecondary)
                            .padding(.top, 2)
                        Text(displayPracticeType)
                            .aurionFont(12, relativeTo: .caption)
                            .foregroundColor(Color.aurionMutedGray)
                            .padding(.top, 2)
                    }
                }
                .padding(.vertical, AurionSpacing.xs)
            }

            // ── Voice Profile ─────────────────────────────────
            // Card-style row with mic icon, prominent status, and a strong
            // CTA when not enrolled — this is core to the speaker-separation
            // pipeline so it shouldn't read as a buried setting.
            Section {
                if appState.hasVoiceProfile {
                    HStack(spacing: 14) {
                        AurionIconBubble(symbol: "checkmark", tint: .aurionGreen, size: 44, symbolWeight: .bold)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(L("profile.voiceEnrolled"))
                                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextPrimary)
                            Text(L("profile.voiceEnrolledSub"))
                                .aurionFont(12, relativeTo: .caption)
                                .foregroundColor(.aurionTextSecondary)
                                .lineLimit(2)
                        }
                        Spacer()
                    }
                    .padding(.vertical, 6)

                    Button(L("profile.rerecordVoice")) {
                        appState.isOnboardingComplete = false
                    }
                    .foregroundColor(.aurionTextPrimary)

                    Button(L("profile.deleteVoice"), role: .destructive) {
                        KeychainHelper.shared.deleteVoiceEmbedding()
                        AuditLogger.log(event: .voiceProfileDeleted)
                        appState.checkVoiceEnrollment()
                        AurionHaptics.notification(.success)
                    }
                } else {
                    HStack(spacing: 14) {
                        AurionIconBubble(symbol: "mic.fill", tint: .aurionGold, size: 44)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(L("profile.setupVoice"))
                                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextPrimary)
                            Text(L("profile.setupVoiceSub"))
                                .aurionFont(12, relativeTo: .caption)
                                .foregroundColor(.aurionTextSecondary)
                                .lineLimit(2)
                        }
                        Spacer()
                    }
                    .padding(.vertical, 6)

                    Button {
                        appState.isOnboardingComplete = false
                    } label: {
                        HStack {
                            Text(L("profile.startVoice"))
                                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextPrimary)
                            Spacer()
                            Image(systemName: "arrow.right")
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundColor(.aurionGold)
                        }
                        .padding(.vertical, 12)
                        .padding(.horizontal, 14)
                        .background(Color.aurionGold.opacity(0.12))
                        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
                    }
                    .buttonStyle(.plain)
                    .listRowInsets(EdgeInsets(top: 4, leading: 16, bottom: 8, trailing: 16))
                    .listRowBackground(Color.clear)
                }
            } header: {
                SectionHeader(title: L("profile.sectionVoice"))
            }

            // ── Practice Settings ────────────────────────────
            Section {
                LabeledContent(L("profile.practiceType"), value: displayPracticeType)
                LabeledContent(L("profile.primarySpecialty"), value: displaySpecialty)

                if let templates = appState.physicianProfile?.preferredTemplates {
                    LabeledContent(L("profile.preferredTemplates"), value: templates
                        .map { localizedSpecialty($0) }
                        .joined(separator: ", "))
                }

                if let types = appState.physicianProfile?.consultationTypes {
                    LabeledContent(L("profile.visitTypes"), value: types
                        .map { localizedConsultationType($0) }
                        .joined(separator: ", "))
                }

                Button(L("profile.editPractice")) {
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
                    Text(L("profile.noTeam"))
                        .aurionCaption()
                } else {
                    ForEach(team, id: \.name) { member in
                        LabeledContent(member.role.displayFormatted, value: member.name)
                    }
                }

                Button(L("profile.editTeam")) {
                    showTeamMemberEditor = true
                }
                .foregroundColor(.aurionGold)
            } header: {
                SectionHeader(title: L("profile.sectionTeam"))
            }

            // ── Appearance ───────────────────────────────────
            Section {
                Picker(L("profile.appearance"), selection: $appState.appearance) {
                    Text(L("appearance.system")).tag("system")
                    Text(L("appearance.light")).tag("light")
                    Text(L("appearance.dark")).tag("dark")
                }
                .pickerStyle(.segmented)
                .sensoryFeedback(.selection, trigger: appState.appearance)
            } header: {
                SectionHeader(title: L("profile.sectionAppearance"))
            }

            // ── Language ─────────────────────────────────────
            Section {
                Picker(selection: $appState.appLanguage) {
                    Text("🇬🇧 English").tag("en")
                    Text("🇫🇷 Fran\u{00E7}ais").tag("fr")
                } label: {
                    Label(L("profile.appLanguage"), systemImage: "textformat")
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
                    Label(L("profile.noteLanguage"), systemImage: "doc.text")
                        .foregroundColor(.aurionTextPrimary)
                }

                Text(L("profile.languageHelp"))
                    .font(.caption)
                    .foregroundColor(.secondary)
            } header: {
                SectionHeader(title: L("profile.sectionLanguage"))
            }

            // ── Notification Preferences ─────────────────────
            Section {
                Toggle(isOn: $notificationPrefs.sessionAlerts) {
                    Label(L("profile.sessionAlerts"), systemImage: "bell.badge")
                        .foregroundColor(.aurionTextPrimary)
                }
                .tint(.aurionGold)
                .sensoryFeedback(.selection, trigger: notificationPrefs.sessionAlerts)

                Toggle(isOn: $notificationPrefs.noteReadyAlerts) {
                    Label(L("profile.noteReady"), systemImage: "doc.badge.clock")
                        .foregroundColor(.aurionTextPrimary)
                }
                .tint(.aurionGold)
                .sensoryFeedback(.selection, trigger: notificationPrefs.noteReadyAlerts)
            } header: {
                SectionHeader(title: L("profile.sectionNotifications"))
            }

            // ── Security (app lock) ───────────────────────────
            Section {
                Toggle(isOn: $appLock.isEnabled) {
                    Label(L("profile.appLock"), systemImage: "faceid")
                        .foregroundColor(.aurionTextPrimary)
                }
                .tint(.aurionGold)
                .sensoryFeedback(.selection, trigger: appLock.isEnabled)

                if appLock.isEnabled {
                    Picker(selection: $appLock.idleTimeoutSeconds) {
                        ForEach(AppLockManager.timeoutOptions, id: \.self) { secs in
                            Text(L("applock.timeout.\(secs)")).tag(secs)
                        }
                    } label: {
                        Label(L("profile.autoLock"), systemImage: "clock")
                            .foregroundColor(.aurionTextPrimary)
                    }
                }

                if hasSavedLogin {
                    Button(role: .destructive) {
                        KeychainHelper.shared.clearBiometricCredential()
                        withAnimation { hasSavedLogin = false }
                    } label: {
                        Label(L("login.forgetSaved"), systemImage: "person.badge.key")
                    }
                }
            } header: {
                SectionHeader(title: L("profile.sectionSecurity"))
            } footer: {
                Text(L("profile.appLockHelp"))
                    .font(.caption2)
            }

            // ── Help ──────────────────────────────────────────
            Section {
                Button {
                    // Switch to Home so the dashboard anchors exist, then
                    // replay once it's had a moment to lay out.
                    AppNavigation.shared.requestTab(.home)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                        tour.replay()
                    }
                } label: {
                    Label(L("profile.replayTour"), systemImage: "sparkles")
                        .foregroundColor(.aurionTextPrimary)
                }
            } header: {
                SectionHeader(title: L("profile.sectionHelp"))
            }

            // ── Privacy & Data (Law 25) ───────────────────────
            Section {
                Button {
                    loadMyData()
                } label: {
                    Label(L("profile.viewData"), systemImage: "doc.text.magnifyingglass")
                }

                Button {
                    exportMyData()
                } label: {
                    Label(L("profile.exportData"), systemImage: "square.and.arrow.up")
                }

                Button {
                    signOut()
                } label: {
                    Label(L("profile.signOut"), systemImage: "rectangle.portrait.and.arrow.right")
                }

                Button(role: .destructive) {
                    showDeleteConfirmation = true
                } label: {
                    Label(L("profile.deleteAccount"), systemImage: "trash")
                }
            } header: {
                SectionHeader(title: L("profile.sectionPrivacy"))
            } footer: {
                Text(L("profile.privacyFooter"))
                    .font(.caption2)
            }

            // ── Consent History ───────────────────────────────
            Section {
                if consentEvents.isEmpty {
                    Text(L("profile.noConsent"))
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
                SectionHeader(title: L("profile.sectionConsent"), count: consentEvents.isEmpty ? nil : consentEvents.count)
            }

            // ── Session History ───────────────────────────────
            Section {
                if isLoadingSessions {
                    HStack(spacing: AurionSpacing.sm) {
                        ProgressView()
                        Text(L("profile.loadingSessions"))
                            .aurionCaption()
                        Spacer(minLength: 0)
                    }
                } else if sessionLoadFailed {
                    ErrorBanner(
                        L("profile.sessionLoadFailed"),
                        onRetry: { Task { await loadSessionHistory() } },
                        onDismiss: { sessionLoadFailed = false }
                    )
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)
                } else if sessionHistory.isEmpty {
                    Text(L("profile.noSessionHistory"))
                        .aurionCaption()
                } else {
                    ForEach(sessionHistory) { session in
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(localizedSpecialty(session.specialty))
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
                SectionHeader(title: L("profile.sectionSessionHistory"), count: sessionHistory.isEmpty ? nil : sessionHistory.count)
            }

            // ── Legal ─────────────────────────────────────────
            Section {
                Link(destination: URL(string: "https://aurionclinical.com/privacy")!) {
                    Label(L("profile.privacyPolicy"), systemImage: "lock.doc")
                }
                Link(destination: URL(string: "https://aurionclinical.com/terms")!) {
                    Label(L("profile.termsOfService"), systemImage: "doc.plaintext")
                }
                Link(destination: URL(string: "https://aurionclinical.com/biometric-policy")!) {
                    Label(L("profile.biometricPolicy"), systemImage: "faceid")
                }

                // Version info
                VStack(alignment: .leading, spacing: AurionSpacing.xs) {
                    HStack {
                        Text(L("profile.version"))
                            .foregroundColor(.aurionTextPrimary)
                        Spacer()
                        Text("0.1.0")
                            .foregroundColor(.secondary)
                    }
                    HStack {
                        Text(L("profile.build"))
                            .foregroundColor(.aurionTextPrimary)
                        Spacer()
                        Text("1")
                            .foregroundColor(.secondary)
                    }
                    HStack {
                        Text(L("profile.environment"))
                            .foregroundColor(.aurionTextPrimary)
                        Spacer()
                        AurionStatusPill(kind: .conflict, labelOverride: L("profile.development"))
                    }
                }
            } header: {
                SectionHeader(title: L("profile.sectionLegal"))
            }
        }
        .navigationTitle(L("profile.title"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbarBackground(.automatic, for: .navigationBar)
        .onAppear { loadConsentHistory() }
        .task { await loadProfile() }
        .task { await loadSessionHistory() }
        .onChange(of: notificationPrefs) { _, newValue in
            newValue.persist()
        }
        .alert(L("profile.deleteTitle"), isPresented: $showDeleteConfirmation) {
            Button(L("profile.deleteConfirm"), role: .destructive) { deleteAccount() }
            Button(L("profile.deleteCancel"), role: .cancel) {}
        } message: {
            Text(L("profile.deleteMessage"))
        }
        .sheet(isPresented: $showDataExport) {
            if let data = try? JSONEncoder().encode(myData) {
                ShareSheet(items: [data])
            }
        }
        // GH-260 — the "Edit Team Members" button at line ~200 was
        // flipping `showTeamMemberEditor` but nothing was observing
        // it. The editor sheet reads + persists the allied-health
        // team list via the existing `PUT /profile` endpoint;
        // persistence happens on the sheet's own "Done" button so a
        // swipe-dismiss is a true no-op (no audit row).
        .sheet(isPresented: $showTeamMemberEditor) {
            TeamMemberEditorView()
                .environmentObject(appState)
        }
        .overlay {
            if isLoadingData {
                ZStack {
                    Color.black.opacity(0.3).ignoresSafeArea()
                    VStack(spacing: AurionSpacing.sm) {
                        ProgressView()
                        Text(L("profile.loadingData"))
                            .font(.caption)
                            // Adaptive — `.ultraThinMaterial` is a light
                            // frost in light mode (white text invisible)
                            // and a dark frost in dark mode (white text
                            // fine). aurionTextPrimary flips with the
                            // material so the label stays readable
                            // either way. Sibling fix to the
                            // CodingSuggestionsCard #187 regression.
                            .foregroundColor(.aurionTextPrimary)
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
                if let token = KeychainHelper.shared.bearerToken() {
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
                if let token = KeychainHelper.shared.bearerToken() {
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
                if let token = KeychainHelper.shared.bearerToken() {
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
        // There is no dedicated consent-history read endpoint in APIClient —
        // the only consent source is the Law-25 `/privacy/my-data` export,
        // which is an explicit, user-initiated data-access action (the "View
        // My Data" button) and inappropriate to auto-fire on every Profile
        // appear. Until a read endpoint exists, ship an honest empty state in
        // release so the "no consent records" copy is reachable and pilot
        // clinicians never see fabricated history. Sample rows are DEBUG-only,
        // localized, and dated from the active locale so even the dev preview
        // isn't hard-coded English.
        #if DEBUG
        let now = ISO8601DateFormatter().string(from: Date())
        consentEvents = [
            ConsentEvent(
                id: "debug-1",
                type: "biometric_consent_confirmed",
                displayName: L("consent.event.biometric"),
                timestamp: formatRelativeTime(now)
            ),
            ConsentEvent(
                id: "debug-2",
                type: "voice_enrollment_complete",
                displayName: L("consent.event.voiceEnrollment"),
                timestamp: formatRelativeTime(now)
            ),
        ]
        #else
        consentEvents = []
        #endif
    }

    private func loadSessionHistory() async {
        isLoadingSessions = true
        sessionLoadFailed = false
        defer { isLoadingSessions = false }
        do {
            let sessions = try await APIClient.shared.listSessions()
            // Map to the lightweight display model. Dates are formatted with
            // the active app locale (formatRelativeTime reads
            // Localization.locale) so the in-app language picker takes effect.
            sessionHistory = sessions.map { s in
                SessionHistoryItem(
                    id: s.id,
                    specialty: s.specialty,
                    date: formatRelativeTime(s.createdAt),
                    state: s.state
                )
            }
        } catch {
            sessionLoadFailed = true
        }
    }
}

// MARK: - Notification Preferences

/// Per-physician local notification preferences, persisted to UserDefaults.
/// Mirrors ``RecordingPreferences`` (JSON-encoded under a single key) so the
/// load/persist shape is consistent across the app. These gate local UX
/// alerts only — there is no backend field for them yet.
struct NotificationPreferences: Codable, Equatable {
    var sessionAlerts: Bool = true
    var noteReadyAlerts: Bool = true

    private static let key = "aurion.notification_preferences"

    static func load() -> NotificationPreferences {
        guard let data = UserDefaults.standard.data(forKey: key),
              let prefs = try? JSONDecoder().decode(NotificationPreferences.self, from: data) else {
            return NotificationPreferences()
        }
        return prefs
    }

    func persist() {
        guard let data = try? JSONEncoder().encode(self) else { return }
        UserDefaults.standard.set(data, forKey: Self.key)
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
