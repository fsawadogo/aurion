import SwiftUI

/// Root content view — routes between onboarding, dashboard, capture, review.
/// Uses SessionManager to bridge iOS ↔ backend for the full Journey 1 flow.
struct ContentView: View {
    @EnvironmentObject var appState: AppState
    /// AUTH-UNIVERSAL-LINKS — published token from an inbound reset-
    /// password Universal Link. Drives the full-screen cover below.
    @EnvironmentObject var resetLinkPayload: ResetLinkPayload
    @StateObject private var sessionManager = SessionManager()
    @StateObject private var tour = TourCoordinator()
    /// #65 — Apple Watch companion bridge. Mirrors `sessionManager`'s
    /// state to the wrist and routes wrist commands back through the same
    /// SessionManager path. Dormant (cheap OS no-op) when no watch is paired.
    @StateObject private var watchBridge = WatchSessionBridge()
    @State private var showRecoveryAlert = false
    @State private var recoveredSession: CaptureSession?
    @State private var showSplash = true

    var body: some View {
        ZStack {
            // AUTH-UNIVERSAL-LINKS — preempt every other route when a
            // reset token is on the bus. Previously we relied on a
            // `.fullScreenCover(item:)` lower in this view, but the
            // cover never appeared on cold-launch deep-link taps (Faical
            // 2026-06-06): the cover modifier was applied to the ZStack
            // *after* SwiftUI had already laid out the Auth route, and
            // the binding-derived `item` apparently didn't trigger a
            // re-present in time. Treating the reset screen as the ROOT
            // when a token is present is cheaper to reason about,
            // bypasses every SwiftUI cover-stacking gotcha, and the
            // token-clears-on-dismiss closure walks the user back to
            // the original Sign In route automatically.
            if let token = resetLinkPayload.token {
                ResetPasswordView(token: token) {
                    resetLinkPayload.token = nil
                }
                .transition(.opacity)
            } else if showSplash {
                SplashView(isVisible: $showSplash)
                    .transition(.opacity)
            } else if !appState.isAuthenticated {
                AuthView()
                    .transition(.opacity)
            } else if !appState.isOnboardingComplete {
                OnboardingFlowView()
                    .transition(AurionTransition.fadeSlide)
            } else if !appState.hasCompletedProfileSetup {
                PhysicianProfileSetupView()
                    .transition(AurionTransition.fadeSlide)
            } else if sessionManager.uiState == .noteReady {
                // Stage 1 note delivered — ask physician to review now
                // or save for later.
                NoteReadyView()
                    .transition(AurionTransition.fadeSlide)
                    .environmentObject(sessionManager)
            } else if sessionManager.uiState == .reviewing, let session = sessionManager.session {
                // Review flow — entered either by "Review now" off a fresh
                // Stage 1 note OR by re-opening an AWAITING_REVIEW row from the
                // inbox (#322, `resumeReview`). Gate on `session` (not `note`)
                // so a resumed review whose prefetch missed still mounts;
                // NoteReviewView fetches fresh + shows its own Retry when the
                // passed `initialNote` is nil.
                NoteReviewView(
                    sessionId: session.id,
                    initialNote: sessionManager.note,
                    onDismiss: {
                        // Back = defer (#322). Non-destructive: the session
                        // stays AWAITING_REVIEW server-side and is re-openable
                        // from the inbox. Never destroys the draft.
                        sessionManager.saveForLater()
                        appState.currentSession = nil
                    },
                    onApproved: {
                        // Approve = finalize. Terminal teardown after a
                        // successful two-step approval.
                        sessionManager.endSession()
                        appState.currentSession = nil
                    }
                )
                .transition(AurionTransition.fadeSlide)
            } else if sessionManager.uiState == .postEncounter, let session = sessionManager.session {
                // Post-encounter — confirm template before pipeline.
                PostEncounterView(currentSpecialty: session.specialty, profileLanguage: appState.physicianProfile?.outputLanguage ?? "en")
                    .transition(AurionTransition.fadeSlide)
                    .environmentObject(sessionManager)
            } else if sessionManager.uiState == .processing {
                // Processing — after stop, before note arrives.
                ProcessingView(status: sessionManager.processingStatus)
                    .environmentObject(sessionManager)
                    .transition(.opacity)
            } else if let session = sessionManager.session ?? appState.currentSession {
                // Active capture session
                CaptureView(session: session)
                    .transition(.opacity)
                    .environmentObject(sessionManager)
            } else {
                MainTabView()
                    .transition(AurionTransition.fadeSlide)
                    .environmentObject(sessionManager)
            }
        }
        .animation(AurionAnimation.smooth, value: showSplash)
        .animation(AurionAnimation.smooth, value: appState.isAuthenticated)
        .animation(AurionAnimation.smooth, value: appState.isOnboardingComplete)
        .animation(AurionAnimation.smooth, value: sessionManager.session?.id)
        .animation(AurionAnimation.smooth, value: sessionManager.note?.sessionId)
        .animation(AurionAnimation.smooth, value: sessionManager.uiState)
        // First-run coach-mark tour. Hosted at the root so the scrim can dim
        // the whole app (incl. the tab bar); anchors are published by the
        // dashboard and resolved here into one coordinate space.
        .overlayPreferenceValue(TourAnchorKey.self) { prefs in
            GeometryReader { proxy in
                if tour.isActive {
                    TourOverlay(
                        tour: tour,
                        frames: prefs.reduce(into: [TourAnchor: CGRect]()) { dict, kv in
                            dict[kv.key] = proxy[kv.value]
                        },
                        containerSize: proxy.size
                    )
                    .transition(.opacity)
                }
            }
            .ignoresSafeArea()
            .allowsHitTesting(tour.isActive)
        }
        .environmentObject(tour)
        .onAppear {
            appState.checkVoiceEnrollment()
            checkForCrashRecovery()
            // Persist "seen" only when dismissed with "Don't show again".
            tour.configure { dontShowAgain in
                if dontShowAgain { appState.hasSeenTour = true }
            }
        }
        // (Previously a `.fullScreenCover(item:)` lived here as the
        // primary surface for reset taps. Moved to the ROOT route in
        // the ZStack above after the cover failed to present on cold
        // launches — see the comment up there.)
        .alert(L("recovery.title"), isPresented: $showRecoveryAlert) {
            Button(L("recovery.recover")) {
                guard let session = recoveredSession else { return }
                Task {
                    // Validates against the backend, cold-starts sources,
                    // wires the session into SessionManager so the capture
                    // controls (pause/resume/stop) actually have a target.
                    let ok = await sessionManager.validateRecoveredSession(session)
                    if !ok {
                        SessionPersistence.clear()
                        recoveredSession = nil
                    }
                }
            }
            Button(L("recovery.discard"), role: .destructive) {
                SessionPersistence.clear()
                recoveredSession = nil
            }
        } message: {
            if let session = recoveredSession {
                Text(L("recovery.message", session.specialty.replacingOccurrences(of: "_", with: " ")))
            }
        }
    }

    private func checkForCrashRecovery() {
        if let session = SessionPersistence.restore() {
            recoveredSession = session
            showRecoveryAlert = true
        }
    }
}

/// AUTH-UNIVERSAL-LINKS — Identifiable wrapper for the inbound reset
/// token so `.fullScreenCover(item:)` can drive the reset cover off
/// `ResetLinkPayload.token`. The token itself becomes the identity —
/// two distinct tokens re-present the cover; the same token doesn't.
private struct ResetLinkToken: Identifiable {
    let token: String
    var id: String { token }
}

// MARK: - Processing View (between stop and note delivery)

struct ProcessingView: View {
    let status: String
    @EnvironmentObject var sessionManager: SessionManager
    @EnvironmentObject var appState: AppState

    var body: some View {
        ZStack {
            Color.aurionBackground.ignoresSafeArea()

            // Recorded offline — the encounter is safely on disk and will
            // sync on reconnect. Distinct terminal panel, not a progress ring.
            if sessionManager.stage1Status == .queuedOffline {
                OfflineQueuedPanel {
                    sessionManager.endSession()
                    appState.currentSession = nil
                }
                .padding(.horizontal, 32)
            } else {
                processingBody
            }
        }
    }

    private var processingBody: some View {
        // A non-nil retryPrompt means Stage 1 terminally failed. In that state
        // the progress ring (parked at 95%) and the live "Uploading audio…"
        // subtitle are stale and contradict the error card — so we swap them
        // for a static failure glyph and let the retry card carry the message.
        let isFailed = sessionManager.stage1Status.retryPrompt != nil
        return VStack(spacing: 24) {
            Spacer()

            if isFailed {
                Image(systemName: "exclamationmark.circle")
                    .font(.system(size: 52, weight: .regular))
                    .foregroundColor(.aurionGold)
                    .accessibilityHidden(true)
            } else {
                ZStack {
                    CircularProgressRing(
                        progress: sessionManager.processingProgress,
                        color: .aurionGold,
                        lineWidth: 6,
                        size: 80
                    )
                    // Percentage centered inside the ring — visible
                    // confirmation the app is making progress, not
                    // frozen. Time-based estimate (backend doesn't
                    // emit per-step events today).
                    Text("\(Int(sessionManager.processingProgress * 100))%")
                        .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                        .foregroundColor(.aurionTextPrimary)
                        .monospacedDigit()
                        .accessibilityLabel(
                            Text(L("processing.a11yProgress",
                                   "\(Int(sessionManager.processingProgress * 100))"))
                        )
                }

                Text(L("processing.title"))
                    .aurionHeadline()

                Text(status)
                    .aurionFont(15, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
            }

            // Recorded audio stays in memory while the prompt is
            // visible, so the clinician can re-fire without losing
            // the encounter.
            if let prompt = sessionManager.stage1Status.retryPrompt {
                // For .noAudio, re-uploading the same silent bytes just 422s
                // again — offer "Record again" (discard this session, return to
                // start) instead of a pointless Retry loop. Everything else is
                // genuinely retryable from the on-disk WAV.
                let isNoAudio = sessionManager.lastUploadFailureCategory == .noAudio
                Stage1RetryPrompt(
                    title: prompt.title,
                    detail: prompt.detail,
                    actionLabel: isNoAudio ? L("processing.recordAgain") : L("common.retry"),
                    action: {
                        if isNoAudio {
                            sessionManager.endSession()
                            appState.currentSession = nil
                        } else {
                            Task { await sessionManager.retryStage1() }
                        }
                    }
                )
                .padding(.horizontal, 32)
            }

            if !sessionManager.maskingFailedFrames.isEmpty {
                MaskingRetryPrompt(
                    failedCount: sessionManager.maskingFailedFrames.count,
                    onRetry: { Task { await sessionManager.retryFailedMaskingFrames() } },
                    onSkip: { sessionManager.skipFailedMaskingFrames() }
                )
                .padding(.horizontal, 32)
            }

            Spacer()
        }
    }
}

private struct Stage1RetryPrompt: View {
    let title: String
    let detail: String
    /// Action button label — "Retry" for transient/server failures, "Record
    /// again" for the no-audio case (where re-uploading silence is pointless).
    let actionLabel: String
    let action: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            Text(title)
                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.aurionTextPrimary)
            Text(detail)
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
                .multilineTextAlignment(.center)
            Button(actionLabel, action: action)
                .buttonStyle(.borderedProminent)
        }
        .padding(16)
        .background(Color.aurionBackground.opacity(0.9))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.aurionGold.opacity(0.4), lineWidth: 1)
        )
        .cornerRadius(12)
    }
}

/// Banner shown during processing when one or more frames could not be
/// masked on-device. Bytes are held locally — never transmitted — until the
/// clinician chooses retry or skip.
private struct MaskingRetryPrompt: View {
    let failedCount: Int
    let onRetry: () -> Void
    let onSkip: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            Text(Lplural("masking.notUploaded", failedCount))
                .aurionFont(15, relativeTo: .subheadline)
                .foregroundColor(.aurionTextPrimary)
                .multilineTextAlignment(.center)

            HStack(spacing: 12) {
                Button(L("common.retry"), action: onRetry)
                    .buttonStyle(.borderedProminent)
                Button(L("common.skip"), role: .destructive, action: onSkip)
                    .buttonStyle(.bordered)
            }
        }
        .padding(16)
        .background(Color.aurionBackground.opacity(0.9))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.aurionGold.opacity(0.4), lineWidth: 1)
        )
        .cornerRadius(12)
    }
}

/// Terminal panel shown after a recording is captured with no connectivity.
/// Reassures the physician the encounter is safe and will sync itself; the
/// audio already sits in the on-device `OfflineUploadQueue`.
private struct OfflineQueuedPanel: View {
    let onDone: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            Image(systemName: "checkmark.icloud")
                .font(.system(size: 52, weight: .light))
                .foregroundColor(.aurionGold)
            Text(L("offline.queued.title"))
                .aurionHeadline()
            Text(L("offline.queued.detail"))
                .aurionFont(15, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 16)
            Button(L("common.done"), action: onDone)
                .buttonStyle(.borderedProminent)
                .padding(.top, 4)
        }
        .padding(28)
    }
}

/// Slim banner surfacing connectivity + sync state, driven by the shared
/// reachability monitor and upload queue. Hidden when online with nothing
/// pending. Drop it at the top of any screen (currently the dashboard).
struct OfflineStatusBanner: View {
    @ObservedObject private var reachability = ReachabilityMonitor.shared
    @ObservedObject private var queue = OfflineUploadQueue.shared

    var body: some View {
        if let message {
            HStack(spacing: 10) {
                if queue.isSyncing {
                    ProgressView().controlSize(.small).tint(.white)
                } else {
                    Image(systemName: reachability.isOnline ? "arrow.triangle.2.circlepath" : "wifi.slash")
                        .font(.footnote.weight(.semibold))
                }
                Text(message)
                    .font(.footnote.weight(.medium))
                    .lineLimit(2)
                Spacer(minLength: 0)
            }
            .foregroundColor(.white)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(reachability.isOnline ? Color.aurionGold.opacity(0.9) : Color.secondary)
            .cornerRadius(12)
        }
    }

    /// nil → banner hidden. Offline always shows; online shows only while
    /// there's queued work to sync.
    private var message: String? {
        let count = queue.pending.count
        if !reachability.isOnline {
            return count > 0
                ? Lplural("offline.queued.waiting", count)
                : L("offline.savedLocally")
        }
        if count > 0 {
            return Lplural("offline.syncing", count)
        }
        return nil
    }
}

// MARK: - Auth Container

/// Auth container. Post-AUTH-PIVOT-IOS the backend's `/auth/register`
/// endpoint is gone — admins create accounts through `/admin/users`,
/// not through a self-serve UI — so this view always presents the
/// login screen. The container is kept as the single sign-in entry
/// point so the surrounding view hierarchy (ContentView's auth /
/// onboarding / dashboard switch) doesn't need to change.
struct AuthView: View {
    var body: some View {
        LoginView()
            .transition(.opacity)
    }
}

// MARK: - Premium Login

struct LoginView: View {
    @EnvironmentObject var appState: AppState
    @State private var email = ""
    @State private var password = ""
    @State private var isSigningIn = false
    @State private var loginError: String?
    @State private var loginAppeared = false
    @State private var signInSucceeded = false
    /// Biometric "remember me". `rememberMe` opts a password sign-in into
    /// saving the credential; `hasSavedLogin` controls whether the Face ID
    /// sign-in button is offered. Both seed from the Keychain so a returning
    /// user keeps their choice.
    @State private var rememberMe = KeychainHelper.shared.hasBiometricCredential()
    @State private var hasSavedLogin = KeychainHelper.shared.hasBiometricCredential()
    private let biometricsAvailable = BiometricAuth.isAvailable
    /// Set when the backend responds to `/auth/login` with `mfa_required`.
    /// Drives a full-screen cover sheet with the TOTP challenge form. The
    /// challenge token is a short-lived JWT (5-minute TTL) the backend
    /// hands back; it's worthless without the user's authenticator code.
    @State private var mfaChallenge: MfaChallenge?
    /// Set when the user taps "Forgot password?". Drives a full-screen
    /// cover with the email-link reset form. State lives here so the
    /// dismiss callback can clean it up without leaking through the
    /// LoginView render.
    @State private var showingForgotPassword = false
    // AUTH-UNIVERSAL-LINKS — manual reset-link paste fallback. The user
    // taps "Have a reset link?" → alert → pastes the email URL or token
    // → ResetLinkExtractor parses it → the bus drives the reset surface.
    @State private var showingResetCodePaste = false
    @State private var pastedResetLink = ""
    @State private var pastedResetLinkError: String?
    @EnvironmentObject private var resetLinkPayload: ResetLinkPayload
    @FocusState private var focusedField: Field?

    enum Field { case email, password }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            // #271 — wrap the sign-in column in a scroll view so every control
            // (email, password, Remember-me, Sign In, Forgot password, the
            // reset-link fallback, and Sign in with Face ID) stays reachable at
            // large Dynamic Type. The GeometryReader `minHeight` keeps the card
            // vertically centered (via the Spacers) when it fits and lets the
            // column scroll once it overflows the viewport.
            GeometryReader { proxy in
            ScrollView(showsIndicators: false) {
            VStack(spacing: 0) {
                AurionLogoLockup(size: 1.2, dark: true)
                    .padding(.top, 80)
                    .opacity(loginAppeared ? 1 : 0)
                    .scaleEffect(loginAppeared ? 1 : 0.92)
                    .offset(y: loginAppeared ? 0 : -20)
                    .animation(
                        .interpolatingSpring(stiffness: 180, damping: 22),
                        value: loginAppeared
                    )

                Spacer()

                VStack(spacing: 16) {
                    Text(L("login.signIn"))
                        .aurionFont(20, weight: .semibold, relativeTo: .title3)
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity, alignment: .leading)

                    VStack(spacing: 12) {
                        loginField(
                            label: L("login.email"),
                            text: $email,
                            field: .email,
                            keyboard: .emailAddress,
                            content: .username,
                            submit: .next
                        ) {
                            focusedField = .password
                        }

                        loginField(
                            label: L("login.password"),
                            text: $password,
                            field: .password,
                            secure: true,
                            content: .password,
                            submit: .done
                        ) {
                            Task { await signIn() }
                        }
                    }

                    if biometricsAvailable {
                        // Marie (2026-06-06): at larger Dynamic Type sizes
                        // the SwiftUI `Toggle` truncated the label to
                        // "Remember me wit…" because the trailing switch
                        // control has a fixed intrinsic width and the
                        // label only got whatever was left. Splitting
                        // into an explicit HStack with the label allowed
                        // to wrap vertically (`fixedSize(vertical:true)`)
                        // lets the full "Remember me with Face ID"
                        // string stay visible at any Text Size setting,
                        // including AX5. Pattern mirrors PR #268's
                        // voice-enrollment fix.
                        HStack(alignment: .center, spacing: 12) {
                            Text(L("login.rememberMeWith", BiometricAuth.typeLabel))
                                .aurionFont(13, relativeTo: .footnote)
                                .foregroundColor(.white.opacity(0.85))
                                .fixedSize(horizontal: false, vertical: true)
                                .frame(maxWidth: .infinity, alignment: .leading)
                            Toggle("", isOn: $rememberMe)
                                .labelsHidden()
                                .tint(.aurionGold)
                        }
                    }

                    Button {
                        AurionHaptics.impact(.medium)
                        Task { await signIn() }
                    } label: {
                        HStack(spacing: 10) {
                            if signInSucceeded {
                                Image(systemName: "checkmark.circle.fill")
                                    .font(.system(size: 16, weight: .bold))
                                    .foregroundColor(.aurionNavy)
                                Text(L("login.signedIn"))
                            } else if isSigningIn {
                                ProgressView().tint(.aurionNavy)
                                Text(L("login.signingIn"))
                            } else {
                                Image(systemName: "arrow.right.circle.fill")
                                    .font(.system(size: 16, weight: .semibold))
                                Text(L("login.signIn"))
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .animation(AurionAnimation.smooth, value: isSigningIn)
                        .animation(AurionAnimation.smooth, value: signInSucceeded)
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                    .disabled(isSigningIn || signInSucceeded || email.isEmpty || password.isEmpty)

                    if let loginError {
                        Text(loginError)
                            .aurionFont(12, relativeTo: .caption)
                            .foregroundColor(Color.aurionOnNavyError)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Button {
                        AurionHaptics.selection()
                        showingForgotPassword = true
                    } label: {
                        Text(L("login.forgotPassword.linkText"))
                            .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                            .foregroundColor(.aurionGold)
                            .frame(maxWidth: .infinity, minHeight: AurionSpacing.hitMin, alignment: .leading)
                            .contentShape(Rectangle())
                    }
                    .disabled(isSigningIn || signInSucceeded)

                    // AUTH-UNIVERSAL-LINKS — manual fallback for the
                    // case where the email-tapped Universal Link doesn't
                    // route the user to ``ResetPasswordView`` (Gmail iOS
                    // in-app browser, mis-cached AASA, etc.). Tapping
                    // here surfaces an alert with a TextField; the user
                    // pastes the full reset URL OR just the token, the
                    // extractor parses both shapes, and the reset view
                    // takes over via the same ``ResetLinkPayload`` bus.
                    Button {
                        AurionHaptics.selection()
                        pastedResetLink = ""
                        showingResetCodePaste = true
                    } label: {
                        Text(L("login.resetCode.linkText"))
                            .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                            .foregroundColor(.aurionGold)
                            .underline()
                            .frame(maxWidth: .infinity, minHeight: AurionSpacing.hitMin, alignment: .leading)
                            .contentShape(Rectangle())
                    }
                    .disabled(isSigningIn || signInSucceeded)

                    if hasSavedLogin {
                        biometricSignInSection
                    }

                    Text(L("login.firstTimeHint"))
                        .aurionFont(11, relativeTo: .caption2)
                        .foregroundColor(Color.aurionOnNavyFootnote)
                        .multilineTextAlignment(.leading)
                        .lineSpacing(3)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 4)
                }
                .padding(24)
                .background(Color.white.opacity(0.06))
                .cornerRadius(18)
                .overlay(
                    RoundedRectangle(cornerRadius: 18)
                        .stroke(Color.white.opacity(0.10), lineWidth: 1)
                )
                .padding(.horizontal, 24)
                .opacity(loginAppeared ? 1 : 0)
                .offset(y: loginAppeared ? 0 : 24)
                .animation(
                    .interpolatingSpring(stiffness: 200, damping: 24)
                        .delay(0.18),
                    value: loginAppeared
                )

                Spacer()

                VStack(spacing: 4) {
                    Text(L("login.footer"))
                        .aurionFont(12, relativeTo: .caption)
                        .tracking(0.4)
                        .foregroundColor(Color.aurionOnNavyFootnote)
                    // #352 — discreet build stamp so pilot users can report the
                    // exact version in TestFlight feedback. Reads CFBundle*
                    // from the bundle via AppVersion.
                    Text(AppVersion.displayLabel)
                        .aurionFont(11, relativeTo: .caption2)
                        .foregroundColor(Color.aurionOnNavyFootnote.opacity(0.8))
                }
                .padding(.bottom, 40)
                .opacity(loginAppeared ? 1 : 0)
                .animation(.easeOut(duration: 0.5).delay(0.4), value: loginAppeared)
            }
            .frame(minHeight: proxy.size.height)
            }
            }
        }
        .onAppear {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                loginAppeared = true
            }
        }
        .fullScreenCover(item: $mfaChallenge) { challenge in
            MfaChallengeView(challenge: challenge) { session in
                handleAuthenticatedSession(session)
            } onCancel: {
                mfaChallenge = nil
                isSigningIn = false
            }
        }
        .fullScreenCover(isPresented: $showingForgotPassword) {
            ForgotPasswordView(onDismiss: { showingForgotPassword = false })
        }
        // AUTH-UNIVERSAL-LINKS — manual reset-link paste.
        // Accepts the full URL ``https://portal.aurionclinical.com/reset-password?token=…``
        // OR just the bare token. Synthesises a URL when the user pastes
        // a bare token so ``ResetLinkExtractor`` can run unchanged.
        .alert(
            L("login.resetCode.title"),
            isPresented: $showingResetCodePaste,
            actions: {
                TextField(L("login.resetCode.placeholder"), text: $pastedResetLink)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button(L("login.resetCode.submit")) {
                    let trimmed = pastedResetLink.trimmingCharacters(in: .whitespacesAndNewlines)
                    if let url = URL(string: trimmed), let token = ResetLinkExtractor.token(from: url) {
                        resetLinkPayload.token = token
                    } else if !trimmed.isEmpty,
                              let synthesised = URL(
                                  string: "https://portal.aurionclinical.com/reset-password?token=\(trimmed)"
                              ),
                              let token = ResetLinkExtractor.token(from: synthesised) {
                        resetLinkPayload.token = token
                    } else {
                        pastedResetLinkError = L("login.resetCode.invalid")
                    }
                }
                Button(L("common.cancel"), role: .cancel) {}
            },
            message: {
                Text(pastedResetLinkError ?? L("login.resetCode.message"))
            }
        )
    }

    @ViewBuilder
    private func loginField(
        label: String,
        text: Binding<String>,
        field: Field,
        secure: Bool = false,
        keyboard: UIKeyboardType = .default,
        content: UITextContentType? = nil,
        submit: SubmitLabel,
        onSubmit: @escaping () -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                .tracking(0.5)
                .foregroundColor(Color.aurionOnNavyFootnote)
            Group {
                if secure {
                    SecureField("", text: text)
                } else {
                    TextField("", text: text)
                }
            }
            .focused($focusedField, equals: field)
            // The visible label is a separate Text above, so the field itself
            // has no accessible name — give it one for VoiceOver.
            .accessibilityLabel(label)
            .submitLabel(submit)
            .onSubmit(onSubmit)
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .keyboardType(keyboard)
            .textContentType(content)
            .foregroundColor(.white)
            .tint(.aurionGold)
            .padding(.horizontal, 12)
            .padding(.vertical, 11)
            .background(Color.white.opacity(0.08))
            .cornerRadius(10)
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(Color.white.opacity(focusedField == field ? 0.35 : 0.10), lineWidth: 1)
            )
        }
    }

    /// "or — Sign in with Face ID" block, shown only when a saved login
    /// exists. The Forget link removes the credential without signing in.
    private var biometricSignInSection: some View {
        VStack(spacing: 12) {
            HStack(spacing: 10) {
                Rectangle().fill(Color.white.opacity(0.12)).frame(height: 1)
                Text(L("login.or"))
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(Color.aurionOnNavyFootnote)
                Rectangle().fill(Color.white.opacity(0.12)).frame(height: 1)
            }

            Button {
                AurionHaptics.impact(.medium)
                Task { await signInWithBiometrics() }
            } label: {
                HStack(spacing: 10) {
                    Image(systemName: BiometricAuth.iconName)
                        .aurionFont(18, weight: .semibold, relativeTo: .title3)
                    Text(L("login.signInWith", BiometricAuth.typeLabel))
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                }
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 13)
                .background(Color.white.opacity(0.08))
                .cornerRadius(10)
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color.aurionGold.opacity(0.5), lineWidth: 1)
                )
            }
            .disabled(isSigningIn || signInSucceeded)

            Button {
                forgetSavedLogin()
            } label: {
                Text(L("login.forgetSaved"))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(Color.aurionOnNavyFootnote)
                    .frame(minHeight: AurionSpacing.hitMin)
                    .contentShape(Rectangle())
            }
        }
    }

    @MainActor
    private func signInWithBiometrics() async {
        // Authenticate first (non-blocking system prompt), then unlock the
        // saved token with that same context — no second prompt. A nil
        // context means the user cancelled or auth failed: stay silent and
        // let them retry or use the password form.
        guard let context = await BiometricAuth.authenticate(
            reason: L("login.biometricPrompt")
        ) else { return }
        guard let refreshToken = KeychainHelper.shared.loadBiometricRefreshToken(
            context: context
        ) else { return }

        isSigningIn = true
        loginError = nil
        do {
            // Refresh tokens issued AFTER MFA enrollment carry the
            // MFA claim — there's no second prompt on the biometric
            // path, same property as the legacy Cognito flow had.
            let session = try await AurionAuth.shared.refresh(refreshToken: refreshToken)
            handleAuthenticatedSession(session)
        } catch {
            // Refresh token expired or revoked — drop the stale credential and
            // fall back to the password form.
            isSigningIn = false
            KeychainHelper.shared.clearBiometricCredential()
            withAnimation(AurionAnimation.smooth) {
                hasSavedLogin = false
                rememberMe = false
            }
            loginError = L("login.biometricExpired")
            AurionHaptics.notification(.error)
        }
    }

    private func forgetSavedLogin() {
        KeychainHelper.shared.clearBiometricCredential()
        AurionHaptics.impact(.light)
        withAnimation(AurionAnimation.smooth) {
            hasSavedLogin = false
            rememberMe = false
        }
    }

    @MainActor
    private func signIn() async {
        guard !email.isEmpty, !password.isEmpty else { return }
        isSigningIn = true
        loginError = nil
        do {
            let outcome = try await AurionAuth.shared.signIn(
                email: email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased(),
                password: password
            )
            handleOutcome(outcome)
        } catch {
            isSigningIn = false
            loginError = error.localizedDescription
            AurionHaptics.notification(.error)
        }
    }

    @MainActor
    private func handleOutcome(_ outcome: AurionAuth.SignInOutcome) {
        switch outcome {
        case .authenticated(let session):
            handleAuthenticatedSession(session)
        case .mfaRequired(let challengeToken, let userEmail):
            isSigningIn = false
            mfaChallenge = MfaChallenge(
                challengeToken: challengeToken,
                userEmail: userEmail
            )
        }
    }

    /// Shared tail of the password + biometric + MFA paths. Persists the
    /// biometric "remember me" credential when opted in, then resolves
    /// the canonical user identity via `/auth/me` so AppState wiring
    /// downstream is unchanged from the legacy Cognito flow.
    @MainActor
    private func handleAuthenticatedSession(_ session: AuthSession) {
        // Persist the biometric "remember me" credential when opted in.
        // Skipped on the biometric sign-in path itself (the email field
        // is empty there) — the credential already exists.
        if rememberMe, !email.isEmpty, !session.refreshToken.isEmpty {
            KeychainHelper.shared.saveBiometricCredential(
                refreshToken: session.refreshToken,
                email: email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
            )
        }
        Task {
            do {
                let me = try await APIClient.shared.fetchCurrentUser()
                AurionHaptics.notification(.success)
                isSigningIn = false
                signInSucceeded = true
                mfaChallenge = nil
                try? await Task.sleep(nanoseconds: 600_000_000)
                appState.applyAuth(userId: me.userId, role: me.role)
            } catch {
                isSigningIn = false
                loginError = L("login.backendLookupFailed", error.localizedDescription)
                AurionHaptics.notification(.error)
            }
        }
    }
}
