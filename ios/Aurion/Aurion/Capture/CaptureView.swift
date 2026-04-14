import SwiftUI

/// Main capture interface -- shown during active recording.
/// Full-screen minimal on both iPhone and iPad.
struct CaptureView: View {
    @ObservedObject var session: CaptureSession
    @EnvironmentObject var sessionManager: SessionManager
    @State private var elapsedTime: TimeInterval = 0
    @State private var timer: Timer?
    @State private var isPulsing = false
    @State private var recBadgePulsing = false

    var body: some View {
        ZStack {
            AurionGradients.navyBackground.ignoresSafeArea()

            VStack(spacing: 0) {
                // Top bar: specialty pill (left) + REC badge (center) + status bar (right area)
                ZStack {
                    // Specialty badge -- frosted glass pill at top-left
                    HStack {
                        specialtyBadge
                        Spacer()
                    }

                    // REC badge -- top center, only when recording
                    if session.state == .recording {
                        recBadge
                            .transition(AurionTransition.scaleIn)
                    }
                }
                .padding(.horizontal, AurionSpacing.lg)
                .padding(.top, AurionSpacing.sm)

                // Frosted glass status bar
                statusBar
                    .padding(.horizontal, AurionSpacing.lg)
                    .padding(.top, AurionSpacing.sm)

                Spacer()

                // Large centered timer
                Text(formatTime(elapsedTime))
                    .font(.system(size: 44, weight: .light, design: .rounded))
                    .monospacedDigit()
                    .foregroundColor(.white)
                    .shadow(color: .black.opacity(0.3), radius: 4, y: 2)

                Spacer()

                if !session.isConsentConfirmed {
                    consentOverlay
                        .transition(AurionTransition.scaleIn)
                } else {
                    controlBar
                }
            }
            .animation(AurionAnimation.smooth, value: session.isConsentConfirmed)
            .animation(AurionAnimation.smooth, value: session.state)
        }
        .onChange(of: session.state) { _, newState in
            switch newState {
            case .recording:
                startTimer()
                AurionHaptics.impact(.heavy)
                withAnimation(AurionAnimation.pulse) {
                    isPulsing = true
                    recBadgePulsing = true
                }
            case .paused:
                stopTimer()
                isPulsing = false
                recBadgePulsing = false
            case .processingStage1:
                stopTimer()
                isPulsing = false
                recBadgePulsing = false
                AurionHaptics.notification(.success)
            default:
                break
            }
        }
        .onAppear {
            if !session.isConsentConfirmed {
                AurionHaptics.notification(.warning)
            }
        }
    }

    // MARK: - Specialty Badge

    private var specialtyBadge: some View {
        let displayName = session.specialty
            .replacingOccurrences(of: "_", with: " ")
            .capitalized

        return HStack(spacing: AurionSpacing.xs) {
            Image(systemName: specialtyIcon)
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(.aurionGold)
            Text(displayName)
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(.white)
        }
        .padding(.horizontal, AurionSpacing.sm)
        .padding(.vertical, AurionSpacing.xs)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
    }

    private var specialtyIcon: String {
        switch session.specialty {
        case "orthopedic_surgery": return "figure.walk"
        case "plastic_surgery": return "scissors"
        case "musculoskeletal": return "figure.flexibility"
        case "emergency_medicine": return "cross.case.fill"
        default: return "stethoscope"
        }
    }

    // MARK: - REC Badge

    private var recBadge: some View {
        HStack(spacing: AurionSpacing.xs) {
            Circle()
                .fill(Color.white)
                .frame(width: 6, height: 6)
            Text("REC")
                .font(.system(size: 13, weight: .heavy, design: .rounded))
                .foregroundColor(.white)
        }
        .padding(.horizontal, AurionSpacing.sm)
        .padding(.vertical, AurionSpacing.xs)
        .background(Color.red)
        .clipShape(Capsule())
        .opacity(recBadgePulsing ? 0.5 : 1.0)
        .animation(AurionAnimation.pulse, value: recBadgePulsing)
    }

    // MARK: - Status Bar

    private var statusBar: some View {
        HStack(spacing: AurionSpacing.sm) {
            Image(systemName: "eyeglasses")
                .foregroundColor(Color.aurionGold)
                .font(.system(size: 14, weight: .semibold))

            Text(stateLabel)
                .font(.system(size: 13, weight: .medium))
                .foregroundColor(.white.opacity(0.9))

            Spacer()

            // Stream indicators
            HStack(spacing: AurionSpacing.xs) {
                streamDot(color: .green, label: "A")
                streamDot(color: .blue, label: "V")
                streamDot(color: .purple, label: "S")
            }
        }
        .padding(.horizontal, AurionSpacing.lg)
        .padding(.vertical, AurionSpacing.sm)
        .background(.ultraThinMaterial)
        .cornerRadius(AurionSpacing.sm)
    }

    private var stateLabel: String {
        switch session.state {
        case .recording: return "Recording"
        case .paused: return "Paused"
        case .consentPending: return "Consent Required"
        case .processingStage1: return "Processing..."
        default: return session.state.rawValue
        }
    }

    private func streamDot(color: Color, label: String) -> some View {
        HStack(spacing: 2) {
            Circle()
                .fill(session.state == .recording ? color : color.opacity(0.3))
                .frame(width: 5, height: 5)
            Text(label)
                .font(.system(size: 9, weight: .bold, design: .monospaced))
                .foregroundColor(.white.opacity(session.state == .recording ? 0.8 : 0.3))
        }
    }

    // MARK: - Consent Overlay

    private var consentOverlay: some View {
        VStack(spacing: AurionSpacing.xl) {
            // Lock icon with badge
            ZStack(alignment: .topTrailing) {
                Image(systemName: "lock.shield.fill")
                    .font(.system(size: 52))
                    .foregroundColor(Color.aurionGold)

                Image(systemName: "exclamationmark.circle.fill")
                    .font(.system(size: 18))
                    .foregroundColor(.white)
                    .background(Circle().fill(Color.aurionAmber).frame(width: 20, height: 20))
                    .offset(x: 4, y: -4)
            }

            Text("Confirm Patient Consent")
                .aurionTitle()
                .foregroundColor(.white)

            Text("Recording cannot begin until patient consent is confirmed. This is a regulatory requirement.")
                .font(.system(size: 15, weight: .regular))
                .foregroundColor(.white.opacity(0.8))
                .multilineTextAlignment(.center)
                .padding(.horizontal, AurionSpacing.xxl)

            Button("Confirm Consent") {
                Task { await sessionManager.confirmConsent() }
            }
            .buttonStyle(AurionPrimaryButtonStyle())
        }
        .padding(AurionSpacing.xxl)
        .background(.ultraThinMaterial)
        .cornerRadius(AurionSpacing.xxl)
        .padding(AurionSpacing.xxl)
    }

    // MARK: - Control Bar

    private var controlBar: some View {
        HStack(spacing: AurionSpacing.huge) {
            switch session.state {
            case .recording:
                Button(action: { session.pause() }) {
                    VStack(spacing: AurionSpacing.xs) {
                        Image(systemName: "pause.circle.fill")
                            .font(.system(size: 44))
                            .foregroundColor(.white)
                        Text("Pause")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.white.opacity(0.7))
                    }
                }
            case .paused:
                Button(action: { session.resume() }) {
                    VStack(spacing: AurionSpacing.xs) {
                        Image(systemName: "play.circle.fill")
                            .font(.system(size: 44))
                            .foregroundColor(Color.aurionGold)
                        Text("Resume")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundColor(.aurionGold.opacity(0.7))
                    }
                }
            default:
                EmptyView()
            }

            Button(action: {
                Task {
                    if session.state == .consentPending && session.isConsentConfirmed {
                        await sessionManager.startRecording()
                    } else if session.state == .recording || session.state == .paused {
                        await sessionManager.stopRecording()
                    }
                }
            }) {
                ZStack {
                    if isPulsing {
                        Circle()
                            .stroke(Color.red.opacity(0.6), lineWidth: 3)
                            .frame(width: 78, height: 78)
                            .scaleEffect(isPulsing ? 1.3 : 1.0)
                            .opacity(isPulsing ? 0 : 0.6)
                            .animation(AurionAnimation.pulse, value: isPulsing)
                    }

                    Circle()
                        .stroke(Color.white, lineWidth: 4)
                        .frame(width: 78, height: 78)

                    if session.state == .recording || session.state == .paused {
                        RoundedRectangle(cornerRadius: 6)
                            .fill(Color.red)
                            .frame(width: 30, height: 30)
                    } else {
                        Circle()
                            .fill(Color.red)
                            .frame(width: 62, height: 62)
                    }
                }
            }
            .disabled(!session.recordButtonEnabled && session.state != .recording && session.state != .paused)

            // Spacer to balance layout when pause/resume button is shown
            Color.clear.frame(width: 44, height: 44)
        }
        .padding(.bottom, AurionSpacing.huge)
    }

    // MARK: - Timer

    private func startTimer() {
        timer = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { _ in
            elapsedTime += 1
        }
    }

    private func stopTimer() {
        timer?.invalidate()
        timer = nil
    }

    private func formatTime(_ seconds: TimeInterval) -> String {
        let mins = Int(seconds) / 60
        let secs = Int(seconds) % 60
        return String(format: "%02d:%02d", mins, secs)
    }
}
