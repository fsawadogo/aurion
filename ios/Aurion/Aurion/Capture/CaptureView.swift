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
    /// Persisted toggle for the on-screen live transcription UI (caption strip
    /// + draft-note preview). Default = true. Hiding it keeps the canonical
    /// Whisper batch transcription on stop fully intact — it only declutters
    /// the recording screen (useful over the immersive camera).
    @AppStorage("aurion.show_live_transcription") private var showLiveTranscription = true
    /// Per-session dismissal of the "captions unavailable" hint. Reset each
    /// time the view recomposes (i.e. each capture session) so the hint
    /// resurfaces if the cause persists; per-launch persistence would hide
    /// a permanently denied permission and never resurface it.
    @State private var captionsHintDismissed = false

    var body: some View {
        ZStack {
            // Two presentations of the same live session:
            //   • Immersive — full-bleed camera (iPhone Camera-app feel) with
            //     floating controls over scrims. Active only when video is
            //     being captured, the preview is toggled on, the session is
            //     live, and the AVCaptureSession has finished coming up.
            //   • Standard — the navy-gradient + big-timer layout. Audio-only,
            //     "background recording" (preview off), the pre-ready window,
            //     and the pre-consent gate all live here.
            if isImmersiveCamera {
                immersiveLayout
                    .transition(.opacity)
            } else {
                standardLayout
                    .transition(.opacity)
            }
        }
        .animation(AurionAnimation.smooth, value: isImmersiveCamera)
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

    /// True when the full-bleed camera presentation should take over. Gated on
    /// the same `isReadyForPreview` flag the old inset card used — attaching a
    /// preview layer before the AVCaptureSession finishes its async
    /// configure+startRunning caused EXC_BAD_ACCESS on the render thread. The
    /// @ObservedObject `builtInSource` invalidates the view when that flag
    /// flips, so this recomputes the moment the pipeline is ready.
    private var isImmersiveCamera: Bool {
        session.captureMode.includesVideo
            && showCameraPreview
            && (session.state == .recording || session.state == .paused)
            && (CaptureSourceRegistry.shared.activeVideoSource as? BuiltInCaptureSource)?
                .isReadyForPreview == true
    }

    // MARK: - Immersive Layout (full-bleed camera)

    /// iPhone Camera-app style presentation: the live preview fills the whole
    /// screen and controls float over translucent scrims. Used on both iPhone
    /// and iPad. All text/icons here are FIXED-LIGHT — they sit over live
    /// camera, so adaptive / navy foregrounds would be illegible.
    private var immersiveLayout: some View {
        ZStack {
            // Solid backdrop so the brief preview-mount window never flashes
            // through to whatever is behind the capture screen.
            Color.black.ignoresSafeArea()

            immersiveCameraPreview
                .ignoresSafeArea()

            // Stage 1 spinner stays centered over the camera through the
            // hand-off out of immersive mode.
            if session.state == .processingStage1 {
                processingIndicator
                    .transition(.opacity)
            }

            VStack(spacing: 0) {
                immersiveTopBar
                Spacer(minLength: 0)
                immersiveBottomCluster
            }
        }
        .animation(AurionAnimation.smooth, value: session.isConsentConfirmed)
        .animation(AurionAnimation.smooth, value: session.state)
    }

    /// Full-bleed live preview. Keeps its own `isReadyForPreview` gate even
    /// though `isImmersiveCamera` already checked it — belt-and-suspenders
    /// against the render-thread EXC_BAD_ACCESS. `CameraPreviewLayer` already
    /// applies `.resizeAspectFill`, so it crops to fill the screen.
    @ViewBuilder
    private var immersiveCameraPreview: some View {
        let registry = CaptureSourceRegistry.shared
        if let builtIn = registry.activeVideoSource as? BuiltInCaptureSource,
           builtIn.isReadyForPreview {
            CameraPreviewLayer(session: registry.builtIn.previewSession)
        }
    }

    /// Floating top bar over a top scrim. Content respects the safe area
    /// (clears the notch / Dynamic Island); the scrim bleeds up underneath so
    /// controls stay legible over any camera content.
    private var immersiveTopBar: some View {
        HStack {
            specialtyBadge

            Spacer()

            // Compact status replaces the big 88pt timer in this layout.
            HStack(spacing: 8) {
                if session.state == .recording {
                    recBadge
                        .transition(AurionTransition.scaleIn)
                }
                Text(formatTime(elapsedTime))
                    .font(.system(size: 17, weight: .semibold, design: .monospaced))
                    .monospacedDigit()
                    .foregroundColor(.white)
                    .contentTransition(.numericText())
                    .animation(AurionAnimation.smooth, value: elapsedTime)
                    .accessibilityLabel(L("capture.a11yElapsed"))
                    .accessibilityValue(accessibleElapsedTime)
            }

            Spacer()

            HStack(spacing: 6) {
                streamIndicators
                maskingShield
                consentBadge
            }
        }
        .padding(.horizontal, AurionSpacing.lg)
        .padding(.top, AurionSpacing.sm)
        .padding(.bottom, AurionSpacing.md)
        .background(
            LinearGradient(
                colors: [Color.black.opacity(0.55), Color.black.opacity(0)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea(edges: .top)
        )
    }

    /// Floating bottom cluster over a bottom scrim: waveform, gated live
    /// transcription, and the transport controls. Content respects the home
    /// indicator; the scrim bleeds down underneath.
    private var immersiveBottomCluster: some View {
        VStack(spacing: AurionSpacing.md) {
            if session.state == .recording {
                audioWaveform
            }

            liveTranscriptionSection

            if !session.isConsentConfirmed {
                consentOverlay
                    .transition(AurionTransition.scaleIn)
            } else {
                controlBar
            }
        }
        .padding(.top, AurionSpacing.lg)
        .background(
            LinearGradient(
                colors: [Color.black.opacity(0), Color.black.opacity(0.55)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea(edges: .bottom)
        )
    }

    // MARK: - Stream Indicators (top-bar right cluster)

    /// A/V/S stream dots plus the preview (eye) and frames shortcuts. Shared by
    /// both layouts; the immersive top bar appends the masking shield.
    private var streamIndicators: some View {
        HStack(spacing: 6) {
            streamCircle("A")
            if session.captureMode.includesVideo {
                streamCircle("V")
            }
            if sessionManager.screenCapture.isRecording {
                streamCircle("S")
            }
            if session.captureMode.includesVideo {
                previewToggleButton
                framesButton
            }
        }
    }

    // MARK: - Live Transcription Section

    /// Live captions + draft-note preview, gated on the persisted
    /// `showLiveTranscription` toggle. Identical in both layouts so it lives in
    /// one place; the container owns the surrounding spacing. The Whisper batch
    /// transcription on stop is unaffected — this only hides the live UI.
    @ViewBuilder
    private var liveTranscriptionSection: some View {
        if showLiveTranscription,
           let live = sessionManager.liveTranscriber,
           session.state == .recording || session.state == .paused {
            VStack(spacing: 14) {
                if live.isAvailable, !live.transcript.isEmpty {
                    liveCaptionStrip(text: live.transcript)
                } else if !live.isAvailable,
                          let reason = live.unavailableReason,
                          !captionsHintDismissed {
                    liveCaptionsUnavailableChip(reason: reason)
                }

                if live.isAvailable {
                    LivePreviewOverlay(
                        sessionId: session.id,
                        partialTranscript: live.transcript,
                        outputLanguage: sessionManager.sessionLanguageForLivePreview
                    )
                }
            }
            .padding(.horizontal, 24)
            .transition(.opacity)
        }
    }

    // MARK: - Live Transcription Toggle

    /// Captions toggle — flips the persisted `showLiveTranscription` flag so the
    /// physician can hide the live caption strip + draft preview (e.g. to keep
    /// the camera view clean) without touching the canonical batch
    /// transcription on stop. Gold-on-translucent like the eye toggle, 44pt hit
    /// target.
    private var transcriptionToggleButton: some View {
        Button {
            AurionHaptics.impact(.light)
            withAnimation(AurionAnimation.smooth) {
                showLiveTranscription.toggle()
            }
        } label: {
            Image(systemName: showLiveTranscription ? "captions.bubble.fill" : "captions.bubble")
                .font(.system(size: 11, weight: .semibold))
                .foregroundColor(.aurionGold)
                .frame(width: 24, height: 24)
                .background(Color.white.opacity(0.10))
                .clipShape(Circle())
        }
        .frame(minWidth: 44, minHeight: 44)
        .contentShape(Rectangle())
        .buttonStyle(.plain)
        .accessibilityLabel(
            showLiveTranscription ? L("capture.a11yHideTranscription")
                                  : L("capture.a11yShowTranscription")
        )
    }

    // MARK: - Masking Reassurance Shield

    /// Privacy reassurance over the live camera. Faces are masked on-device
    /// BEFORE any frame is uploaded (masking runs after record-stop — there is
    /// no real-time masking), so this is a quiet trust signal, not a live
    /// status. Non-interactive; meaning is carried by the VoiceOver label.
    private var maskingShield: some View {
        Image(systemName: "shield.lefthalf.filled")
            .font(.system(size: 13, weight: .semibold))
            .foregroundColor(.aurionGold)
            .frame(width: 24, height: 24)
            .background(Color.white.opacity(0.10))
            .clipShape(Circle())
            .accessibilityLabel(L("capture.maskingReassurance"))
    }

    // MARK: - Consent Reassurance Badge

    /// Compact consent indicator for the immersive (full-screen camera) layout,
    /// which has no room for the standard consent chip. Appears once consent is
    /// confirmed — a quiet trust signal that the session was opened with patient
    /// consent. Until then the bottom cluster shows the full consent prompt, so
    /// a "pending" badge here would be redundant. Deliberately GREEN (not the
    /// cluster's gold accent): green reads as "confirmed/safe" and keeps consent
    /// visually distinct from the adjacent gold masking shield. Fixed green —
    /// not an adaptive status token — because this always sits over the camera's
    /// dark scrim. Non-interactive; method + time are carried by the VoiceOver
    /// value. Animates in via the `isConsentConfirmed` animation on the layout
    /// (same `.transition` pattern as `recBadge`).
    @ViewBuilder private var consentBadge: some View {
        if session.isConsentConfirmed {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.aurionGreen)
                .frame(width: 24, height: 24)
                .background(Color.white.opacity(0.10))
                .clipShape(Circle())
                .transition(AurionTransition.scaleIn)
                .accessibilityLabel(L("capture.consentBadgeA11y"))
                .accessibilityValue(consentBadgeA11yValue)
        }
    }

    /// Method + time for the consent badge's VoiceOver value, mirroring the
    /// standard consent chip. Empty when consent details are unavailable.
    private var consentBadgeA11yValue: String {
        guard let method = session.consentMethod,
              let at = session.consentConfirmedAt else { return "" }
        return L("capture.consentChip", method.displayName,
                 Self.consentTimeFormatter.string(from: at))
    }

    // MARK: - Standard Layout (navy gradient + big timer)

    /// The original capture presentation. The camera is intentionally hidden
    /// here (audio-only, preview toggled off for "background recording", the
    /// not-yet-ready window, or pre-consent) — the full-screen camera lives in
    /// the immersive layout, reachable via the eye toggle once the pipeline is
    /// up.
    private var standardLayout: some View {
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

                    // Stream indicators reflect what SessionManager actually
                    // orchestrated — audio-only modes keep the V pill and
                    // camera preview hidden because the camera is never lit.
                    streamIndicators
                }
                .padding(.horizontal, AurionSpacing.lg)
                .padding(.top, AurionSpacing.sm)

                // The camera is shown full-screen via the immersive layout
                // (eye toggle) — in this navy layout it stays hidden by design
                // ("background recording").

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
                        .accessibilityLabel(L("capture.a11yElapsed"))
                        // VoiceOver reads "minutes:seconds" rather than the
                        // raw digits so e.g. "01:24" speaks as "1 minute 24
                        // seconds" — clearer when the screen is in a coat
                        // pocket and the clinician is checking on capture.
                        .accessibilityValue(accessibleElapsedTime)

                    Text(L("capture.recordingMode", session.captureMode.displayName))
                        .aurionFont(13, relativeTo: .footnote)
                        .tracking(0.4)
                        .foregroundColor(Color.aurionOnNavySecondary)

                    // On Stop the side controls fade out and the timer
                    // freezes; without this the screen reads as hung while
                    // Stage 1 runs. A brief in-view spinner makes the
                    // transcribe→assemble wait legible.
                    if session.state == .processingStage1 {
                        processingIndicator
                            .padding(.top, 24)
                            .transition(.opacity)
                    }

                    if let method = session.consentMethod, let timestamp = session.consentConfirmedAt {
                        consentChip(method: method, at: timestamp)
                            .padding(.top, 6)
                    }

                    if session.isCollaborative {
                        collaborationPill
                            .padding(.top, 4)
                    }

                    // Audio waveform bars
                    if session.state == .recording {
                        audioWaveform
                            .padding(.top, 28)
                    }

                    // Live captions + draft-note preview (gated on the
                    // showLiveTranscription toggle). Whisper batch
                    // transcription on stop is unaffected.
                    liveTranscriptionSection
                        .padding(.top, 28)
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
                            // Brand-navy on gold pill — stays fixed in both modes.
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
            // Keep the 24pt visual circle but expand the touch region to the
            // HIG-minimum 44pt so it isn't easy to miss-tap during a live
            // encounter.
            .frame(minWidth: 44, minHeight: 44)
            .contentShape(Rectangle())
            .buttonStyle(.plain)
            .accessibilityLabel(L("capture.a11yViewFrames"))
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
        // Expand the tap target to the HIG-minimum 44pt while keeping the
        // 24pt visual circle.
        .frame(minWidth: 44, minHeight: 44)
        .contentShape(Rectangle())
        .buttonStyle(.plain)
        .accessibilityLabel(
            showCameraPreview ? L("capture.a11yHidePreview")
                              : L("capture.a11yShowPreview")
        )
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
        // Purely decorative — VoiceOver shouldn't announce each of the
        // 21 bars. The presence of audio is already conveyed by the
        // timer's running state.
        .accessibilityHidden(true)
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

    // MARK: - Processing Indicator

    /// Shown while Stage 1 runs (record_stop → stage1_delivered). The timer
    /// is intentionally frozen here, so a spinner + label is the only signal
    /// that work is in flight. Decorative spinner; the label carries the
    /// meaning for VoiceOver.
    private var processingIndicator: some View {
        HStack(spacing: 10) {
            ProgressView()
                .tint(.aurionGold)
            Text(L("capture.processing"))
                .aurionFont(14, weight: .medium, relativeTo: .subheadline)
                .foregroundColor(Color.aurionOnNavySecondary)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
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
                .aurionFont(12, weight: .medium, relativeTo: .caption)
                .foregroundColor(.white.opacity(0.92))
                .lineLimit(1)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 5)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
    }

    // MARK: - Live Captions

    /// One-line muted chip explaining why live captions aren't showing
    /// (permission denied, no on-device speech model for the current locale,
    /// recognizer temporarily offline). Dismissable per-session so the
    /// physician acknowledges and recording UI returns to its normal layout.
    /// Recording itself is never affected — Whisper batch transcription on
    /// stop is the canonical source of truth.
    private func liveCaptionsUnavailableChip(reason: UnavailableReason) -> some View {
        let message = Self.captionsUnavailableMessage(for: reason)
        return HStack(alignment: .center, spacing: 8) {
            Image(systemName: "captions.bubble")
                .font(.system(size: 12, weight: .semibold))
                .foregroundColor(.white.opacity(0.55))
            Text(message)
                .aurionFont(13, weight: .medium, relativeTo: .footnote)
                .foregroundColor(.white.opacity(0.7))
                .lineLimit(1)
                .truncationMode(.tail)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button {
                withAnimation(AurionAnimation.smooth) {
                    captionsHintDismissed = true
                }
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundColor(.white.opacity(0.55))
                    .padding(6)
                    .contentShape(Rectangle())
            }
            .accessibilityLabel(Text(L("captions.unavailable.dismissA11y")))
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .fill(Color.white.opacity(0.05))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10, style: .continuous)
                .stroke(Color.white.opacity(0.12), lineWidth: 1)
        )
    }

    /// Map the LiveTranscriber's structured unavailable reason to a localized
    /// one-liner. Static so it doesn't accidentally close over view state.
    private static func captionsUnavailableMessage(for reason: UnavailableReason) -> String {
        switch reason {
        case .notAuthorized:     return L("captions.unavailable.permission")
        case .noOnDeviceModel:   return L("captions.unavailable.model")
        case .recognizerOffline: return L("captions.unavailable.offline")
        case .localeUnsupported: return L("captions.unavailable.locale")
        }
    }

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
                .aurionFont(15, weight: .regular, relativeTo: .body)
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

    // MARK: - Consent Audit Chip

    private static let consentTimeFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm:ss"
        return f
    }()

    /// Always-visible record of how and when consent was given. Compliance
    /// can see at a glance that the session was opened with patient consent
    /// and which method was used.
    private func consentChip(method: ConsentMethod, at timestamp: Date) -> some View {
        HStack(spacing: 6) {
            Image(systemName: method.icon)
                .font(.system(size: 10, weight: .semibold))
            Text(L("capture.consentChip", method.displayName, Self.consentTimeFormatter.string(from: timestamp)))
                .aurionFont(12, weight: .medium, relativeTo: .caption)
        }
        .foregroundColor(.aurionGold)
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
    }

    // MARK: - Consent Overlay

    /// Selected method persists across re-renders within this consent step.
    @State private var pendingConsentMethod: ConsentMethod = .verbal

    private var consentOverlay: some View {
        ZStack {
            Color.aurionNavy.opacity(0.78)
                .ignoresSafeArea()

            VStack(spacing: 14) {
                ZStack {
                    RoundedRectangle(cornerRadius: 16)
                        .fill(Color.aurionGoldBg)
                        .frame(width: 64, height: 64)
                    Image(systemName: "lock.shield")
                        .font(.system(size: 30))
                        .foregroundColor(.aurionGoldDark)
                }

                Text(L("capture.consentTitle"))
                    .aurionFont(20, weight: .semibold, relativeTo: .title3)
                    .foregroundColor(.aurionTextPrimary)
                    .multilineTextAlignment(.center)

                Text(L("capture.consentSub"))
                    .aurionFont(14, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)

                consentMethodPicker

                AurionGoldButton(label: L("capture.consentButton"), full: true) {
                    Task { await sessionManager.confirmConsent(method: pendingConsentMethod) }
                }

                Button(L("common.cancel")) {
                    // Abort the consent-pending session and return to the
                    // dashboard. Was an empty closure — Cancel did nothing,
                    // trapping the user on the consent gate (#294). endSession
                    // is the established teardown (drops the staged WAV, ends
                    // the Live Activity, sets uiState = .idle).
                    AurionHaptics.impact(.light)
                    sessionManager.endSession()
                }
                    .aurionFont(14, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
            }
            .padding(28)
            .background(Color.aurionCardBackground)
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.xl))
            .padding(28)
        }
    }

    /// Segmented picker so the clinician records HOW consent was obtained.
    /// The selection flows into the audit log via SessionManager.
    private var consentMethodPicker: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(L("capture.consentMethodQ"))
                .aurionFont(13, weight: .medium, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
            Picker(L("capture.consentMethodQ"), selection: $pendingConsentMethod) {
                ForEach(ConsentMethod.allCases) { method in
                    Text(method.displayName).tag(method)
                }
            }
            .pickerStyle(.segmented)
            .labelsHidden()
        }
    }

    // MARK: - Control Bar

    private var controlBar: some View {
        VStack(spacing: AurionSpacing.md) {
            // Utility row: live-transcription (captions) toggle. Shown only
            // while live so the pre-record bar stays a single record button;
            // sits above the transport row so the record button stays centered.
            if session.state == .recording || session.state == .paused {
                HStack {
                    Spacer()
                    transcriptionToggleButton
                }
                .padding(.horizontal, 40)
            }

            // Transport controls: pause/resume · record/stop · stop
            HStack(alignment: .center) {
            Spacer()

            // Left button: Pause/Resume (56px circle)
            Button(action: {
                AurionHaptics.impact(.light)
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
            .accessibilityLabel(session.state == .paused ? L("capture.a11yResume") : L("capture.a11yPause"))
            .accessibilityHint(session.state == .paused
                               ? L("capture.a11yResumeHint")
                               : L("capture.a11yPauseHint"))

            Spacer()

            // Center: Gold record/stop button (78px)
            Button(action: {
                AurionHaptics.impact(.medium)
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
            // Two distinct disable rules combined:
            //   1. Before recording starts: respect recordButtonEnabled
            //      (consent required, etc.)
            //   2. After recording starts: block Stop until the minimum
            //      duration elapses so the audio delegate has time to
            //      deliver its first buffer. Without this guard, tapping
            //      Start → Stop in <2s leaves audioPCMData empty and the
            //      next screen shows "Recording was too short".
            .disabled(
                ((session.state != .recording && session.state != .paused) && !session.recordButtonEnabled)
                || ((session.state == .recording || session.state == .paused) && elapsedTime < SessionManager.minimumRecordingSeconds)
            )
            .accessibilityLabel(
                (session.state == .recording || session.state == .paused)
                    ? L("capture.a11yStop")
                    : L("capture.a11yStart")
            )
            .accessibilityHint(
                (session.state == .recording || session.state == .paused)
                    ? L("capture.a11yStopHint")
                    : L("capture.a11yStartHint")
            )

            Spacer()

            // Right button: Stop (56px circle)
            Button(action: {
                AurionHaptics.impact(.medium)
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
            // Same minimum-duration guard as the center record/stop button.
            // Audio delegate buffers don't arrive until ~500ms–2s after
            // capture starts; stopping inside that window produces an
            // empty PCM buffer.
            .disabled(elapsedTime < SessionManager.minimumRecordingSeconds)
            .accessibilityLabel(L("capture.a11yStop"))
            .accessibilityHint(L("capture.a11yStopHint"))

            Spacer()
            }
            .padding(.horizontal, 40)
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

    /// VoiceOver-friendly form of the elapsed time. Uses
    /// `DateComponentsFormatter` so users hear "1 minute 24 seconds"
    /// instead of "zero one colon two four", which is unintelligible
    /// from a coat pocket.
    private var accessibleElapsedTime: String {
        let formatter = DateComponentsFormatter()
        formatter.allowedUnits = [.hour, .minute, .second]
        formatter.unitsStyle = .spellOut
        formatter.zeroFormattingBehavior = .dropLeading
        return formatter.string(from: elapsedTime) ?? "\(Int(elapsedTime)) seconds"
    }
}
