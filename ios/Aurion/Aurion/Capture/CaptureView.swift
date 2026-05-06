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
            AurionGradients.captureBackground.ignoresSafeArea()

            VStack(spacing: 0) {
                // Top bar: specialty pill (left) + REC badge (center) + A/V/S (right)
                HStack {
                    specialtyBadge

                    Spacer()

                    if session.state == .recording {
                        recBadge
                            .transition(AurionTransition.scaleIn)
                    }

                    Spacer()

                    // Stream indicators — top right per design
                    HStack(spacing: 6) {
                        streamCircle("A")
                        streamCircle("V")
                        streamCircle("S")
                    }
                }
                .padding(.horizontal, AurionSpacing.lg)
                .padding(.top, AurionSpacing.sm)

                Spacer()

                // Large centered timer — monospaced 88pt per design
                VStack(spacing: 6) {
                    Text(formatTime(elapsedTime))
                        .font(.system(size: 88, weight: .medium, design: .monospaced))
                        .monospacedDigit()
                        .tracking(-2)
                        .foregroundColor(.white)

                    Text("Recording \u{00B7} Doctor + Patient")
                        .font(.system(size: 13))
                        .tracking(0.4)
                        .foregroundColor(Color(red: 183/255, green: 192/255, blue: 214/255))

                    // Audio waveform bars
                    if session.state == .recording {
                        audioWaveform
                            .padding(.top, 28)
                    }

                    // Live captions — on-device, runs alongside the canonical
                    // Whisper batch transcription. Hidden when the device or
                    // locale lacks an on-device speech model.
                    if let live = sessionManager.liveTranscriber,
                       live.isAvailable,
                       !live.transcript.isEmpty,
                       session.state == .recording || session.state == .paused {
                        liveCaptionStrip(text: live.transcript)
                            .padding(.top, 28)
                            .padding(.horizontal, 24)
                            .transition(.opacity)
                    }
                }

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
        HStack(spacing: 6) {
            Circle()
                .fill(Color.white)
                .frame(width: 6, height: 6)
                .opacity(recBadgePulsing ? 0.4 : 1.0)
                .animation(AurionAnimation.pulse, value: recBadgePulsing)
            Text(L("capture.rec"))
                .font(.system(size: 11, weight: .bold))
                .tracking(1)
                .foregroundColor(.white)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(Color.aurionRed)
        .clipShape(Capsule())
    }

    // MARK: - Stream Indicators

    private func streamCircle(_ label: String) -> some View {
        Text(label)
            .font(.system(size: 11, weight: .semibold))
            .foregroundColor(.aurionGold)
            .frame(width: 24, height: 24)
            .background(Color.white.opacity(0.10))
            .clipShape(Circle())
    }

    // MARK: - Audio Waveform

    private var audioWaveform: some View {
        HStack(alignment: .bottom, spacing: 4) {
            ForEach(0..<12, id: \.self) { i in
                RoundedRectangle(cornerRadius: 9999)
                    .fill(Color.aurionGold.opacity(0.8))
                    .frame(width: 3, height: waveHeight(for: i))
                    .animation(
                        .easeInOut(duration: Double.random(in: 0.8...1.4))
                        .repeatForever(autoreverses: true)
                        .delay(Double(i) * 0.05),
                        value: session.state == .recording
                    )
            }
        }
        .frame(height: 32)
    }

    private func waveHeight(for index: Int) -> CGFloat {
        let heights: [CGFloat] = [10, 18, 26, 14, 22, 30, 16, 8, 22, 28, 12, 18]
        return session.state == .recording ? heights[index] : 4
    }

    // MARK: - Live Captions

    /// Two-line italic gold-tint preview of the on-device speech recognizer's
    /// running transcript. Visually distinct from final SOAP output so the
    /// physician doesn't mistake interim text for the canonical note: italic,
    /// 0.85 opacity, gold-tinted on translucent navy. Auto-truncates to the
    /// last few sentences via `lineLimit(2)` + tail truncation so the strip
    /// never overflows the centered timer area.
    private func liveCaptionStrip(text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            // Tiny pulsing dot tells the physician this is live, not history.
            Circle()
                .fill(Color.aurionGold)
                .frame(width: 6, height: 6)
                .opacity(0.85)
                .padding(.top, 6)
            Text(text)
                .font(.system(size: 15, weight: .regular, design: .default))
                .italic()
                .foregroundColor(.aurionGold.opacity(0.85))
                .lineLimit(2)
                .truncationMode(.head)
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(Color.white.opacity(0.06))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 12, style: .continuous)
                .stroke(Color.aurionGold.opacity(0.18), lineWidth: 1)
        )
    }

    // MARK: - Consent Overlay

    private var consentOverlay: some View {
        ZStack {
            // Blurred navy overlay
            Color(red: 13/255, green: 27/255, blue: 62/255).opacity(0.78)
                .ignoresSafeArea()

            // Centered white card
            VStack(spacing: 14) {
                ZStack {
                    RoundedRectangle(cornerRadius: 16)
                        .fill(Color.aurionGoldBg)
                        .frame(width: 64, height: 64)
                    Image(systemName: "lock.shield")
                        .font(.system(size: 30))
                        .foregroundColor(.aurionGoldDark)
                }

                Text("Confirm Patient Consent")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundColor(.aurionNavy)
                    .multilineTextAlignment(.center)

                Text("Confirm the patient has been informed and consents to recording for note generation.")
                    .font(.system(size: 14))
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)

                AurionGoldButton(label: "Patient Has Consented", full: true) {
                    Task { await sessionManager.confirmConsent() }
                }

                Button("Cancel") {}
                    .font(.system(size: 14))
                    .foregroundColor(.aurionTextSecondary)
            }
            .padding(28)
            .background(Color.aurionCardBackground)
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.xl))
            .padding(28)
        }
    }

    // MARK: - Control Bar

    private var controlBar: some View {
        HStack(alignment: .center) {
            Spacer()

            // Left button: Pause/Resume (56px circle)
            Button(action: {
                if session.state == .recording { sessionManager.pauseRecording() }
                else if session.state == .paused { sessionManager.resumeRecording() }
            }) {
                Circle()
                    .fill(Color.white.opacity(0.10))
                    .frame(width: 56, height: 56)
                    .overlay(
                        Image(systemName: session.state == .paused ? "play.fill" : "pause.fill")
                            .font(.system(size: 22))
                            .foregroundColor(.white)
                    )
            }
            .opacity(session.state == .recording || session.state == .paused ? 1 : 0)

            Spacer()

            // Center: Gold record/stop button (78px)
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
                            .fill(
                                RadialGradient(
                                    colors: [Color.aurionGold.opacity(0.30), Color.aurionGold.opacity(0)],
                                    center: .center,
                                    startRadius: 0,
                                    endRadius: 50
                                )
                            )
                            .frame(width: 98, height: 98)
                            .scaleEffect(isPulsing ? 1.18 : 1.0)
                            .opacity(isPulsing ? 0.4 : 0.9)
                            .animation(AurionAnimation.pulse, value: isPulsing)
                    }

                    // Gold disc with 8pt translucent ring (design spec) and
                    // a deep gold drop shadow.
                    Circle()
                        .stroke(Color.aurionGold.opacity(0.18), lineWidth: 8)
                        .frame(width: 86, height: 86)

                    Circle()
                        .fill(Color.aurionGold)
                        .frame(width: 78, height: 78)
                        .shadow(color: Color.aurionGold.opacity(0.36), radius: 16, x: 0, y: 12)

                    if session.state == .recording || session.state == .paused {
                        RoundedRectangle(cornerRadius: 6)
                            .fill(Color.aurionNavy)
                            .frame(width: 30, height: 30)
                    }
                }
            }
            .disabled(!session.recordButtonEnabled && session.state != .recording && session.state != .paused)

            Spacer()

            // Right button: Stop (56px circle)
            Button(action: {
                Task { await sessionManager.stopRecording() }
            }) {
                Circle()
                    .fill(Color.white.opacity(0.10))
                    .frame(width: 56, height: 56)
                    .overlay(
                        Image(systemName: "stop.fill")
                            .font(.system(size: 22))
                            .foregroundColor(.white)
                    )
            }
            .opacity(session.state == .recording || session.state == .paused ? 1 : 0)

            Spacer()
        }
        .padding(.horizontal, 40)
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
