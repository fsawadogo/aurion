import SwiftUI

/// Root content view — routes between onboarding, dashboard, capture, review.
/// Uses SessionManager to bridge iOS ↔ backend for the full Journey 1 flow.
struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var sessionManager = SessionManager()
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
        .onAppear {
            appState.checkVoiceEnrollment()
            checkForCrashRecovery()
        }
        .alert("Incomplete Session Detected", isPresented: $showRecoveryAlert) {
            Button("Recover") {
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
            Button("Discard", role: .destructive) {
                SessionPersistence.clear()
                recoveredSession = nil
            }
        } message: {
            if let session = recoveredSession {
                Text("A \(session.specialty.replacingOccurrences(of: "_", with: " ")) session was interrupted. Would you like to recover it?")
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

    var body: some View {
        ZStack {
            Color.aurionBackground.ignoresSafeArea()

            VStack(spacing: 24) {
                Spacer()

                CircularProgressRing(progress: 0.7, color: .aurionGold, lineWidth: 6, size: 80)

                Text("Processing Session")
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
            Button("Retry", action: onRetry)
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
            Text("\(failedCount) frame\(failedCount == 1 ? "" : "s") could not be masked on-device and were not uploaded.")
                .font(.subheadline)
                .foregroundColor(.primary)
                .multilineTextAlignment(.center)

            HStack(spacing: 12) {
                Button("Retry", action: onRetry)
                    .buttonStyle(.borderedProminent)
                Button("Skip", role: .destructive, action: onSkip)
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
    @State private var isSigningIn = false
    @State private var loginError: String?
    /// Drives the entrance staircase — logo first, then the form card,
    /// then the footer. Flipped on first appear; the resulting feel is a
    /// deliberate composition rather than a slam-on render.
    @State private var loginAppeared = false
    /// True for ~700 ms after a successful sign-in. The sign-in button
    /// morphs into a green checkmark before ContentView swaps in the
    /// dashboard — confirms "you're in" with a beat of visual feedback.
    @State private var signInSucceeded = false

    var body: some View {
        ZStack {
            // Navy gradient background. Brand-fixed surface — same in
            // both color schemes (login is identity, not theme).
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

                // Sign-in card. The email + password form is gone —
                // authentication happens in the Cognito hosted UI
                // (opened in ASWebAuthenticationSession) so the iOS app
                // never touches credentials, and MFA enrollment +
                // challenge flows live entirely on Cognito's surface.
                VStack(spacing: 18) {
                    VStack(spacing: 6) {
                        Text("Sign in to continue")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundColor(.white)
                        Text("Aurion uses a secure sign-in window from AWS Cognito. Multi-factor authentication is required.")
                            .font(.system(size: 13))
                            .foregroundColor(Color.aurionOnNavySecondary)
                            .multilineTextAlignment(.center)
                            .lineSpacing(3)
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
                                Text("Signed in")
                            } else if isSigningIn {
                                ProgressView().tint(.aurionNavy)
                                Text("Opening secure sign-in…")
                            } else {
                                Image(systemName: "lock.shield.fill")
                                    .font(.system(size: 16, weight: .semibold))
                                Text("Sign in")
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .animation(AurionAnimation.smooth, value: isSigningIn)
                        .animation(AurionAnimation.smooth, value: signInSucceeded)
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                    .disabled(isSigningIn || signInSucceeded)

                    if let loginError {
                        Text(loginError)
                            .font(.system(size: 12))
                            .foregroundColor(Color.aurionOnNavyError)
                            .multilineTextAlignment(.center)
                    }

                    Text("First-time access? Your administrator will provide a temporary password and walk you through enrolling your authenticator app.")
                        .font(.system(size: 11))
                        .foregroundColor(Color.aurionOnNavyFootnote)
                        .multilineTextAlignment(.center)
                        .lineSpacing(3)
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
    }

    @MainActor
    private func signIn() async {
        isSigningIn = true
        loginError = nil
        do {
            // Hosted UI handles password + TOTP MFA on Cognito's surface,
            // we get back a token bundle on the redirect.
            _ = try await CognitoAuth.shared.signIn()

            // Backend round trip: validates the JWT via JWKS, looks up
            // (or auto-provisions on first sign-in) the UserModel row,
            // returns the canonical user identity for the SwiftUI app.
            let me = try await APIClient.shared.fetchCurrentUser()
            AurionHaptics.notification(.success)
            isSigningIn = false
            signInSucceeded = true
            try? await Task.sleep(nanoseconds: 600_000_000)
            appState.applyAuth(userId: me.userId, role: me.role)
        } catch AuthError.userCancelled {
            isSigningIn = false
            // Soft state — no error banner, user knows they cancelled.
        } catch {
            isSigningIn = false
            loginError = error.localizedDescription
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
                        Text("Create your account")
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundColor(.white)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(.bottom, 4)

                        labelledField(
                            label: "FULL NAME",
                            placeholder: "Dr. Jane Doe",
                            text: $fullName,
                            secure: false,
                            field: .name,
                            contentType: .name,
                            autocapitalize: true
                        )

                        labelledField(
                            label: "EMAIL",
                            placeholder: "you@aurion.health",
                            text: $email,
                            secure: false,
                            field: .email,
                            contentType: .emailAddress,
                            autocapitalize: false
                        )

                        labelledField(
                            label: "PASSWORD",
                            placeholder: "At least 8 characters",
                            text: $password,
                            secure: true,
                            field: .password,
                            contentType: .newPassword,
                            autocapitalize: false
                        )

                        labelledField(
                            label: "CONFIRM PASSWORD",
                            placeholder: "Re-enter password",
                            text: $confirmPassword,
                            secure: true,
                            field: .confirm,
                            contentType: .newPassword,
                            autocapitalize: false
                        )

                        if !confirmPassword.isEmpty && password != confirmPassword {
                            Text("Passwords don't match.")
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
                                Text("Create Account")
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
                            Text("Already have an account?")
                                .font(.system(size: 13))
                                .foregroundColor(Color.aurionOnNavySecondary)
                            Button("Sign in", action: onSwitchToLogin)
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

                    Text("By creating an account you agree to handle PHI in accordance with your facility's policies.")
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
            registerError = parseDetail(body) ?? "An account with that email already exists."
            AurionHaptics.notification(.error)
        } catch {
            registerError = "Sign-up failed: \(error.localizedDescription)"
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
