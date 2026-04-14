import SwiftUI

/// Root content view — routes between onboarding, dashboard, capture, review.
/// Uses SessionManager to bridge iOS ↔ backend for the full Journey 1 flow.
struct ContentView: View {
    @EnvironmentObject var appState: AppState
    @StateObject private var sessionManager = SessionManager()
    @State private var showRecoveryAlert = false
    @State private var recoveredSession: CaptureSession?

    var body: some View {
        ZStack {
            if !appState.isAuthenticated {
                LoginView()
                    .transition(.opacity)
            } else if !appState.isOnboardingComplete {
                OnboardingFlowView()
                    .transition(AurionTransition.fadeSlide)
            } else if let note = sessionManager.note {
                // Note received — show review
                NoteReviewView(sessionId: sessionManager.session?.id ?? "", initialNote: note)
                    .transition(AurionTransition.fadeSlide)
                    .overlay(alignment: .topTrailing) {
                        Button("Done") {
                            sessionManager.endSession()
                            appState.currentSession = nil
                        }
                        .font(.subheadline.bold())
                        .foregroundColor(.aurionGold)
                        .padding()
                    }
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
                DashboardView()
                    .transition(AurionTransition.fadeSlide)
                    .environmentObject(sessionManager)
            }
        }
        .animation(AurionAnimation.smooth, value: appState.isAuthenticated)
        .animation(AurionAnimation.smooth, value: appState.isOnboardingComplete)
        .animation(AurionAnimation.smooth, value: sessionManager.session?.id)
        .animation(AurionAnimation.smooth, value: sessionManager.note?.sessionId)
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

// MARK: - Premium Login

struct LoginView: View {
    @EnvironmentObject var appState: AppState
    @State private var email = ""
    @State private var password = ""
    @State private var isSigningIn = false
    @FocusState private var focusedField: LoginField?

    enum LoginField { case email, password }

    var body: some View {
        ZStack {
            AurionGradients.navyBackground.ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer()

                VStack(spacing: 24) {
                    Image(systemName: "waveform.circle.fill")
                        .font(.system(size: 56))
                        .foregroundStyle(AurionGradients.goldShimmer)

                    VStack(spacing: 4) {
                        Text("Aurion")
                            .font(.system(size: 28, weight: .bold))
                            .foregroundColor(.aurionTextPrimary)
                        Text("CLINICAL AI")
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .tracking(3)
                    }

                    Divider().padding(.horizontal, 32)

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Email").font(.caption).foregroundColor(.secondary)
                        TextField("physician@hospital.org", text: $email)
                            .textFieldStyle(.plain)
                            .textContentType(.emailAddress)
                            .autocapitalization(.none)
                            .padding(12)
                            .background(Color.aurionFieldBackground)
                            .cornerRadius(10)
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(focusedField == .email ? Color.aurionGold : .clear, lineWidth: 2)
                            )
                            .focused($focusedField, equals: .email)
                    }

                    VStack(alignment: .leading, spacing: 6) {
                        Text("Password").font(.caption).foregroundColor(.secondary)
                        SecureField("", text: $password)
                            .textFieldStyle(.plain)
                            .padding(12)
                            .background(Color.aurionFieldBackground)
                            .cornerRadius(10)
                            .overlay(
                                RoundedRectangle(cornerRadius: 10)
                                    .stroke(focusedField == .password ? Color.aurionGold : .clear, lineWidth: 2)
                            )
                            .focused($focusedField, equals: .password)
                    }

                    Button {
                        AurionHaptics.impact(.medium)
                        isSigningIn = true
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) {
                            appState.isAuthenticated = true
                        }
                    } label: {
                        HStack(spacing: 8) {
                            if isSigningIn {
                                ProgressView().tint(.white)
                            }
                            Text("Sign In")
                        }
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                    .disabled(isSigningIn)
                }
                .padding(32)
                .background(Color.aurionCardBackground)
                .cornerRadius(24)
                .shadow(color: .black.opacity(0.2), radius: 30, y: 10)
                .padding(.horizontal, 32)

                Spacer()

                Text("HIPAA Compliant · On-Device Privacy")
                    .font(.caption2)
                    .foregroundColor(.white.opacity(0.4))
                    .padding(.bottom, 24)
            }
        }
    }
}
