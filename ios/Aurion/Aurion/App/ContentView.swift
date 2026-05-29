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

            CircularProgressRing(progress: 0.7, color: .aurionGold, lineWidth: 6, size: 80)

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

/// Holds the login/register toggle. Each child view gets a closure that
/// flips the mode without leaking the mode enum into either subview.
struct AuthView: View {
    @State private var mode: AuthMode = .login

    private enum AuthMode { case login, register }

    var body: some View {
        ZStack {
            switch mode {
            case .login:
                LoginView(onSwitchToRegister: { mode = .register })
                    .transition(.opacity)
            case .register:
                RegisterView(onSwitchToLogin: { mode = .login })
                    .transition(.opacity)
            }
        }
        .animation(AurionAnimation.smooth, value: mode)
    }
}

// MARK: - Premium Login

struct LoginView: View {
    let onSwitchToRegister: () -> Void

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
    /// Set when Cognito asks the user to replace their temp password
    /// (first sign-in for every admin-provisioned account). Drives a
    /// full-screen cover sheet rather than swapping the form so the
    /// transition reads as "you got past the first gate, now do this."
    @State private var newPasswordChallenge: (session: String, username: String)?
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
                                .font(.system(size: 13))
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
                            .font(.system(size: 12))
                            .foregroundColor(Color.aurionOnNavyError)
                            .multilineTextAlignment(.center)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    if hasSavedLogin {
                        biometricSignInSection
                    }

                    Text(L("login.firstTimeHint"))
                        .font(.system(size: 11))
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
                    .font(.system(size: 12))
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
        .fullScreenCover(item: Binding(
            get: { newPasswordChallenge.map { NewPasswordChallenge(session: $0.session, username: $0.username) } },
            set: { _ in newPasswordChallenge = nil }
        )) { challenge in
            NewPasswordView(challenge: challenge) { outcome in
                handleOutcome(outcome)
            } onCancel: {
                newPasswordChallenge = nil
            }
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
                .font(.system(size: 11, weight: .semibold))
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
                    .font(.system(size: 11))
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
                .font(.system(size: 12))
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
            let outcome = try await CognitoNativeAuth.shared.refreshSession(
                refreshToken: refreshToken
            )
            handleOutcome(outcome)
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
            let outcome = try await CognitoNativeAuth.shared.signIn(
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
    private func handleOutcome(_ outcome: CognitoNativeAuth.SignInOutcome) {
        switch outcome {
        case .authenticated:
            // Persist the biometric "remember me" credential when opted in.
            // Skipped on the biometric sign-in path itself (the email field
            // is empty there) — the credential already exists.
            if rememberMe, !email.isEmpty,
               let rt = KeychainHelper.shared.getRefreshToken(), !rt.isEmpty {
                KeychainHelper.shared.saveBiometricCredential(
                    refreshToken: rt,
                    email: email.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
                )
            }
            // Backend round trip — same shape as the hosted-UI path used
            // to do, so AppState wiring downstream is unchanged.
            Task {
                do {
                    let me = try await APIClient.shared.fetchCurrentUser()
                    AurionHaptics.notification(.success)
                    isSigningIn = false
                    signInSucceeded = true
                    newPasswordChallenge = nil
                    try? await Task.sleep(nanoseconds: 600_000_000)
                    appState.applyAuth(userId: me.userId, role: me.role)
                } catch {
                    isSigningIn = false
                    loginError = L("login.backendLookupFailed", error.localizedDescription)
                    AurionHaptics.notification(.error)
                }
            }
        case .newPasswordRequired(let session, let username):
            isSigningIn = false
            newPasswordChallenge = (session: session, username: username)
        case .mfaRequired:
            isSigningIn = false
            loginError = L("login.mfaUnsupported")
            AurionHaptics.notification(.error)
        }
    }
}

// MARK: - New password challenge (first sign-in)

/// Identifiable wrapper so the new-password screen can be presented via
/// `.fullScreenCover(item:)` without ambiguity over the tuple.
private struct NewPasswordChallenge: Identifiable {
    let id = UUID()
    let session: String
    let username: String
}

private struct NewPasswordView: View {
    let challenge: NewPasswordChallenge
    let onSuccess: (CognitoNativeAuth.SignInOutcome) -> Void
    let onCancel: () -> Void

    @State private var newPassword = ""
    @State private var confirm = ""
    @State private var isSubmitting = false
    @State private var error: String?
    @FocusState private var focused: Field?

    enum Field { case newPassword, confirm }

    /// Cognito user pool policy mirrored from `infrastructure/cognito.tf`.
    /// We surface the rules inline so the user sees what they're shooting
    /// for before they hit submit, not after the failure roundtrip.
    private var meetsPolicy: Bool {
        newPassword.count >= 12 &&
            newPassword.range(of: #"[a-z]"#, options: .regularExpression) != nil &&
            newPassword.range(of: #"[A-Z]"#, options: .regularExpression) != nil &&
            newPassword.range(of: #"\d"#, options: .regularExpression) != nil &&
            newPassword.range(of: #"[^A-Za-z0-9]"#, options: .regularExpression) != nil
    }

    private var canSubmit: Bool {
        meetsPolicy && newPassword == confirm && !isSubmitting
    }

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 0) {
                HStack {
                    Button {
                        onCancel()
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "chevron.left")
                            Text(L("common.cancel"))
                        }
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.white.opacity(0.8))
                    }
                    Spacer()
                }
                .padding(.horizontal, 24)
                .padding(.top, 20)

                Spacer()

                VStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(L("newpw.title"))
                            .aurionFont(22, weight: .semibold, relativeTo: .title2)
                            .foregroundColor(.white)
                        Text(L("newpw.forUser", challenge.username))
                            .font(.system(size: 13))
                            .foregroundColor(Color.aurionOnNavySecondary)
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)

                    field(L("newpw.newPassword"), text: $newPassword, field: .newPassword) {
                        focused = .confirm
                    }
                    field(L("newpw.confirmPassword"), text: $confirm, field: .confirm) {
                        if canSubmit { Task { await submit() } }
                    }

                    policyChecklist
                        .padding(.top, 4)

                    Button {
                        AurionHaptics.impact(.medium)
                        Task { await submit() }
                    } label: {
                        HStack(spacing: 10) {
                            if isSubmitting {
                                ProgressView().tint(.aurionNavy)
                                Text(L("newpw.updating"))
                            } else {
                                Image(systemName: "checkmark.circle.fill")
                                    .font(.system(size: 16, weight: .semibold))
                                Text(L("newpw.update"))
                            }
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                    .disabled(!canSubmit)

                    if let error {
                        Text(error)
                            .font(.system(size: 12))
                            .foregroundColor(Color.aurionOnNavyError)
                            .multilineTextAlignment(.leading)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }
                }
                .padding(24)
                .background(Color.white.opacity(0.06))
                .cornerRadius(18)
                .overlay(
                    RoundedRectangle(cornerRadius: 18)
                        .stroke(Color.white.opacity(0.10), lineWidth: 1)
                )
                .padding(.horizontal, 24)

                Spacer()
            }
        }
        .onAppear { focused = .newPassword }
    }

    @ViewBuilder
    private func field(
        _ label: String,
        text: Binding<String>,
        field: Field,
        onSubmit: @escaping () -> Void
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.system(size: 11, weight: .semibold))
                .tracking(0.5)
                .foregroundColor(Color.aurionOnNavyFootnote)
            SecureField("", text: text)
                .focused($focused, equals: field)
                .submitLabel(field == .newPassword ? .next : .done)
                .onSubmit(onSubmit)
                .textInputAutocapitalization(.never)
                .autocorrectionDisabled()
                .textContentType(.newPassword)
                .foregroundColor(.white)
                .tint(.aurionGold)
                .padding(.horizontal, 12)
                .padding(.vertical, 11)
                .background(Color.white.opacity(0.08))
                .cornerRadius(10)
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .stroke(Color.white.opacity(focused == field ? 0.35 : 0.10), lineWidth: 1)
                )
        }
    }

    private var policyChecklist: some View {
        VStack(alignment: .leading, spacing: 4) {
            policyRow(L("newpw.policy.length"), ok: newPassword.count >= 12)
            policyRow(L("newpw.policy.upper"), ok: newPassword.range(of: #"[A-Z]"#, options: .regularExpression) != nil)
            policyRow(L("newpw.policy.lower"), ok: newPassword.range(of: #"[a-z]"#, options: .regularExpression) != nil)
            policyRow(L("newpw.policy.digit"), ok: newPassword.range(of: #"\d"#, options: .regularExpression) != nil)
            policyRow(L("newpw.policy.symbol"), ok: newPassword.range(of: #"[^A-Za-z0-9]"#, options: .regularExpression) != nil)
            policyRow(L("newpw.policy.match"), ok: !confirm.isEmpty && newPassword == confirm)
        }
    }

    private func policyRow(_ text: String, ok: Bool) -> some View {
        HStack(spacing: 6) {
            Image(systemName: ok ? "checkmark.circle.fill" : "circle")
                .font(.system(size: 11))
                .foregroundColor(ok ? Color.aurionGold : Color.aurionOnNavyFootnote)
            Text(text)
                .font(.system(size: 11))
                .foregroundColor(ok ? Color.aurionOnNavySecondary : Color.aurionOnNavyFootnote)
        }
    }

    @MainActor
    private func submit() async {
        isSubmitting = true
        error = nil
        do {
            let outcome = try await CognitoNativeAuth.shared.completeNewPassword(
                username: challenge.username,
                newPassword: newPassword,
                session: challenge.session
            )
            onSuccess(outcome)
        } catch {
            isSubmitting = false
            self.error = error.localizedDescription
            AurionHaptics.notification(.error)
        }
    }
}

// MARK: - Register

struct RegisterView: View {
    let onSwitchToLogin: () -> Void

    @EnvironmentObject var appState: AppState
    @State private var fullName = ""
    @State private var email = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @State private var isSubmitting = false
    @State private var registerError: String?
    @FocusState private var focusedField: Field?

    private enum Field { case name, email, password, confirm }

    /// Min 8 chars, matching the backend's RegisterRequest validation.
    private var canSubmit: Bool {
        !fullName.trimmingCharacters(in: .whitespaces).isEmpty
            && email.contains("@")
            && password.count >= 8
            && password == confirmPassword
            && !isSubmitting
    }

    var body: some View {
        ZStack {
            // Reversed direction so the upper portion (where the logo
            // lockup lands) is exactly `aurionNavy` (= Logo.png bg color).
            // Bottom fades into a slightly darker navy for depth without
            // letting the logo look like it's pasted on a separate panel.
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            ScrollView(showsIndicators: false) {
                VStack(spacing: 0) {
                    AurionLogoLockup(size: 1.0, dark: true)
                        .padding(.top, 56)
                        .padding(.bottom, 32)

                    VStack(spacing: 14) {
                        Text(L("register.title"))
                            .aurionFont(18, weight: .semibold, relativeTo: .title3)
                            .foregroundColor(.white)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.bottom, 4)

                        labelledField(
                            label: L("register.fullName"),
                            placeholder: L("register.fullNamePlaceholder"),
                            text: $fullName,
                            secure: false,
                            field: .name,
                            contentType: .name,
                            autocapitalize: true
                        )

                        labelledField(
                            label: L("register.email"),
                            placeholder: L("register.emailPlaceholder"),
                            text: $email,
                            secure: false,
                            field: .email,
                            contentType: .emailAddress,
                            autocapitalize: false
                        )

                        labelledField(
                            label: L("register.password"),
                            placeholder: L("register.passwordPlaceholder"),
                            text: $password,
                            secure: true,
                            field: .password,
                            contentType: .newPassword,
                            autocapitalize: false
                        )

                        labelledField(
                            label: L("register.confirmPassword"),
                            placeholder: L("register.confirmPlaceholder"),
                            text: $confirmPassword,
                            secure: true,
                            field: .confirm,
                            contentType: .newPassword,
                            autocapitalize: false
                        )

                        if !confirmPassword.isEmpty && password != confirmPassword {
                            Text(L("register.passwordMismatch"))
                                .font(.system(size: 12))
                                .foregroundColor(Color.aurionOnNavyError)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }

                        Button {
                            AurionHaptics.impact(.medium)
                            Task { await submit() }
                        } label: {
                            HStack(spacing: 8) {
                                if isSubmitting {
                                    ProgressView().tint(.aurionNavy)
                                }
                                Text(L("register.createAccount"))
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(AurionPrimaryButtonStyle())
                        .disabled(!canSubmit)
                        .padding(.top, 4)

                        if let registerError {
                            Text(registerError)
                                .font(.system(size: 12))
                                .foregroundColor(Color.aurionOnNavyError)
                                .multilineTextAlignment(.center)
                        }

                        HStack(spacing: 6) {
                            Text(L("register.haveAccount"))
                                .font(.system(size: 13))
                                .foregroundColor(Color.aurionOnNavySecondary)
                            Button(L("login.signIn"), action: onSwitchToLogin)
                                .font(.system(size: 13, weight: .semibold))
                                .foregroundColor(.aurionGold)
                        }
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

                    Text(L("register.phiNotice"))
                        .font(.system(size: 11))
                        .tracking(0.2)
                        .foregroundColor(Color.aurionOnNavyFootnote)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 32)
                        .padding(.top, 24)
                        .padding(.bottom, 32)
                }
            }
        }
    }

    @ViewBuilder
    private func labelledField(
        label: String,
        placeholder: String,
        text: Binding<String>,
        secure: Bool,
        field: Field,
        contentType: UITextContentType,
        autocapitalize: Bool
    ) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label)
                .font(.system(size: 12, weight: .semibold))
                .tracking(0.8)
                .foregroundColor(Color.aurionOnNavySecondary)
            Group {
                if secure {
                    SecureField(placeholder, text: text)
                } else {
                    TextField(placeholder, text: text)
                        .autocapitalization(autocapitalize ? .words : .none)
                }
            }
            .textFieldStyle(.plain)
            .textContentType(contentType)
            .foregroundColor(.white)
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(Color.white.opacity(0.08))
            .cornerRadius(10)
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(focusedField == field ? Color.aurionGold : Color.white.opacity(0.16), lineWidth: 1)
            )
            .focused($focusedField, equals: field)
        }
    }

    @MainActor
    private func submit() async {
        isSubmitting = true
        registerError = nil
        defer { isSubmitting = false }
        do {
            let resp = try await APIClient.shared.register(
                email: email.trimmingCharacters(in: .whitespaces),
                password: password,
                fullName: fullName.trimmingCharacters(in: .whitespaces)
            )
            KeychainHelper.shared.saveAuthToken(
                resp.accessToken,
                userId: resp.userId,
                role: resp.role,
                name: resp.fullName
            )
            let role = UserRole(rawValue: resp.role) ?? .clinician
            appState.applyAuth(userId: resp.userId, role: role)
            AurionHaptics.notification(.success)
        } catch APIError.conflict(let body) {
            registerError = parseDetail(body) ?? L("register.errorExists")
            AurionHaptics.notification(.error)
        } catch {
            registerError = L("register.errorGeneric", error.localizedDescription)
            AurionHaptics.notification(.error)
        }
    }

    /// FastAPI errors arrive as `{"detail": "..."}` — pull out the human-readable string.
    private func parseDetail(_ body: String) -> String? {
        guard let data = body.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let detail = json["detail"] as? String else {
            return nil
        }
        return detail
    }
}
