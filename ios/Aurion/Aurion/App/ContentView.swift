import SwiftUI

/// Root content view — routes between onboarding, dashboard, capture, review.
/// Uses SessionManager to bridge iOS ↔ backend for the full Journey 1 flow.
struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var sessionManager = SessionManager()
    @StateObject private var tour = TourCoordinator()
    @State private var showRecoveryAlert = false
    @State private var recoveredSession: CaptureSession?
    @State private var showSplash = true

    var body: some View {
        ZStack {
            if showSplash {
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
            } else if sessionManager.uiState == .reviewing, let note = sessionManager.note {
                // Physician chose to review now.
                NoteReviewView(
                    sessionId: sessionManager.session?.id ?? "",
                    initialNote: note,
                    onDismiss: {
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
        VStack(spacing: 24) {
            Spacer()

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
                .font(.subheadline)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)

            // Recorded audio stays in memory while the prompt is
            // visible, so the clinician can re-fire without losing
            // the encounter.
            if let prompt = sessionManager.stage1Status.retryPrompt {
                Stage1RetryPrompt(
                    title: prompt.title,
                    detail: prompt.detail,
                    onRetry: { Task { await sessionManager.retryStage1() } }
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
    let onRetry: () -> Void

    var body: some View {
        VStack(spacing: 12) {
            Text(title)
                .font(.subheadline.weight(.semibold))
                .foregroundColor(.primary)
            Text(detail)
                .font(.footnote)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
            Button(L("common.retry"), action: onRetry)
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
                .font(.subheadline)
                .foregroundColor(.primary)
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
                .font(.subheadline)
                .foregroundColor(.secondary)
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
    @FocusState private var focusedField: Field?

    enum Field { case email, password }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

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
                        Toggle(isOn: $rememberMe) {
                            Text(L("login.rememberMeWith", BiometricAuth.typeLabel))
                                .aurionFont(13, relativeTo: .footnote)
                                .foregroundColor(.white.opacity(0.85))
                        }
                        .tint(.aurionGold)
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
                    }
                    .disabled(isSigningIn || signInSucceeded)
                    .frame(maxWidth: .infinity, alignment: .leading)

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

                Text(L("login.footer"))
                    .aurionFont(12, relativeTo: .caption)
                    .tracking(0.4)
                    .foregroundColor(Color.aurionOnNavyFootnote)
                    .padding(.bottom, 40)
                    .opacity(loginAppeared ? 1 : 0)
                    .animation(.easeOut(duration: 0.5).delay(0.4), value: loginAppeared)
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

            Button(L("login.forgetSaved")) { forgetSavedLogin() }
                .aurionFont(12, relativeTo: .caption)
                .foregroundColor(Color.aurionOnNavyFootnote)
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
