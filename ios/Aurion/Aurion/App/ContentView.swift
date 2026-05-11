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
            } else if sessionManager.note != nil && !sessionManager.showingReview {
                // Note ready — ask physician to review now or save for later
                NoteReadyView()
                    .transition(AurionTransition.fadeSlide)
                    .environmentObject(sessionManager)
            } else if let note = sessionManager.note, sessionManager.showingReview {
                // Physician chose to review now
                NoteReviewView(
                    sessionId: sessionManager.session?.id ?? "",
                    initialNote: note,
                    onDismiss: {
                        sessionManager.endSession()
                        appState.currentSession = nil
                    }
                )
                .transition(AurionTransition.fadeSlide)
            } else if sessionManager.showingPostEncounter, let session = sessionManager.session {
                // Post-encounter — confirm template before pipeline
                PostEncounterView(currentSpecialty: session.specialty, profileLanguage: appState.physicianProfile?.outputLanguage ?? "en")
                    .transition(AurionTransition.fadeSlide)
                    .environmentObject(sessionManager)
            } else if sessionManager.isProcessing {
                // Processing state — after stop, before note arrives
                ProcessingView(status: sessionManager.processingStatus)
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
        .animation(AurionAnimation.smooth, value: sessionManager.showingReview)
        .animation(AurionAnimation.smooth, value: sessionManager.showingPostEncounter)
        .animation(AurionAnimation.smooth, value: sessionManager.isProcessing)
        .onAppear {
            appState.checkVoiceEnrollment()
            checkForCrashRecovery()
        }
        .alert("Incomplete Session Detected", isPresented: $showRecoveryAlert) {
            Button("Recover") {
                if let session = recoveredSession {
                    appState.currentSession = session
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

                Spacer()
            }
        }
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
    @FocusState private var focusedField: LoginField?
    /// Drives the entrance staircase — logo first, then the form card,
    /// then the footer. Flipped on first appear; the resulting feel is a
    /// deliberate composition rather than a slam-on render.
    @State private var loginAppeared = false
    /// True for ~700 ms after a successful sign-in. The sign-in button
    /// morphs into a green checkmark before ContentView swaps in the
    /// dashboard — confirms "you're in" with a beat of visual feedback.
    @State private var signInSucceeded = false

    enum LoginField { case email, password }

    var body: some View {
        ZStack {
            // Navy gradient background (design: #1A2E5C → #0D1B3E)
            // Reversed direction so the upper portion (where the logo
            // lockup lands) is exactly `aurionNavy` (= Logo.png bg color).
            // Bottom fades into a slightly darker navy for depth without
            // letting the logo look like it's pasted on a separate panel.
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 0) {
                // Logo lockup — matches design/assets/logo-lockup-dark.svg
                AurionLogoLockup(size: 1.2, dark: true)
                    .padding(.top, 80)
                    // Spring entrance — slides + scales in for a deliberate
                    // brand reveal instead of a hard cut.
                    .opacity(loginAppeared ? 1 : 0)
                    .scaleEffect(loginAppeared ? 1 : 0.92)
                    .offset(y: loginAppeared ? 0 : -20)
                    .animation(
                        .interpolatingSpring(stiffness: 180, damping: 22),
                        value: loginAppeared
                    )

                Spacer()

                // Form card — frosted glass per design
                VStack(spacing: 14) {
                    VStack(alignment: .leading, spacing: 6) {
                        Text(L("login.email").uppercased())
                            .font(.system(size: 12, weight: .semibold))
                            .tracking(0.8)
                            .foregroundColor(Color(red: 183/255, green: 192/255, blue: 214/255))
                        TextField("dr.chen@aurion.health", text: $email)
                            .textFieldStyle(.plain)
                            .textContentType(.emailAddress)
                            .autocapitalization(.none)
                            .foregroundColor(.white)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 12)
                            .background(Color.white.opacity(0.08))
                            .cornerRadius(10)
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(focusedField == .email ? Color.aurionGold : Color.white.opacity(0.16), lineWidth: 1)
                            )
                            .focused($focusedField, equals: .email)
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text(L("login.password").uppercased())
                            .font(.system(size: 12, weight: .semibold))
                            .tracking(0.8)
                            .foregroundColor(Color(red: 183/255, green: 192/255, blue: 214/255))
                        SecureField("", text: $password)
                            .textFieldStyle(.plain)
                            .foregroundColor(.white)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 12)
                            .background(Color.white.opacity(0.08))
                            .cornerRadius(10)
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(focusedField == .password ? Color.aurionGold : Color.white.opacity(0.16), lineWidth: 1)
                            )
                            .focused($focusedField, equals: .password)
                    }

                    Button {
                        AurionHaptics.impact(.medium)
                        Task { await signIn() }
                    } label: {
                        HStack(spacing: 8) {
                            if signInSucceeded {
                                Image(systemName: "checkmark.circle.fill")
                                    .font(.system(size: 16, weight: .bold))
                                    .foregroundColor(.aurionNavy)
                                    .transition(.scale.combined(with: .opacity))
                                Text("Signed in")
                                    .transition(.opacity)
                            } else if isSigningIn {
                                ProgressView()
                                    .tint(.aurionNavy)
                                    .transition(.opacity)
                                Text("Signing in…")
                                    .transition(.opacity)
                            } else {
                                Text(L("login.signIn"))
                                    .transition(.opacity)
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
                            .foregroundColor(Color(red: 255/255, green: 180/255, blue: 180/255))
                            .multilineTextAlignment(.center)
                    }

                    HStack {
                        Text("Forgot password?")
                            .font(.system(size: 13))
                            .foregroundColor(Color(red: 183/255, green: 192/255, blue: 214/255))
                        Spacer()
                        Button("Create account", action: onSwitchToRegister)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(.aurionGold)
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
                // Form card slides up after the logo lands — 180ms delay
                // gives the logo room to finish its spring.
                .opacity(loginAppeared ? 1 : 0)
                .offset(y: loginAppeared ? 0 : 24)
                .animation(
                    .interpolatingSpring(stiffness: 200, damping: 24)
                        .delay(0.18),
                    value: loginAppeared
                )

                Spacer()

                // Footer
                Text(L("login.footer"))
                    .font(.system(size: 12))
                    .tracking(0.4)
                    .foregroundColor(Color(red: 133/255, green: 144/255, blue: 174/255))
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
            let resp = try await APIClient.shared.login(email: email, password: password)
            KeychainHelper.shared.saveAuthToken(
                resp.accessToken,
                userId: resp.userId,
                role: resp.role,
                name: resp.fullName
            )
            AurionHaptics.notification(.success)
            // Brief "signed in" beat before ContentView swaps in the
            // dashboard — gives the user a single frame of confirmation
            // that the credentials worked, not just a jarring scene cut.
            isSigningIn = false
            signInSucceeded = true
            try? await Task.sleep(nanoseconds: 600_000_000)
            let role = UserRole(rawValue: resp.role) ?? .clinician
            appState.applyAuth(userId: resp.userId, role: role)
        } catch APIError.unauthorized {
            isSigningIn = false
            loginError = "Invalid email or password."
            AurionHaptics.notification(.error)
        } catch {
            isSigningIn = false
            loginError = "Sign-in failed: \(error.localizedDescription)"
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
                                .foregroundColor(Color(red: 255/255, green: 180/255, blue: 180/255))
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
                                .foregroundColor(Color(red: 255/255, green: 180/255, blue: 180/255))
                                .multilineTextAlignment(.center)
                        }

                        HStack(spacing: 6) {
                            Text("Already have an account?")
                                .font(.system(size: 13))
                                .foregroundColor(Color(red: 183/255, green: 192/255, blue: 214/255))
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
                        .foregroundColor(Color(red: 133/255, green: 144/255, blue: 174/255))
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
                .foregroundColor(Color(red: 183/255, green: 192/255, blue: 214/255))
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
