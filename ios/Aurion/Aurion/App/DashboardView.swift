import SwiftUI

/// Main dashboard — pixel-perfect port of `screens.jsx → DashboardScreen`.
/// Greeting (28pt two-line, Avatar trailing) → Pending Review (gold-accent
/// card) → Quick Start (2×2 grid) → Recent Sessions (compact list).
/// Encounter-type and pre-encounter (context) sheets share the dashboard's
/// state because the design click-thru routes both back here.
struct DashboardView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var sessionManager: SessionManager
    @State private var recentSessions: [SessionResponse] = []
    @State private var isLoadingSessions = false
    @State private var showEncounterTypeSheet = false
    @State private var showContextPrompt = false
    @State private var encounterContext = ""
    @State private var selectedQuickStart: (specialty: String, consultationType: String)?
    @State private var selectedEncounterType = "doctor_patient"
    @State private var selectedParticipants: [[String: Any]] = []

    // MARK: - Greeting

    private var greetingLine1: String {
        let hour = Calendar.current.component(.hour, from: Date())
        switch hour {
        case 0..<12: return L("dashboard.greeting.morning")
        case 12..<17: return L("dashboard.greeting.afternoon")
        default: return L("dashboard.greeting.evening")
        }
    }

    private var doctorLine: String {
        guard let name = appState.physicianProfile?.displayName, !name.isEmpty else { return "" }
        let parts = name.split(separator: " ")
        let last = parts.count > 1 ? String(parts.last!) : name
        return "Dr. \(last)."
    }

    private var avatarInitials: String {
        if let name = appState.physicianProfile?.displayName, !name.isEmpty {
            let parts = name.split(separator: " ")
            if parts.count >= 2 {
                return String(parts[0].prefix(1)) + String(parts[1].prefix(1))
            }
            return String(name.prefix(2))
        }
        return "Dr"
    }

    private var todayCount: Int {
        let calendar = Calendar.current
        let formatter = ISO8601DateFormatter()
        return recentSessions.filter { s in
            guard let d = formatter.date(from: s.createdAt) else { return false }
            return calendar.isDateInToday(d)
        }.count
    }

    private var pendingReviewSessions: [SessionResponse] {
        recentSessions.filter { $0.state == "AWAITING_REVIEW" }
    }

    private var quickStartCards: [(specialty: String, type: String, label: String, icon: String)] {
        let profile = appState.physicianProfile
        let specialty = profile?.primarySpecialty ?? "general"
        let types = profile?.consultationTypes ?? ["new_patient", "follow_up"]
        let icon: String = {
            switch specialty {
            case "orthopedic_surgery": return "figure.walk"
            case "plastic_surgery": return "heart"
            case "musculoskeletal": return "figure.run"
            case "emergency_medicine": return "cross.case"
            default: return "stethoscope"
            }
        }()
        return types.map { type in
            let label: String
            switch type {
            case "new_patient": label = L("quickstart.newPatient")
            case "follow_up": label = L("quickstart.followUp")
            case "pre_op": label = L("quickstart.preOp")
            case "post_op": label = L("quickstart.postOp")
            default: label = type.displayFormatted
            }
            return (specialty, type, label, icon)
        }
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    greetingHeader
                    if !pendingReviewSessions.isEmpty { pendingReviewSection }
                    quickStartSection
                    recentSessionsSection
                }
                .padding(.horizontal, AurionSpacing.edgeIPhone)
                .padding(.top, 8)
                .padding(.bottom, 24)
            }
            .background(Color.aurionBackground)
            .navigationBarHidden(true)
            .task { await loadRecentSessions() }
            .refreshable { await loadRecentSessions() }
            .sheet(isPresented: $showEncounterTypeSheet) { encounterTypeSheet }
            .sheet(isPresented: $showContextPrompt) { encounterContextSheet }
        }
    }

    // MARK: - Greeting (two-line + avatar)

    private var greetingHeader: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 8) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(greetingLine1)
                        .font(.system(size: 28, weight: .bold))
                        .tracking(-0.56)
                        .foregroundColor(.aurionTextPrimary)
                    if !doctorLine.isEmpty {
                        Text(doctorLine)
                            .font(.system(size: 28, weight: .bold))
                            .tracking(-0.56)
                            .foregroundColor(.aurionTextPrimary)
                    }
                }
                Text("\(todayCount) sessions \(L("dashboard.today")) \u{00B7} \(pendingReviewSessions.count) pending review")
                    .font(.system(size: 14))
                    .foregroundColor(.aurionTextSecondary)
            }
            Spacer()
            AurionAvatar(initials: avatarInitials, size: 44)
        }
    }

    // MARK: - Pending Review (gold-accent card)

    private var pendingReviewSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L("dashboard.pendingReview"))
            ForEach(pendingReviewSessions, id: \.id) { session in
                NavigationLink(destination: SessionNoteView(session: session)) {
                    AurionCard(padding: 16, accent: true) {
                        HStack {
                            VStack(alignment: .leading, spacing: 2) {
                                Text(session.specialty.displayFormatted)
                                    .font(.system(size: 16, weight: .semibold))
                                    .foregroundColor(.aurionNavy)
                                Text("Recorded \(formatRelativeTime(session.createdAt))")
                                    .font(.system(size: 13))
                                    .foregroundColor(.aurionTextSecondary)
                            }
                            Spacer()
                            Text(L("sessions.resume"))
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundColor(.aurionNavy)
                                .padding(.horizontal, 14)
                                .padding(.vertical, 6)
                                .background(Color.aurionGold)
                                .clipShape(Capsule())
                        }
                    }
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Quick Start (2×2 grid)

    private var quickStartSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Quick Start")
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                ForEach(quickStartCards, id: \.type) { card in
                    Button {
                        AurionHaptics.impact(.light)
                        selectedQuickStart = (card.specialty, card.type)
                        selectedEncounterType = "doctor_patient"
                        selectedParticipants = []
                        encounterContext = ""
                        showEncounterTypeSheet = true
                    } label: {
                        AurionCard(padding: 14) {
                            VStack(alignment: .leading, spacing: 10) {
                                AurionIconTile(systemName: card.icon, size: 36, active: true)
                                Spacer(minLength: 0)
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(card.specialty.displayFormatted)
                                        .font(.system(size: 11, weight: .semibold))
                                        .tracking(0.6)
                                        .textCase(.uppercase)
                                        .foregroundColor(.aurionTextSecondary)
                                    Text(card.label)
                                        .font(.system(size: 16, weight: .semibold))
                                        .foregroundColor(.aurionNavy)
                                        .lineLimit(2)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: 100, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            if let error = sessionManager.error {
                Text(error)
                    .font(.system(size: 13))
                    .foregroundColor(.aurionRed)
                    .multilineTextAlignment(.center)
                    .frame(maxWidth: .infinity)
            }
        }
    }

    // MARK: - Recent Sessions (compact list inside one card)

    private var recentSessionsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: "Recent Sessions") {
                Text("See all")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.aurionGold)
            }

            if isLoadingSessions {
                HStack { Spacer(); ProgressView(); Spacer() }
                    .padding(.vertical, AurionSpacing.lg)
            } else if recentSessions.isEmpty {
                EmptyStateView(
                    icon: "waveform.path.ecg",
                    title: L("dashboard.noSessions"),
                    subtitle: L("dashboard.noSessionsSub")
                )
            } else {
                AurionCard(padding: 0) {
                    VStack(spacing: 0) {
                        ForEach(Array(recentSessions.prefix(3).enumerated()), id: \.element.id) { index, session in
                            recentSessionRow(session: session)
                            if index < min(recentSessions.count, 3) - 1 {
                                Rectangle().fill(Color.aurionBorder).frame(height: 1).padding(.leading, 60)
                            }
                        }
                    }
                }
            }
        }
    }

    private func recentSessionRow(session: SessionResponse) -> some View {
        let icon: String = {
            switch session.specialty {
            case "plastic_surgery": return "heart"
            case "orthopedic_surgery": return "figure.walk"
            case "musculoskeletal": return "figure.run"
            case "emergency_medicine": return "cross.case"
            default: return "stethoscope"
            }
        }()

        return HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: 9)
                    .fill(Color.aurionSurfaceAlt)
                    .frame(width: 32, height: 32)
                Image(systemName: icon)
                    .font(.system(size: 14))
                    .foregroundColor(.aurionTextSecondary)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(session.specialty.displayFormatted)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.aurionNavy)
                    .lineLimit(1)
                Text(formatRelativeTime(session.createdAt))
                    .font(.system(size: 12))
                    .foregroundColor(.aurionTextSecondary)
                    .lineLimit(1)
            }
            Spacer()
            AurionStatusPill(
                kind: sessionStateKind(session.state),
                labelOverride: sessionStateLabel(session.state)
            )
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
    }

    // MARK: - Encounter Type Sheet (screen 4)

    private var encounterTypeSheet: some View {
        NavigationStack {
            VStack(spacing: 0) {
                AurionNavBar(title: "Encounter Type") {
                    AurionTextButton(label: L("common.cancel")) {
                        showEncounterTypeSheet = false
                    }
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("Who\u{2019}s in the room?")
                                .font(.system(size: 22, weight: .semibold))
                                .tracking(-0.22)
                                .foregroundColor(.aurionNavy)
                            Text("Aurion will adjust capture and consent accordingly.")
                                .font(.system(size: 14))
                                .foregroundColor(.aurionTextSecondary)
                        }
                        .padding(.top, 8)

                        VStack(spacing: 12) {
                            AurionSelectableCard(
                                icon: "person.2",
                                title: "Doctor + Patient",
                                subtitle: "Standard one-on-one visit",
                                selected: selectedEncounterType == "doctor_patient"
                            ) {
                                selectedEncounterType = "doctor_patient"
                                selectedParticipants = []
                            }

                            AurionSelectableCard(
                                icon: "person.3",
                                title: "With Team Member",
                                subtitle: "Nurse or PA also present",
                                selected: selectedEncounterType == "doctor_patient_allied"
                            ) {
                                selectedEncounterType = "doctor_patient_allied"
                            }

                            if selectedEncounterType == "doctor_patient_allied" {
                                alliedHealthPicker
                            }

                            AurionSelectableCard(
                                icon: "graduationcap",
                                title: "With Trainee",
                                subtitle: "Resident, fellow, or student",
                                selected: selectedEncounterType == "doctor_patient_transitory"
                            ) {
                                selectedEncounterType = "doctor_patient_transitory"
                            }

                            if selectedEncounterType == "doctor_patient_transitory" {
                                traineeForm
                            }
                        }
                    }
                    .padding(.horizontal, AurionSpacing.edgeIPhone)
                    .padding(.bottom, 20)
                }

                VStack(spacing: 0) {
                    Rectangle().fill(Color.aurionBorder).frame(height: 1)
                    AurionGoldButton(label: L("setup.continue"), full: true) {
                        showEncounterTypeSheet = false
                        showContextPrompt = true
                    }
                    .padding(.horizontal, AurionSpacing.edgeIPhone)
                    .padding(.vertical, 12)
                    .padding(.bottom, 8)
                }
                .background(Color.aurionCardBackground)
            }
            .background(Color.aurionBackground)
        }
        .presentationDetents([.large])
    }

    private var alliedHealthPicker: some View {
        let team = appState.physicianProfile?.alliedHealthTeam ?? []
        return VStack(alignment: .leading, spacing: 10) {
            if team.isEmpty {
                Text("No team members configured. Add them in Profile settings.")
                    .font(.system(size: 13))
                    .foregroundColor(.aurionTextSecondary)
                    .padding(.horizontal, 12)
            } else {
                ForEach(team, id: \.name) { member in
                    let isChecked = selectedParticipants.contains { ($0["name"] as? String) == member.name }
                    Button {
                        AurionHaptics.selection()
                        if isChecked {
                            selectedParticipants.removeAll { ($0["name"] as? String) == member.name }
                        } else {
                            selectedParticipants.append([
                                "name": member.name,
                                "role": member.role,
                                "is_persistent": true,
                            ])
                        }
                    } label: {
                        HStack(spacing: 10) {
                            ZStack {
                                RoundedRectangle(cornerRadius: 5)
                                    .fill(isChecked ? Color.aurionGold : Color.clear)
                                    .frame(width: 18, height: 18)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 5)
                                            .stroke(isChecked ? Color.aurionGold : Color(red: 198/255, green: 202/255, blue: 210/255), lineWidth: 2)
                                    )
                                if isChecked {
                                    Image(systemName: "checkmark")
                                        .font(.system(size: 10, weight: .bold))
                                        .foregroundColor(.aurionNavy)
                                }
                            }
                            Text("\(member.role.displayFormatted) — \(member.name)")
                                .font(.system(size: 14))
                                .foregroundColor(.aurionNavy)
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.leading, 56)
    }

    @State private var traineeName = ""
    @State private var traineeRole = "resident"

    private var traineeForm: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 10) {
                AurionField(label: "Name", placeholder: "J. Lee", text: $traineeName)
                VStack(alignment: .leading, spacing: 6) {
                    Text("Role")
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(.aurionTextSecondary)
                    Picker("Role", selection: $traineeRole) {
                        Text("Resident").tag("resident")
                        Text("Fellow").tag("fellow")
                        Text("Student").tag("medical_student")
                    }
                    .pickerStyle(.segmented)
                }
            }
            HStack {
                Spacer()
                Button {
                    guard !traineeName.isEmpty else { return }
                    selectedParticipants.append([
                        "name": traineeName,
                        "role": traineeRole,
                        "is_persistent": false,
                    ])
                    traineeName = ""
                } label: {
                    Label("Add", systemImage: "plus.circle")
                        .font(.system(size: 14, weight: .medium))
                        .foregroundColor(.aurionGold)
                }
                .disabled(traineeName.isEmpty || selectedParticipants.count >= 3)
            }
        }
        .padding(.leading, 56)
    }

    // MARK: - Pre-Encounter Context Sheet (screen 5)

    private var encounterContextSheet: some View {
        NavigationStack {
            VStack(spacing: 0) {
                AurionNavBar(title: "Context") {
                    AurionTextButton(label: "Back") {
                        showContextPrompt = false
                        showEncounterTypeSheet = true
                    }
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text("What brings the patient in today?")
                                .font(.system(size: 22, weight: .semibold))
                                .tracking(-0.22)
                                .foregroundColor(.aurionNavy)
                            Text("Optional. Improves note accuracy.")
                                .font(.system(size: 14))
                                .foregroundColor(.aurionTextSecondary)
                        }

                        AurionField(
                            placeholder: "e.g. Right knee pain, 3 weeks post-op meniscus repair.",
                            text: $encounterContext,
                            multiline: true
                        )

                        // Gold tip box
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: "sparkles")
                                .font(.system(size: 18))
                                .foregroundColor(.aurionGoldDark)
                            Text("Aurion uses this to focus the structured note. Stays on-device.")
                                .font(.system(size: 13))
                                .foregroundColor(.aurionStatusPending)
                                .lineSpacing(3)
                        }
                        .padding(14)
                        .background(Color.aurionGoldBg)
                        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
                    }
                    .padding(.horizontal, AurionSpacing.edgeIPhone)
                    .padding(.top, 8)
                    .padding(.bottom, 20)
                }

                VStack(spacing: 8) {
                    Rectangle().fill(Color.aurionBorder).frame(height: 1)
                    AurionGoldButton(label: "Start Session", full: true) {
                        showContextPrompt = false
                        startSession()
                    }
                    .padding(.top, 4)
                    Button {
                        encounterContext = ""
                        showContextPrompt = false
                        startSession()
                    } label: {
                        Text("Skip Context")
                            .font(.system(size: 15, weight: .medium))
                            .foregroundColor(.aurionNavy)
                            .padding(8)
                    }
                    .buttonStyle(.plain)
                }
                .padding(.horizontal, AurionSpacing.edgeIPhone)
                .padding(.bottom, 16)
                .background(Color.aurionCardBackground)
            }
            .background(Color.aurionBackground)
        }
        .presentationDetents([.large])
    }

    // MARK: - Actions

    private func startSession() {
        guard let qs = selectedQuickStart else { return }
        let request = SessionStartRequest(
            specialty: qs.specialty,
            consultationType: qs.consultationType,
            encounterContext: encounterContext.isEmpty ? nil : encounterContext,
            outputLanguage: appState.physicianProfile?.outputLanguage ?? "en",
            encounterType: selectedEncounterType,
            participants: selectedParticipants.isEmpty ? nil : selectedParticipants
        )
        Task { await sessionManager.startNewSession(request) }
    }

    private func loadRecentSessions() async {
        isLoadingSessions = true
        defer { isLoadingSessions = false }
        do {
            recentSessions = try await APIClient.shared.listSessions()
        } catch {
            recentSessions = []
        }
    }
}
