import SwiftUI

/// Main dashboard — pixel-perfect port of `screens.jsx → DashboardScreen`.
/// Greeting (28pt two-line, Avatar trailing) → Pending Review (gold-accent
/// card) → Quick Start (2×2 grid) → Recent Sessions (compact list).
/// Encounter-type and pre-encounter (context) sheets share the dashboard's
/// state because the design click-thru routes both back here.
struct DashboardView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var sessionManager: SessionManager
    @EnvironmentObject var tour: TourCoordinator
    /// Drives the iPad readable-measure clamp. ``.regular`` means
    /// we're on iPad in regular size class — content gets centred
    /// and capped at ~720pt so the dashboard doesn't stretch absurdly
    /// wide. ``.compact`` (iPhone, iPad slide-over) keeps full width.
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @State private var recentSessions: [SessionResponse] = []
    @State private var isLoadingSessions = false
    @State private var showEncounterTypeSheet = false
    @State private var showContextPrompt = false
    @State private var encounterContext = ""
    @State private var selectedQuickStart: (specialty: String, consultationType: String)?
    @State private var selectedEncounterType = "doctor_patient"
    @State private var selectedParticipants: [[String: Any]] = []
    @State private var selectedCaptureMode: CaptureMode = .multimodal
    /// Drives the entrance staircase — flipped true on first appear so the
    /// greeting / quick-start / recent rows spring in 60ms apart instead
    /// of materializing as one block. Stays true for the lifetime of the
    /// view (no need to replay on tab return — feels frantic).
    @State private var dashboardAppeared = false
    /// Smoothly counts up from 0 to `todayCount` so the dashboard reads
    /// "0 sessions" → "12 sessions" with a quick spring rather than
    /// flashing the final value at paint time.
    @State private var displayedTodayCount = 0
    /// Cross-cutting nav bus — ``StartSessionIntent`` publishes a
    /// ``PendingQuickStart`` here when the user invokes "Start an Aurion
    /// session" from Siri / Shortcuts / Spotlight.
    @ObservedObject private var navigation = AppNavigation.shared

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
        return "Dr. \(Self.lastName(from: name))."
    }

    /// Derive a presentable last name from a profile's `displayName`, which
    /// is sometimes a real name ("Marie Gdalevitch") and sometimes the raw
    /// sign-in email ("faical.sawadogo@aurionclinical.com") before the
    /// physician sets a display name during onboarding.
    private static func lastName(from raw: String) -> String {
        // Real name with spaces → last word.
        let words = raw.split(separator: " ")
        if words.count > 1, let last = words.last {
            return last.capitalized
        }
        // Email → strip the domain, split the local part on . _ - and take
        // the last meaningful token (e.g. "faical.sawadogo" → "Sawadogo").
        let local = raw.split(separator: "@").first.map(String.init) ?? raw
        let tokens = local.split(whereSeparator: { ".-_".contains($0) })
        if let last = tokens.last {
            return last.capitalized
        }
        return raw.capitalized
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

    /// Sessions whose Stage 2 visual enrichment is in flight on the
    /// backend (post-`/approve-stage1`, pre-`REVIEW_COMPLETE`). The tile
    /// polls each session's job state and self-promotes when complete.
    private var stage2InProgressSessions: [SessionResponse] {
        recentSessions.filter { $0.state == "PROCESSING_STAGE2" }
    }

    /// Sessions on the backend still in an active capture state. Surfaced at
    /// the top of the dashboard with a Resume CTA so the physician can hop
    /// straight back into `CaptureView` after backgrounding the app.
    private var resumableSessions: [SessionResponse] {
        recentSessions.filter { $0.state == "RECORDING" || $0.state == "PAUSED" }
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
            default: label = localizedConsultationType(type)
            }
            return (specialty, type, label, icon)
        }
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            ScrollViewReader { proxy in
            ScrollView {
                VStack(spacing: 20) {
                    OfflineStatusBanner()
                    greetingHeader
                        .tourAnchor(.greeting)
                        .id(TourAnchor.greeting)
                    if !resumableSessions.isEmpty { resumableSection }
                    if !stage2InProgressSessions.isEmpty { stage2InProgressSection }
                    if !pendingReviewSessions.isEmpty { pendingReviewSection }
                    quickStartSection
                        .tourAnchor(.startSession)
                        .id(TourAnchor.startSession)
                    recentSessionsSection
                        .tourAnchor(.recentSessions)
                        .id(TourAnchor.recentSessions)
                }
                .aurionScreenEdge()
                .padding(.top, 8)
                .padding(.bottom, 24)
                // iPad readable-measure clamp. On iPhone (compact) this
                // is a no-op — `maxWidth: .infinity` lets content fill
                // the screen. On iPad regular the content centres
                // around 720pt so it reads like a focused dashboard,
                // not a stretched phone screen.
                .frame(maxWidth: horizontalSizeClass == .regular ? 720 : .infinity)
                .frame(maxWidth: .infinity)
            }
            // Keeps the recent-sessions card breathing-room above the
            // translucent (iOS 26 glass) tab bar — otherwise the last
            // row reads as clipped under the bar.
            .contentMargins(.bottom, 24, for: .scrollContent)
            .background(Color.aurionBackground)
            .navigationBarHidden(true)
            .task { await loadRecentSessions() }
            .refreshable { await loadRecentSessions() }
            .onAppear {
                // Defer the staircase trigger one runloop so the initial
                // paint is the pre-reveal state — gives the springs a delta.
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                    dashboardAppeared = true
                }
                // First-run coach-mark tour. Delay lets the dashboard finish
                // laying out so the spotlight anchors resolve; the coordinator
                // self-guards against re-firing on later tab returns.
                if !appState.hasSeenTour {
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                        tour.autoStartIfNeeded(seen: appState.hasSeenTour)
                    }
                }
            }
            .onChange(of: todayCount) { _, newCount in
                withAnimation(.interpolatingSpring(stiffness: 100, damping: 18)) {
                    displayedTodayCount = newCount
                }
            }
            .sheet(isPresented: $showEncounterTypeSheet) { encounterTypeSheet }
            .sheet(isPresented: $showContextPrompt) { encounterContextSheet }
            .onChange(of: navigation.pendingQuickStart) { _, request in
                // App Intent or Spotlight asked us to start a session for a
                // specific specialty. Mirror the Quick Start card tap so the
                // encounter-type sheet flow stays the only entry point —
                // consent and encounter context still need their human gate.
                guard let request else { return }
                AurionHaptics.impact(.light)
                selectedQuickStart = (request.specialty, request.consultationType)
                selectedEncounterType = "doctor_patient"
                selectedParticipants = []
                encounterContext = ""
                showEncounterTypeSheet = true
                navigation.clearPendingQuickStart()
            }
            // Smoothly scroll each highlighted section into view as the
            // coach-mark tour advances, so the spotlight always lands on a
            // visible target — notably recent sessions, which can sit below
            // the fold on a tall dashboard.
            .onChange(of: tour.stepIndex) { _, _ in scrollToTourTarget(proxy) }
            .onChange(of: tour.isActive) { _, active in
                if active { scrollToTourTarget(proxy) }
            }
            }
        }
    }

    /// Center the current tour step's target section in the scroll view (the
    /// greeting pins to the top instead, since it's already there). No-op for
    /// the tab-bar step, which has no scroll anchor.
    private func scrollToTourTarget(_ proxy: ScrollViewProxy) {
        guard tour.isActive, let anchor = tour.currentStep.anchor else { return }
        withAnimation(AurionAnimation.smooth) {
            proxy.scrollTo(anchor, anchor: anchor == .greeting ? .top : .center)
        }
    }

    // MARK: - Greeting (two-line + avatar)

    private var greetingHeader: some View {
        HStack(alignment: .top) {
            VStack(alignment: .leading, spacing: 8) {
                VStack(alignment: .leading, spacing: 0) {
                    Text(greetingLine1)
                        .aurionFont(28, weight: .bold, relativeTo: .title)
                        .tracking(-0.56)
                        .foregroundColor(.aurionTextPrimary)
                    if !doctorLine.isEmpty {
                        Text(doctorLine)
                            .aurionFont(28, weight: .bold, relativeTo: .title)
                            .tracking(-0.56)
                            .foregroundColor(.aurionTextPrimary)
                    }
                }
                Text(L("dashboard.sessionSummary", displayedTodayCount, pendingReviewSessions.count))
                    .aurionFont(14, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .contentTransition(.numericText())
                    .animation(AurionAnimation.smooth, value: displayedTodayCount)
            }
            Spacer()
            Button {
                AurionHaptics.impact(.light)
                AppNavigation.shared.requestTab(.profile)
            } label: {
                AurionAvatar(initials: avatarInitials, size: 44)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(L("a11y.openProfile"))
        }
    }

    // MARK: - Continue Recording (active session — RECORDING / PAUSED)

    /// Gold-accent card surfaced when a session is still mid-capture on the
    /// backend. Common path: physician started recording, backgrounded the
    /// app, came back — iOS lost the capture sources but the server row is
    /// still PAUSED/RECORDING. Tap loads it into `SessionManager` and
    /// `ContentView` routes back to `CaptureView`.
    private var resumableSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L("dashboard.continueRecording"))
            ForEach(resumableSessions, id: \.id) { session in
                Button {
                    AurionHaptics.impact(.light)
                    Task { await sessionManager.adoptSession(session) }
                } label: {
                    AurionCard(padding: 16, accent: true) {
                        HStack(spacing: 12) {
                            AurionIconBubble(symbol: "record.circle", tint: .aurionGold, size: 36)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(localizedSpecialty(session.specialty))
                                    .aurionFont(16, weight: .semibold, relativeTo: .body)
                                    .foregroundColor(.aurionTextPrimary)
                                Text(session.state == "PAUSED"
                                     ? L("dashboard.pausedAgo", formatRelativeTime(session.updatedAt))
                                     : L("dashboard.recordingAgo", formatRelativeTime(session.updatedAt)))
                                    .aurionFont(13, relativeTo: .footnote)
                                    .foregroundColor(.aurionTextSecondary)
                            }
                            Spacer()
                            Text(L("sessions.resume"))
                                .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                                // Brand-navy on gold pill — fixed in both modes.
                                .foregroundColor(.aurionNavy)
                                .padding(.horizontal, 14)
                                .padding(.vertical, 6)
                                .background(Color.aurionGold)
                                .clipShape(Capsule())
                        }
                        // Without this, the Spacer area between the label
                        // stack and the Resume pill swallows taps — the
                        // user sees the visual but the Button never fires.
                        .contentShape(Rectangle())
                    }
                }
                .buttonStyle(.plain)
            }
            if let err = sessionManager.error {
                ErrorBanner(err, onDismiss: { sessionManager.error = nil })
            }
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
                                Text(localizedSpecialty(session.specialty))
                                    .aurionFont(16, weight: .semibold, relativeTo: .body)
                                    .foregroundColor(.aurionTextPrimary)
                                Text(L("dashboard.recordedAgo", formatRelativeTime(session.createdAt)))
                                    .aurionFont(13, relativeTo: .footnote)
                                    .foregroundColor(.aurionTextSecondary)
                            }
                            Spacer()
                            Text(L("sessions.resume"))
                                .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                                // Brand-navy on gold pill — fixed in both modes.
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

    // MARK: - Stage 2 in progress (polled tile)
    //
    // Surfaces sessions whose visual enrichment is still running on the
    // backend. Each tile owns its own poll loop (5 s cadence); when a
    // tile reports completion we refresh `recentSessions` so the row
    // moves into Pending Review and the tile drops out.

    private var stage2InProgressSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L("dashboard.stage2InProgress"))
            ForEach(stage2InProgressSessions, id: \.id) { session in
                Stage2DashboardTile(
                    session: session,
                    onCompleted: { Task { await loadRecentSessions() } },
                    onFailed: { Task { await loadRecentSessions() } }
                )
            }
        }
    }

    // MARK: - Quick Start (2×2 grid)

    private var quickStartSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L("dashboard.quickStart"))
            LazyVGrid(columns: [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)], spacing: 10) {
                ForEach(Array(quickStartCards.enumerated()), id: \.element.type) { idx, card in
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
                                    Text(localizedSpecialty(card.specialty))
                                        .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                                        .tracking(0.6)
                                        .textCase(.uppercase)
                                        .foregroundColor(.aurionTextSecondary)
                                    Text(card.label)
                                        .aurionFont(16, weight: .semibold, relativeTo: .body)
                                        .foregroundColor(.aurionTextPrimary)
                                        .lineLimit(2)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: 100, alignment: .leading)
                        }
                    }
                    .buttonStyle(.plain)
                    // Staircase: each card springs in with its own delay so
                    // the 2×2 grid forms instead of slamming on screen.
                    .opacity(dashboardAppeared ? 1 : 0)
                    .offset(y: dashboardAppeared ? 0 : 14)
                    .animation(
                        .interpolatingSpring(stiffness: 220, damping: 22)
                            .delay(0.12 + Double(idx) * 0.08),
                        value: dashboardAppeared
                    )
                    // Announce as one button with a clear action hint rather
                    // than reading the specialty + label as separate fragments.
                    .accessibilityElement(children: .combine)
                    .accessibilityAddTraits(.isButton)
                    .accessibilityHint(L("a11y.startEncounterHint"))
                }
            }
            if let error = sessionManager.error {
                ErrorBanner(error, onDismiss: { sessionManager.error = nil })
            }
        }
    }

    // MARK: - Recent Sessions (compact list inside one card)

    private var recentSessionsSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L("dashboard.recentSessions")) {
                Button {
                    AurionHaptics.impact(.light)
                    AppNavigation.shared.requestTab(.sessions)
                } label: {
                    Text(L("dashboard.seeAll"))
                        .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                        .foregroundColor(.aurionGold)
                }
                .buttonStyle(.plain)
                // Same Spacer-swallows-taps gotcha as the Resume button —
                // the SectionHeader's trailing slot lives next to a layout
                // Spacer; without contentShape the gold text reads but
                // doesn't tap.
                .contentShape(Rectangle())
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
                    .aurionFont(14, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(localizedSpecialty(session.specialty))
                    .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextPrimary)
                    .lineLimit(1)
                Text(formatRelativeTime(session.createdAt))
                    .aurionFont(12, relativeTo: .caption)
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
                AurionNavBar(title: L("encounter.title")) {
                    AurionTextButton(label: L("common.cancel")) {
                        showEncounterTypeSheet = false
                    }
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(L("encounter.whoInRoom"))
                                .aurionFont(22, weight: .semibold, relativeTo: .title2)
                                .tracking(-0.22)
                                .foregroundColor(.aurionTextPrimary)
                            Text(L("encounter.adjustSub"))
                                .aurionFont(14, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextSecondary)
                        }
                        .padding(.top, 8)

                        VStack(spacing: 12) {
                            AurionSelectableCard(
                                icon: "person.2",
                                title: L("encounter.doctorPatient.title"),
                                subtitle: L("encounter.doctorPatient.sub"),
                                selected: selectedEncounterType == "doctor_patient"
                            ) {
                                selectedEncounterType = "doctor_patient"
                                selectedParticipants = []
                            }

                            AurionSelectableCard(
                                icon: "person.3",
                                title: L("encounter.allied.title"),
                                subtitle: L("encounter.allied.sub"),
                                selected: selectedEncounterType == "doctor_patient_allied"
                            ) {
                                selectedEncounterType = "doctor_patient_allied"
                            }

                            if selectedEncounterType == "doctor_patient_allied" {
                                alliedHealthPicker
                            }

                            AurionSelectableCard(
                                icon: "graduationcap",
                                title: L("encounter.trainee.title"),
                                subtitle: L("encounter.trainee.sub"),
                                selected: selectedEncounterType == "doctor_patient_transitory"
                            ) {
                                selectedEncounterType = "doctor_patient_transitory"
                            }

                            if selectedEncounterType == "doctor_patient_transitory" {
                                traineeForm
                            }
                        }
                    }
                    .aurionScreenEdge()
                    .padding(.bottom, 20)
                }

                VStack(spacing: 0) {
                    Rectangle().fill(Color.aurionBorder).frame(height: 1)
                    AurionGoldButton(label: L("setup.continue"), full: true) {
                        showEncounterTypeSheet = false
                        showContextPrompt = true
                    }
                    .aurionScreenEdge()
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
                Text(L("encounter.noTeam"))
                    .aurionFont(13, relativeTo: .footnote)
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
                                            .stroke(isChecked ? Color.aurionGold : Color.aurionInputBorder, lineWidth: 2)
                                    )
                                if isChecked {
                                    Image(systemName: "checkmark")
                                        .font(.system(size: 10, weight: .bold))
                                        .foregroundColor(.aurionTextPrimary)
                                }
                            }
                            Text("\(member.role.displayFormatted) \u{2014} \(member.name)")
                                .aurionFont(14, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextPrimary)
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
                AurionField(label: L("encounter.name"), placeholder: L("encounter.namePlaceholder"), text: $traineeName)
                VStack(alignment: .leading, spacing: 6) {
                    Text(L("encounter.role"))
                        .aurionFont(13, weight: .medium, relativeTo: .footnote)
                        .foregroundColor(.aurionTextSecondary)
                    Picker(L("encounter.role"), selection: $traineeRole) {
                        Text(L("encounter.role.resident")).tag("resident")
                        Text(L("encounter.role.fellow")).tag("fellow")
                        Text(L("encounter.role.student")).tag("medical_student")
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
                    Label(L("common.add"), systemImage: "plus.circle")
                        .aurionFont(14, weight: .medium, relativeTo: .subheadline)
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
                AurionNavBar(title: L("context.title")) {
                    AurionTextButton(label: L("setup.back")) {
                        showContextPrompt = false
                        showEncounterTypeSheet = true
                    }
                }

                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        captureModePicker

                        VStack(alignment: .leading, spacing: 4) {
                            HStack(spacing: 6) {
                                Text(L("context.question"))
                                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                                    .tracking(-0.22)
                                    .foregroundColor(.aurionTextPrimary)
                                Text("•")
                                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                                    .foregroundColor(.aurionGold)
                            }
                            Text(L("context.required"))
                                .aurionFont(14, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextSecondary)
                        }

                        AurionField(
                            placeholder: L("context.placeholder"),
                            text: $encounterContext,
                            multiline: true
                        )

                        // Gold tip box
                        HStack(alignment: .top, spacing: 10) {
                            Image(systemName: "sparkles")
                                .font(.system(size: 18))
                                .foregroundColor(.aurionGoldDark)
                            Text(L("context.tip"))
                                .aurionFont(13, relativeTo: .footnote)
                                .foregroundColor(.aurionStatusPending)
                                .lineSpacing(3)
                        }
                        .padding(14)
                        .background(Color.aurionGoldBg)
                        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
                    }
                    .aurionScreenEdge()
                    .padding(.top, 8)
                    .padding(.bottom, 20)
                }

                VStack(spacing: 8) {
                    Rectangle().fill(Color.aurionBorder).frame(height: 1)
                    AurionGoldButton(
                        label: L("dashboard.startButton"),
                        full: true,
                        disabled: !hasMinimumContext
                    ) {
                        showContextPrompt = false
                        startSession()
                    }
                    .padding(.top, 4)
                    if !hasMinimumContext {
                        Text(L("context.minHint"))
                            .aurionFont(12, relativeTo: .caption)
                            .foregroundColor(.aurionTextSecondary)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal, 8)
                    }
                }
                .aurionScreenEdge()
                .padding(.bottom, 16)
                .background(Color.aurionCardBackground)
            }
            .background(Color.aurionBackground)
        }
        .presentationDetents([.large])
    }

    // MARK: - Capture Mode Picker (in context sheet)

    /// Three-option selector for how Aurion captures this encounter. Echoed
    /// back on the capture screen as a pill so the physician confirms the
    /// chosen mode at a glance. Per-session, not per-profile — common case
    /// is the same physician switching between modes.
    private var captureModePicker: some View {
        VStack(alignment: .leading, spacing: 10) {
            VStack(alignment: .leading, spacing: 4) {
                Text(L("context.captureMode"))
                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                    .tracking(-0.22)
                    .foregroundColor(.aurionTextPrimary)
                Text(L("context.captureModeSub"))
                    .aurionFont(14, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
            }
            VStack(spacing: 10) {
                ForEach(CaptureMode.allCases) { mode in
                    AurionSelectableCard(
                        icon: mode.icon,
                        title: mode.displayName,
                        subtitle: mode.subtitle,
                        selected: selectedCaptureMode == mode
                    ) {
                        selectedCaptureMode = mode
                    }
                }
            }
        }
    }

    // MARK: - Validation

    /// Encounter context is required before a session can start. We enforce
    /// a minimum trimmed length (3 chars) so the field can't be bypassed
    /// with a single space — physicians must give Aurion something to anchor
    /// the note template against.
    private var hasMinimumContext: Bool {
        encounterContext.trimmingCharacters(in: .whitespacesAndNewlines).count >= 3
    }

    // MARK: - Actions

    private func startSession() {
        guard let qs = selectedQuickStart else { return }
        // Defensive — UI already blocks Start Session when context is empty,
        // but if somehow we get here without it, bail rather than ship a
        // contextless session to the backend.
        guard hasMinimumContext else { return }
        let request = SessionStartRequest(
            specialty: qs.specialty,
            consultationType: qs.consultationType,
            encounterContext: encounterContext.trimmingCharacters(in: .whitespacesAndNewlines),
            outputLanguage: appState.physicianProfile?.outputLanguage ?? "en",
            encounterType: selectedEncounterType,
            participants: selectedParticipants.isEmpty ? nil : selectedParticipants,
            captureMode: selectedCaptureMode
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
