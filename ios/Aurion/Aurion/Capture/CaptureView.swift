import SwiftUI

/// Main capture interface — shown during active recording.
/// Full-screen minimal on both iPhone and iPad.
struct CaptureView: View {
    @ObservedObject var session: CaptureSession
    @EnvironmentObject var sessionManager: SessionManager
    @State private var elapsedTime: TimeInterval = 0
    @State private var timer: Timer?
    @State private var isPulsing = false

    var body: some View {
        ZStack {
            AurionGradients.navyBackground.ignoresSafeArea()

            VStack {
                HStack {
                    Image(systemName: "eyeglasses")
                        .foregroundColor(Color.aurionGold)
                    Text(session.state == .recording ? "Recording" : session.state.rawValue)
                        .font(.caption)
                        .foregroundColor(.white)

                    Spacer()

                    Text(formatTime(elapsedTime))
                        .font(.title3)
                        .monospacedDigit()
                        .foregroundColor(.white)

                    Spacer()

                    Text(session.specialty)
                        .font(.caption2)
                        .foregroundColor(.white.opacity(0.7))
                }
                .padding()
                .background(.ultraThinMaterial)
                .cornerRadius(16)
                .padding(.horizontal, 16)
                .padding(.top, 8)

                Spacer()

                if !session.isConsentConfirmed {
                    consentOverlay
                        .transition(AurionTransition.scaleIn)
                } else {
                    controlBar
                }
            }
            .animation(AurionAnimation.smooth, value: session.isConsentConfirmed)
        }
        .onChange(of: session.state) { _, newState in
            switch newState {
            case .recording:
                startTimer()
                AurionHaptics.impact(.heavy)
                withAnimation(AurionAnimation.pulse) {
                    isPulsing = true
                }
            case .paused:
                stopTimer()
                isPulsing = false
            case .processingStage1:
                stopTimer()
                isPulsing = false
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

    // MARK: - Consent Overlay

    private var consentOverlay: some View {
        VStack(spacing: 24) {
            Image(systemName: "lock.shield")
                .font(.system(size: 48))
                .foregroundColor(Color.aurionGold)

            Text("Confirm Patient Consent")
                .font(.title2)
                .fontWeight(.bold)
                .foregroundColor(.white)

            Text("Recording cannot begin until patient consent is confirmed.")
                .font(.body)
                .foregroundColor(.white.opacity(0.8))
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)

            Button("Confirm Consent") {
                Task { await sessionManager.confirmConsent() }
            }
            .buttonStyle(AurionPrimaryButtonStyle())
        }
        .padding(24)
        .background(.ultraThinMaterial)
        .cornerRadius(24)
        .padding(24)
    }

    // MARK: - Control Bar

    private var controlBar: some View {
        HStack(spacing: 40) {
            switch session.state {
            case .recording:
                Button(action: { session.pause() }) {
                    Image(systemName: "pause.circle.fill")
                        .font(.system(size: 44))
                        .foregroundColor(.white)
                }
            case .paused:
                Button(action: { session.resume() }) {
                    Image(systemName: "play.circle.fill")
                        .font(.system(size: 44))
                        .foregroundColor(Color.aurionGold)
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
                            .frame(width: 72, height: 72)
                            .scaleEffect(isPulsing ? 1.3 : 1.0)
                            .opacity(isPulsing ? 0 : 0.6)
                            .animation(AurionAnimation.pulse, value: isPulsing)
                    }

                    Circle()
                        .stroke(Color.white, lineWidth: 4)
                        .frame(width: 72, height: 72)

                    if session.state == .recording || session.state == .paused {
                        RoundedRectangle(cornerRadius: 4)
                            .fill(Color.red)
                            .frame(width: 28, height: 28)
                    } else {
                        Circle()
                            .fill(Color.red)
                            .frame(width: 56, height: 56)
                    }
                }
            }
            .disabled(!session.recordButtonEnabled && session.state != .recording && session.state != .paused)

            Spacer().frame(width: 44)
        }
        .padding(.bottom, 40)
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
