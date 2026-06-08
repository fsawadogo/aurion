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
    /// Drives the Dynamic Type reflows. At accessibility sizes the Quick
    /// Start grid collapses to a single column and the recent-session row
    /// drops its status pill below the title so nothing clips (#271).
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @State private var recentSessions: [SessionResponse] = []
    @State private var isLoadingSessions = false
    @State private var showEncounterTypeSheet = false
    @State private var showContextPrompt = false
    @State private var encounterContext = ""
    @State private var selectedQuickStart: (specialty: String, consultationType: String)?
    @State private var selectedEncounterType = "doctor_patient"
    @State private var selectedParticipants: [[String: Any]] = []
    @State private var selectedCaptureMode: CaptureMode = .multimodal
    /// #316 (I2) — the physician's saved context picked for this session, or
    /// nil when none is chosen yet / the free-text "Other" path is active.
    /// Drives both the card selection highlight and the `context_id` sent on
    /// Start. Identity compared by ``VisitTypeContext/id`` (local UUID).
    @State private var selectedContext: VisitTypeContext?
    /// True when the physician taps the "Other" escape hatch — reveals the
    /// free-text field (which keeps the 3-char rule) and sends a nil
    /// `context_id` so the backend resolves the specialty-default template.
    @State private var isOtherContextSelected = false
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
        // Shared fractional-tolerant parser (Theme.parseISODate). A bare
        // ISO8601DateFormatter rejects the backend's fractional-seconds
        // timestamps, which made this count always 0 (#279).
        return recentSessions.filter { s in
            guard let d = parseISODate(s.createdAt) else { return false }
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
        Self.quickStartCards(for: appState.physicianProfile)
    }

    /// Derive the Quick Start cards from the physician profile.
    ///
    /// Returns `[]` when `profile` is nil — the caller renders a skeleton
    /// instead of fabricating GENERAL defaults that would start a
    /// "general"-template session for the wrong specialty (#278). When a
    /// profile exists but its `consultationTypes` are empty, fall back to
    /// the two default *types* but keep the profile's real specialty —
    /// never "general".
    ///
    /// Pure + static so it's unit-testable without hosting the view.
    static func quickStartCards(
        for profile: PhysicianProfileResponse?
    ) -> [(specialty: String, type: String, label: String, icon: String)] {
        guard let profile else { return [] }
        let specialty = profile.primarySpecialty
        let types = profile.consultationTypes.isEmpty
            ? ["new_patient", "follow_up"]
            : profile.consultationTypes
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
                    // Single source of truth for session errors. Previously
                    // rendered in BOTH resumableSection and quickStartSection,
                    // so one failure surfaced two identical banners. Hoisted
                    // here so it shows exactly once regardless of which
                    // section triggered it.
                    if let err = sessionManager.error {
                        ErrorBanner(err, onDismiss: { sessionManager.error = nil })
                    }
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
            .task { await loadDashboardData() }
            .refreshable { await loadDashboardData() }
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
            .onChange(of: showContextPrompt) { _, presented in
                // Fresh context step every time it opens — clear any prior
                // saved-context pick / "Other" state so a new encounter
                // doesn't inherit the last one's selection (#316).
                if presented {
                    selectedContext = nil
                    isOtherContextSelected = false
                }
            }
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
        }
    }

    // MARK: - Pending Review (gold-accent card)
    //
    // Marie bug-bash (2026-06-05): this section previously used the SAME
    // "Resume" pill label as `resumableSection` above, even though the
    // tap action is completely different — pending-review navigates to
    // `SessionNoteView` (a note-review screen), not back into recording.
    // Marie tapped this card expecting to resume her paused encounter
    // and landed on a blank review screen ("No content captured" per
    // section, because her earlier audio-upload bug had stranded
    // sessions in AWAITING_REVIEW with no note). Pill is now labelled
    // "Review" (`sessions.review`) so the two cards are visually
    // distinct from each other at the glance.
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
                            Text(L("sessions.review"))
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

    /// Grid columns for the Quick Start cards. Two side-by-side columns at
    /// normal text sizes; a single full-width column at accessibility sizes
    /// so the specialty + visit-type labels have room to wrap instead of
    /// being squeezed into a narrow half-width card and clipping (#271 DT).
    private var quickStartColumns: [GridItem] {
        dynamicTypeSize.isAccessibilitySize
            ? [GridItem(.flexible(), spacing: 10)]
            : [GridItem(.flexible(), spacing: 10), GridItem(.flexible(), spacing: 10)]
    }

    private var quickStartSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            SectionHeader(title: L("dashboard.quickStart"))
            // While the profile is still loading (nil), show shimmer
            // placeholders rather than GENERAL fallback cards — tapping a
            // wrong-specialty card would start a "general"-template session
            // for an ortho/plastics surgeon (#278).
            if appState.physicianProfile == nil {
                quickStartSkeleton
            } else {
            LazyVGrid(columns: quickStartColumns, spacing: 10) {
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
                                        // Cap at 2 lines in the 2-up grid, but
                                        // let the label wrap freely in the
                                        // single-column accessibility layout so
                                        // long visit-type names aren't clipped
                                        // (#271 DT).
                                        .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 2)
                                        .fixedSize(horizontal: false, vertical: dynamicTypeSize.isAccessibilitySize)
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
            }
        }
    }

    /// Shimmer placeholder shown while the physician profile is loading
    /// (nil). Mirrors the 2-up Quick Start grid so the layout doesn't jump
    /// when the real cards replace it. Renders no GENERAL fallback (#278).
    private var quickStartSkeleton: some View {
        LazyVGrid(columns: quickStartColumns, spacing: 10) {
            ForEach(0..<2, id: \.self) { _ in
                AurionCard(padding: 14) {
                    VStack(alignment: .leading, spacing: 10) {
                        AurionSkeleton(cornerRadius: AurionRadius.sm)
                            .frame(width: 36, height: 36)
                        Spacer(minLength: 0)
                        AurionSkeleton().frame(width: 70, height: 10)
                        AurionSkeleton().frame(width: 110, height: 14)
                    }
                    .frame(maxWidth: .infinity, minHeight: 100, alignment: .leading)
                }
            }
        }
        .accessibilityLabel(L("dashboard.quickStart"))
        .accessibilityHint(L("common.loading"))
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
                            // The row reads as a tappable card but did nothing
                            // on tap. Mirror `pendingReviewSection` — route the
                            // tap into the session's note via NavigationLink
                            // inside the dashboard's own NavigationStack.
                            NavigationLink(destination: SessionNoteView(session: session)) {
                                recentSessionRow(session: session)
                            }
                            .buttonStyle(.plain)
                            if index < min(recentSessions.count, 3) - 1 {
                                Rectangle().fill(Color.aurionBorder).frame(height: 1).padding(.leading, 60)
                            }
                        }
                    }
                }
            }
        }
    }

    @ViewBuilder
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

        let iconBubble = ZStack {
            RoundedRectangle(cornerRadius: 9)
                .fill(Color.aurionSurfaceAlt)
                .frame(width: 32, height: 32)
            Image(systemName: icon)
                .aurionFont(14, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)
        }

        // At accessibility sizes the title is allowed to wrap; otherwise it
        // stays a single line beside the trailing pill (#271 DT).
        let titleStack = VStack(alignment: .leading, spacing: 2) {
            Text(localizedSpecialty(session.specialty))
                .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.aurionTextPrimary)
                .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 1)
                .fixedSize(horizontal: false, vertical: dynamicTypeSize.isAccessibilitySize)
            Text(formatRelativeTime(session.createdAt))
                .aurionFont(12, relativeTo: .caption)
                .foregroundColor(.aurionTextSecondary)
                .lineLimit(1)
        }

        let pill = AurionStatusPill(
            kind: sessionStateKind(session.state),
            labelOverride: sessionStateLabel(session.state)
        )

        Group {
            if dynamicTypeSize.isAccessibilitySize {
                // The title + pill can't coexist on one line at AX sizes —
                // the pill would crush the title to an ellipsis. Drop it
                // below the title/time stack so both read in full (#271 DT).
                HStack(alignment: .top, spacing: 12) {
                    iconBubble
                    VStack(alignment: .leading, spacing: 8) {
                        titleStack
                        pill
                    }
                    Spacer(minLength: 0)
                }
            } else {
                HStack(spacing: 12) {
                    iconBubble
                    titleStack
                    Spacer()
                    pill
                }
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        // The Spacer between the label stack and the status pill otherwise
        // swallows taps; make the whole padded row the hit target so the
        // wrapping NavigationLink fires anywhere on the row.
        .contentShape(Rectangle())
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
                            // The three participant combinations (#321). The
                            // key clinical axis is whether the attending
                            // physician is present — not "what flavor of extra
                            // person is in the room". "Team member(s)" subsumes
                            // nurse / PA / resident / fellow / student.

                            // 1 — Doctor + Patient (standard 1:1, no team).
                            AurionSelectableCard(
                                icon: "person.2",
                                title: L("encounter.doctorPatient.title"),
                                subtitle: L("encounter.doctorPatient.sub"),
                                selected: selectedEncounterType == "doctor_patient"
                            ) {
                                selectedEncounterType = "doctor_patient"
                                selectedParticipants = []
                            }

                            // 2 — Doctor + team member(s) + Patient (attending
                            // present *with* the care team).
                            AurionSelectableCard(
                                icon: "person.3",
                                title: L("encounter.doctorTeam.title"),
                                subtitle: L("encounter.doctorTeam.sub"),
                                selected: selectedEncounterType == "doctor_team_patient"
                            ) {
                                selectedEncounterType = "doctor_team_patient"
                            }

                            if selectedEncounterType == "doctor_team_patient" {
                                teamMemberEntry
                            }

                            // 3 — Team member(s) + Patient (attending NOT
                            // present — a resident / nurse / fellow sees the
                            // patient on their own).
                            AurionSelectableCard(
                                icon: "stethoscope",
                                title: L("encounter.teamOnly.title"),
                                subtitle: L("encounter.teamOnly.sub"),
                                selected: selectedEncounterType == "team_patient"
                            ) {
                                selectedEncounterType = "team_patient"
                            }

                            if selectedEncounterType == "team_patient" {
                                teamMemberEntry
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

    /// Team-member entry shown under both team-including combinations
    /// (#321). "Team member(s)" subsumes the former allied (nurse / PA,
    /// persistent from the profile) and trainee (resident / fellow / student,
    /// ad-hoc) inputs — both collapse here so the clinician can name who is
    /// present regardless of whether the attending is in the room. Choosing
    /// WHICH members from a per-day roster + per-member access is #275; this
    /// only reuses the existing lightweight entry so the capture pill still
    /// shows names.
    private var teamMemberEntry: some View {
        VStack(alignment: .leading, spacing: 14) {
            alliedHealthPicker
            roleChips
            traineeForm
        }
    }

    private var alliedHealthPicker: some View {
        let allTeam = appState.physicianProfile?.alliedHealthTeam ?? []
        // #275 / I2 — only today's roster is selectable. Effective presence
        // is computed server-side (stale dates auto-reset to absent); we
        // filter on it here so combos 2 & 3 show who's actually in the clinic
        // today. When nobody is marked working today we still let the
        // clinician add ad-hoc named members and anonymous role chips below.
        let team = allTeam.filter(\.isWorkingToday)
        return VStack(alignment: .leading, spacing: 10) {
            if allTeam.isEmpty {
                Text(L("encounter.noTeam"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
                    .padding(.horizontal, 12)
            } else if team.isEmpty {
                Text(L("encounter.noneToday"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
                    .padding(.horizontal, 12)
            } else {
                ForEach(team) { member in
                    let isChecked = selectedParticipants.contains {
                        ($0["source"] as? String) == "profile" && ($0["name"] as? String) == member.name
                    }
                    Button {
                        AurionHaptics.selection()
                        if isChecked {
                            selectedParticipants.removeAll {
                                ($0["source"] as? String) == "profile" && ($0["name"] as? String) == member.name
                            }
                        } else {
                            selectedParticipants.append([
                                "name": member.name,
                                "role": member.role,
                                "source": "profile",
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
                                        // Navy-on-gold (fixed) — the gold fill
                                        // is identical in both modes, so an
                                        // adaptive checkmark went white-on-gold
                                        // (washed out) in dark mode (#293).
                                        .foregroundColor(.aurionNavy)
                                        .accessibilityHidden(true)
                                }
                            }
                            Text("\(member.role.displayFormatted) \u{2014} \(member.name)")
                                .aurionFont(14, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextPrimary)
                            Spacer()
                        }
                        .frame(minHeight: 44)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(isChecked ? .isSelected : [])
                }
            }
        }
        .padding(.leading, 56)
    }

    /// Anonymous role chips (#275 — "choose who" item 2). Each toggles a
    /// name-less participant ("a nurse was present") tagged
    /// `source: adhoc_role`, which carries zero PHI. Toggling is idempotent
    /// per role; the existing 3-participant cap still applies — a selected
    /// chip can always be removed, but a new one is blocked at three.
    private struct AnonymousRoleChip: Identifiable {
        let role: String
        let labelKey: String
        var id: String { role }
    }

    private static let anonymousRoleChips: [AnonymousRoleChip] = [
        AnonymousRoleChip(role: "nurse", labelKey: "encounter.role.nurse"),
        AnonymousRoleChip(role: "resident", labelKey: "encounter.role.resident"),
        AnonymousRoleChip(role: "medical_student", labelKey: "encounter.role.student"),
    ]

    private func isRoleChipSelected(_ role: String) -> Bool {
        selectedParticipants.contains {
            ($0["source"] as? String) == "adhoc_role" && ($0["role"] as? String) == role
        }
    }

    private var roleChips: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(L("encounter.anonRoles"))
                .aurionFont(13, weight: .medium, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
            // Flow layout (not a flat HStack) so the three chips wrap to a
            // second row at larger Dynamic Type instead of being squeezed
            // flat and truncating their labels (#271).
            AurionFlowLayout(spacing: 8, lineSpacing: 8) {
                ForEach(Self.anonymousRoleChips) { entry in
                    let selected = isRoleChipSelected(entry.role)
                    let capReached = !selected && selectedParticipants.count >= 3
                    Button {
                        AurionHaptics.selection()
                        if selected {
                            selectedParticipants.removeAll {
                                ($0["source"] as? String) == "adhoc_role"
                                    && ($0["role"] as? String) == entry.role
                            }
                        } else if !capReached {
                            selectedParticipants.append([
                                "role": entry.role,
                                "source": "adhoc_role",
                                "is_persistent": false,
                            ])
                        }
                    } label: {
                        Text(L(entry.labelKey))
                            .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                            .foregroundColor(selected ? .white : .aurionTextPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 7)
                            .background(selected ? Color.aurionNavy : Color.aurionCardBackground)
                            .clipShape(Capsule())
                            .overlay(
                                Capsule().stroke(selected ? .clear : Color.aurionBorder, lineWidth: 1)
                            )
                            .opacity(capReached ? 0.4 : 1)
                    }
                    .buttonStyle(.plain)
                    .disabled(capReached)
                    .accessibilityAddTraits(selected ? [.isSelected, .isButton] : .isButton)
                    .accessibilityHint(capReached ? L("encounter.participantCapReached") : "")
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.leading, 56)
    }

    @State private var traineeName = ""
    @State private var traineeRole = "resident"

    /// Full-text label for an ad-hoc trainee role tag. Used by the role
    /// menu trigger so the selected role always reads in full.
    private func traineeRoleLabel(_ role: String) -> String {
        switch role {
        case "resident": return L("encounter.role.resident")
        case "fellow": return L("encounter.role.fellow")
        case "medical_student": return L("encounter.role.student")
        default: return role.displayFormatted
        }
    }

    private var traineeForm: some View {
        // Name + Role each get their OWN full-width row (#271). The Role
        // control was a `.segmented` Picker squeezed into the right half of
        // an HStack, so its labels truncated to "Resi… / Fellow / Stud…" at
        // larger Dynamic Type. Segmented controls can't wrap or scale, so
        // it's now a menu-style picker whose trigger shows the full role
        // word and whose dropdown lists all three at any text size.
        VStack(alignment: .leading, spacing: 12) {
            AurionField(label: L("encounter.name"), placeholder: L("encounter.namePlaceholder"), text: $traineeName)
            VStack(alignment: .leading, spacing: 6) {
                Text(L("encounter.role"))
                    .aurionFont(13, weight: .medium, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
                Menu {
                    Picker(L("encounter.role"), selection: $traineeRole) {
                        Text(L("encounter.role.resident")).tag("resident")
                        Text(L("encounter.role.fellow")).tag("fellow")
                        Text(L("encounter.role.student")).tag("medical_student")
                    }
                } label: {
                    HStack(spacing: 8) {
                        Text(traineeRoleLabel(traineeRole))
                            .aurionFont(16, relativeTo: .body)
                            .foregroundColor(.aurionTextPrimary)
                            // Let the role word wrap rather than truncate at AX
                            // sizes; the trigger grows vertically to fit.
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.system(size: 12, weight: .semibold))
                            .foregroundColor(.aurionTextSecondary)
                    }
                    .padding(.horizontal, 14)
                    .padding(.vertical, 12)
                    .background(Color.aurionCardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
                    .overlay(
                        RoundedRectangle(cornerRadius: AurionRadius.sm)
                            .stroke(Color.aurionInputBorder, lineWidth: 1)
                    )
                    .contentShape(Rectangle())
                }
                .accessibilityLabel(L("encounter.role"))
                .accessibilityValue(traineeRoleLabel(traineeRole))
            }
            HStack {
                Spacer()
                Button {
                    guard !traineeName.isEmpty else { return }
                    // #275 — a typed-in trainee is an ad-hoc NAMED participant.
                    selectedParticipants.append([
                        "name": traineeName,
                        "role": traineeRole,
                        "source": "adhoc_named",
                        "is_persistent": false,
                    ])
                    traineeName = ""
                } label: {
                    Label(L("common.add"), systemImage: "plus.circle")
                        .aurionFont(14, weight: .medium, relativeTo: .subheadline)
                        .foregroundColor(.aurionGold)
                }
                .disabled(traineeName.isEmpty || selectedParticipants.count >= 3)
                .accessibilityHint(selectedParticipants.count >= 3 ? L("encounter.participantCapReached") : "")
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

                        contextStep

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
                        disabled: !canStartSession
                    ) {
                        showContextPrompt = false
                        startSession()
                    }
                    .padding(.top, 4)
                    if let hint = startDisabledHint {
                        Text(hint)
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

    // MARK: - Context Step (#316, I2)

    /// The physician's saved contexts for the visit type chosen on the Quick
    /// Start card, sourced from the cached profile's `contextsPerVisitType`.
    /// Empty when the visit type has none configured — the UI then falls back
    /// to the legacy free-text-only step.
    private var availableContexts: [VisitTypeContext] {
        guard let type = selectedQuickStart?.consultationType else { return [] }
        return appState.physicianProfile?.contextsPerVisitType[type] ?? []
    }

    /// Routes the context step: curated picker when the chosen visit type has
    /// saved contexts, otherwise today's free-text-only field. Keeping the two
    /// paths in one place means the fallback stays byte-identical to the
    /// pre-#316 behavior when no contexts are configured.
    @ViewBuilder
    private var contextStep: some View {
        if availableContexts.isEmpty {
            legacyContextInput
        } else {
            savedContextPicker
        }
    }

    /// Pre-#316 behavior: a single required free-text field (3-char rule).
    /// Used when the visit type has no saved contexts.
    private var legacyContextInput: some View {
        VStack(alignment: .leading, spacing: 12) {
            contextQuestionHeader(subtitle: L("context.required"))
            AurionField(
                placeholder: L("context.placeholder"),
                text: $encounterContext,
                multiline: true
            )
        }
    }

    /// Curated picker: the visit type's saved contexts as the primary
    /// selectable options, plus an "Other" escape hatch that reveals the
    /// free-text field. Picking a saved context is enough to enable Start;
    /// "Other" retains the 3-char minimum and sends a nil `context_id`.
    private var savedContextPicker: some View {
        VStack(alignment: .leading, spacing: 12) {
            contextQuestionHeader(subtitle: L("context.chooseSub"))

            VStack(spacing: 10) {
                ForEach(availableContexts) { ctx in
                    AurionSelectableCard(
                        title: ctx.label,
                        selected: !isOtherContextSelected && selectedContext?.id == ctx.id
                    ) {
                        selectedContext = ctx
                        isOtherContextSelected = false
                    }
                }

                AurionSelectableCard(
                    icon: "square.and.pencil",
                    title: L("context.other"),
                    subtitle: L("context.otherSub"),
                    selected: isOtherContextSelected
                ) {
                    isOtherContextSelected = true
                    selectedContext = nil
                }

                if isOtherContextSelected {
                    AurionField(
                        placeholder: L("context.placeholder"),
                        text: $encounterContext,
                        multiline: true
                    )
                    .transition(.opacity)
                }
            }
        }
        .animation(AurionAnimation.smooth, value: isOtherContextSelected)
    }

    /// Shared "What brings the patient in today? •" title with a swappable
    /// sub-line (required vs. choose-or-describe).
    private func contextQuestionHeader(subtitle: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            // firstTextBaseline keeps the gold "required" bullet riding the
            // first line when the question wraps at larger Dynamic Type; the
            // fixedSize lets the title grow vertically instead of clipping.
            HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(L("context.question"))
                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                    .tracking(-0.22)
                    .foregroundColor(.aurionTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Text("•")
                    .aurionFont(22, weight: .semibold, relativeTo: .title2)
                    .foregroundColor(.aurionGold)
            }
            Text(subtitle)
                .aurionFont(14, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)
        }
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
    /// the note template against. Gates the free-text paths (legacy + "Other").
    private var hasMinimumContext: Bool {
        encounterContext.trimmingCharacters(in: .whitespacesAndNewlines).count >= 3
    }

    /// True when picking a saved context is a live option for this session
    /// (the chosen visit type has at least one) AND one is currently selected.
    private var hasSavedContextSelection: Bool {
        !availableContexts.isEmpty && !isOtherContextSelected && selectedContext != nil
    }

    /// Whether Start is enabled. A picked saved context is enough on its own
    /// (#316) — no 3-char gate. The free-text paths (legacy field, or "Other")
    /// still require the 3-char minimum.
    private var canStartSession: Bool {
        if hasSavedContextSelection { return true }
        // Saved contexts exist but none picked AND "Other" not chosen → block.
        if !availableContexts.isEmpty && !isOtherContextSelected { return false }
        return hasMinimumContext
    }

    /// Sub-button hint shown while Start is disabled, nil once it's enabled.
    /// Tells the physician whether to pick a context or type a few words.
    private var startDisabledHint: String? {
        if canStartSession { return nil }
        if !availableContexts.isEmpty && !isOtherContextSelected {
            return L("context.selectHint")
        }
        return L("context.minHint")
    }

    // MARK: - Actions

    private func startSession() {
        guard let qs = selectedQuickStart else { return }
        // Defensive — UI already blocks Start when the context step is
        // incomplete, but if somehow we get here without it, bail rather than
        // ship a contextless session to the backend.
        guard canStartSession else { return }
        // A picked saved context contributes its label (the existing free-text
        // ENCOUNTER CONTEXT field) AND its server id (#316). The "Other" /
        // legacy paths send the typed free text and a nil context_id, so the
        // backend resolves the specialty-default template.
        let encounterLabel: String
        let contextId: String?
        if hasSavedContextSelection, let ctx = selectedContext {
            encounterLabel = ctx.label
            contextId = ctx.serverID.isEmpty ? nil : ctx.serverID
        } else {
            encounterLabel = encounterContext.trimmingCharacters(in: .whitespacesAndNewlines)
            contextId = nil
        }
        let request = SessionStartRequest(
            specialty: qs.specialty,
            consultationType: qs.consultationType,
            encounterContext: encounterLabel,
            outputLanguage: appState.physicianProfile?.outputLanguage ?? "en",
            encounterType: selectedEncounterType,
            participants: selectedParticipants.isEmpty ? nil : selectedParticipants,
            captureMode: selectedCaptureMode,
            contextId: contextId
        )
        Task { await sessionManager.startNewSession(request) }
    }

    /// Dashboard appear / pull-to-refresh entry point. Self-heals a missing
    /// profile (e.g. if the launch-time fetch in `AurionApp` failed) so the
    /// Quick Start grid recovers its real specialty + visit types instead of
    /// staying on the skeleton/GENERAL fallback (#278), then loads sessions.
    private func loadDashboardData() async {
        if appState.physicianProfile == nil {
            appState.physicianProfile = try? await APIClient.shared.getProfile()
        }
        await loadRecentSessions()
    }

    private func loadRecentSessions() async {
        isLoadingSessions = true
        defer { isLoadingSessions = false }
        do {
            recentSessions = try await APIClient.shared.listSessions()
        } catch {
            recentSessions = []
        }
        // Publish the awaiting-review count to the shared nav bus so the
        // Sessions tab badge stays in step with this list (#300).
        navigation.pendingReviewCount = pendingReviewSessions.count
    }
}
