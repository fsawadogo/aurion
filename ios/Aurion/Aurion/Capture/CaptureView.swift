import SwiftUI

/// Main capture interface -- shown during active recording.
/// Full-screen minimal on both iPhone and iPad.
struct CaptureView: View {
    @ObservedObject var session: CaptureSession
    @EnvironmentObject var sessionManager: SessionManager
    /// Observed so the camera preview re-renders the moment the underlying
    /// AVCaptureSession transitions to .recording — gates the preview-layer
    /// mount on the actual capture-pipeline ready state, not just
    /// `session.state` which flips a tick earlier.
    @ObservedObject private var builtInSource = CaptureSourceRegistry.shared.builtIn
    @State private var elapsedTime: TimeInterval = 0
    @State private var timer: Timer?
    @State private var isPulsing = false
    @State private var recBadgePulsing = false
    @State private var showingFrameGallery = false
    /// Persisted across launches via UserDefaults. Default = true so the
    /// preview shows on first use; physicians can hide it for "background
    /// recording" — pocket / patient-not-on-camera scenarios — and the
    /// choice sticks for the next session.
    @AppStorage("aurion.show_camera_preview") private var showCameraPreview = true

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

                    // Stream indicators — top right per design. The "V" pill
                    // hides for audio-only modes so the physician can confirm
                    // the chosen capture mode at a glance. The preview toggle
                    // and frame-gallery shortcut sit next to them in
                    // multimodal mode, since neither has meaning otherwise.
                    HStack(spacing: 6) {
                        streamCircle("A")
                        if session.captureMode == .multimodal {
                            streamCircle("V")
                        }
                        streamCircle("S")
                        if session.captureMode == .multimodal {
                            previewToggleButton
                            framesButton
                        }
                    }
                }
                .padding(.horizontal, AurionSpacing.lg)
                .padding(.top, AurionSpacing.sm)

                if session.captureMode == .multimodal
                    && showCameraPreview
                    && (session.state == .recording || session.state == .paused) {
                    cameraPreviewCard
                        .padding(.top, AurionSpacing.md)
                        .padding(.horizontal, AurionSpacing.lg)
                        .transition(.opacity.combined(with: .scale(scale: 0.95)))
                }

                Spacer()

                // Large centered timer — monospaced 88pt per design
                VStack(spacing: 6) {
                    Text(formatTime(elapsedTime))
                        .font(.system(size: 88, weight: .medium, design: .monospaced))
                        .monospacedDigit()
                        .tracking(-2)
                        .foregroundColor(.white)
                        // Each second-tick smoothly morphs the digit instead
                        // of hard-cutting — iOS 17+ system content-transition.
                        .contentTransition(.numericText())
                        .animation(AurionAnimation.smooth, value: elapsedTime)

                    Text("Recording \u{00B7} \(session.captureMode.displayName)")
                        .font(.system(size: 13))
                        .tracking(0.4)
                        .foregroundColor(Color(red: 183/255, green: 192/255, blue: 214/255))

                    if session.isCollaborative {
                        collaborationPill
                            .padding(.top, 4)
                    }

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
        .sheet(isPresented: $showingFrameGallery) {
            FrameGalleryView(source: builtInSource)
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
                // Scale + opacity together — feels like a deliberate
                // heartbeat rather than a strobing dot. Driven by the
                // existing `recBadgePulsing` toggle so onChange already
                // owns the rhythm.
                .scaleEffect(recBadgePulsing ? 0.7 : 1.0)
                .opacity(recBadgePulsing ? 0.45 : 1.0)
                .animation(
                    .easeInOut(duration: 0.9).repeatForever(autoreverses: true),
                    value: recBadgePulsing
                )
            Text(L("capture.rec"))
                .font(.system(size: 11, weight: .bold))
                .tracking(1)
                .foregroundColor(.white)
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(
            Capsule()
                .fill(Color.aurionRed)
                // Subtle outer glow so the badge reads as "live" without
                // adding another animated layer.
                .shadow(color: Color.aurionRed.opacity(0.4), radius: 8, x: 0, y: 0)
        )
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

    // MARK: - Frames Button

    /// Top-bar shortcut that opens the live `FrameGalleryView` sheet. The
    /// gold badge shows the current frame count so the physician sees the
    /// capture pipeline accruing data in real time — a quiet trust signal
    /// without staring at the preview the whole time. Only shown when a
    /// `BuiltInCaptureSource` is the active video source (external sources
    /// like Ray-Ban Meta don't currently expose buffered frames).
    @ViewBuilder
    private var framesButton: some View {
        if let _ = CaptureSourceRegistry.shared.activeVideoSource as? BuiltInCaptureSource {
            Button {
                AurionHaptics.selection()
                showingFrameGallery = true
            } label: {
                ZStack(alignment: .topTrailing) {
                    Image(systemName: "photo.stack")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundColor(.aurionGold)
                        .frame(width: 24, height: 24)
                        .background(Color.white.opacity(0.10))
                        .clipShape(Circle())

                    if builtInSource.capturedFrames.count > 0 {
                        Text("\(min(builtInSource.capturedFrames.count, 99))")
                            .font(.system(size: 8, weight: .bold))
                            .foregroundColor(.aurionNavy)
                            .padding(.horizontal, 4)
                            .padding(.vertical, 1)
                            .background(Color.aurionGold)
                            .clipShape(Capsule())
                            .offset(x: 6, y: -4)
                            .contentTransition(.numericText())
                            .animation(
                                AurionAnimation.smooth,
                                value: builtInSource.capturedFrames.count
                            )
                    }
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel("View captured frames")
        }
    }

    // MARK: - Camera Preview Toggle

    /// Eye/eye-slash button — flips the persisted `showCameraPreview` flag.
    /// Tapping while recording immediately hides/shows the preview without
    /// affecting the capture pipeline (the AVCaptureSession keeps running;
    /// only the preview-layer SwiftUI view is mounted/unmounted).
    private var previewToggleButton: some View {
        Button {
            AurionHaptics.selection()
            withAnimation(AurionAnimation.smooth) {
                showCameraPreview.toggle()
            }
        } label: {
            Image(systemName: showCameraPreview ? "eye.fill" : "eye.slash.fill")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.aurionGold)
                .frame(width: 24, height: 24)
                .background(Color.white.opacity(0.10))
                .clipShape(Circle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(
            showCameraPreview ? "Hide camera preview (background recording)"
                              : "Show camera preview"
        )
    }

    // MARK: - Camera Preview

    /// Live preview card — anchors to the active BuiltInCaptureSource's
    /// AVCaptureSession so we share inputs/outputs with the frame extractor
    /// (no second mic claim, no resource conflict). Shown only when the
    /// underlying AVCaptureSession is actually running (gated on
    /// `isReadyForPreview`) AND the physician hasn't toggled it off.
    ///
    /// Sized to fill the screen width (minus the standard horizontal padding
    /// applied by the caller) at a 4:3 landscape aspect ratio. The native
    /// camera capture is portrait, but `videoGravity = .resizeAspectFill`
    /// on the preview layer crops the top/bottom of that portrait frame so
    /// the visible card is wide — better for confirming the patient is
    /// centered in the shot.
    @ViewBuilder
    private var cameraPreviewCard: some View {
        let registry = CaptureSourceRegistry.shared
        // Only render when the active video source is the built-in camera
        // AND it has finished bringing up the capture pipeline. The latter
        // gates out a brief window (a few hundred ms after Start) where
        // `session.state == .recording` but the AVCaptureSession itself
        // hasn't yet finished its async configure+startRunning. Attaching
        // a preview layer during that window caused EXC_BAD_ACCESS on
        // AVFoundation's render thread.
        if let builtIn = registry.activeVideoSource as? BuiltInCaptureSource,
           builtIn.isReadyForPreview {
            CameraPreviewLayer(session: registry.builtIn.previewSession)
                .frame(maxWidth: .infinity)
                .aspectRatio(4.0 / 3.0, contentMode: .fit)
                .clipShape(RoundedRectangle(cornerRadius: 18))
                .overlay(
                    RoundedRectangle(cornerRadius: 18)
                        .stroke(Color.aurionGold.opacity(0.35), lineWidth: 1)
                )
                .shadow(color: .black.opacity(0.35), radius: 16, x: 0, y: 4)
        }
    }

    // MARK: - Audio Waveform

    /// Live waveform driven by the active capture source's RMS audio level
    /// (`builtInSource.audioLevel`, 0…1). 21 bars with a phase-offset
    /// envelope so the wave appears to ripple across the row in time with
    /// the mic input. Each bar height = idle baseline + envelope × current
    /// audio level — so silence shows a thin flat row, loud speech swells.
    /// Spring animation gives it a soft, organic motion rather than the
    /// previous random-easing flicker.
    private var audioWaveform: some View {
        let bars = 21
        return HStack(alignment: .center, spacing: 3) {
            ForEach(0..<bars, id: \.self) { i in
                Capsule()
                    .fill(
                        LinearGradient(
                            colors: [.aurionGoldLight, .aurionGold],
                            startPoint: .top, endPoint: .bottom
                        )
                    )
                    .frame(width: 3, height: waveBarHeight(for: i, of: bars))
                    .animation(
                        .interpolatingSpring(stiffness: 120, damping: 14),
                        value: builtInSource.audioLevel
                    )
            }
        }
        .frame(height: 40)
    }

    /// Per-bar height as a function of bar index + current audio level. The
    /// envelope is a soft sine bump centered on the row so middle bars are
    /// taller than edge bars at the same audio level — same shape an
    /// equalizer would draw.
    private func waveBarHeight(for index: Int, of total: Int) -> CGFloat {
        guard session.state == .recording else { return 4 }
        let center = Double(total) / 2.0
        let distance = abs(Double(index) - center)
        // Sine envelope — 1.0 at center, ~0.35 at edges.
        let envelope = 0.35 + 0.65 * cos((distance / center) * (.pi / 2))
        // Smooth audio level — clamp + amplify so the bars never go flat
        // mid-speech but also can't peg at max constantly.
        let level = CGFloat(min(1.0, max(0.15, Double(builtInSource.audioLevel) * 1.6)))
        return 6 + 30 * level * envelope
    }

    // MARK: - Collaboration Pill

    /// Shared-encounter indicator. Renders when the encounter type isn't
    /// solo doctor+patient — names every non-physician participant so
    /// nurses, residents, and PAs see themselves on the capture screen
    /// and the room understands they're part of one unified note.
    private var collaborationPill: some View {
        let names = session.participants.map { $0.name }
        // When participants are named (allied or trainee), show the names
        // after a separator. With no named participants (encounter type set
        // but list empty), the pill falls back to just the static label so
        // it doesn't read "Shared encounter · Shared encounter".
        let summary: String? = {
            if names.isEmpty { return nil }
            if names.count == 1 { return names[0] }
            if names.count == 2 { return "\(names[0]) + \(names[1])" }
            return "\(names[0]) + \(names.count - 1) others"
        }()
        let label: String = summary.map { "Shared encounter \u{00B7} \($0)" }
            ?? "Shared encounter"
        return HStack(spacing: 6) {
            Image(systemName: "person.2.fill")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.aurionGold)
            Text(label)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.white.opacity(0.92))
                .lineLimit(1)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 5)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
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
