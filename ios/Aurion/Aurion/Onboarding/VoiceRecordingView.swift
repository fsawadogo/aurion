import SwiftUI
import AVFoundation
import Combine
import UIKit

/// Screen 3 — Voice recording prompt.
/// Records 30–60 seconds of physician speech to a temp file. The file URL is
/// passed to VoiceProcessingView which extracts a fingerprint on-device,
/// saves it to Keychain, and deletes the audio file.
///
/// Motion: idle record button has a slow gold halo (matches the design's
/// `--sh-record-pulse` token); during recording, the halo accelerates to
/// the 1.6s breathing cycle. Sentence rows fade green as they complete.
/// Audio bars are deterministic + audio-level reactive (no per-render
/// random jitter).
///
/// Marie bug-bash:
///   * Bug B — sentence rows used to ellipsis-truncate on iPhone Mini.
///     We now let `Text` wrap naturally and pin vertical sizing with
///     `.fixedSize(horizontal: false, vertical: true)` so the card
///     grows to fit the full clinical sentence.
///   * Bug C — per-sentence "completion" used to advance purely on
///     elapsed recording time (8s per row). A silent user would see all
///     four rows turn green and a successful enrollment that
///     fingerprinted nothing. We now sample the recorder's average
///     power every 0.1s, accumulate per-sentence windows, and only
///     turn a row green when (duration ≥ 2.0s) AND (mean dBFS > -45).
///     A failing row stays amber with "We didn't hear you — try again."
///     and disables Continue until the user re-records.
struct VoiceRecordingView: View {
    let onComplete: (URL) -> Void
    /// Optional skip handler for the mic-permission dead-end. Voice
    /// enrollment is optional, and when the OS has denied the microphone
    /// the clinician cannot record at all — so the host flow can pass a
    /// skip closure to let them proceed past this screen. Defaults to
    /// `nil` (Skip hidden) so the view still compiles standalone and in
    /// flows that don't offer a skip; the "Open Settings" recovery is
    /// always available regardless.
    var onSkip: (() -> Void)? = nil

    @StateObject private var recorder = VoiceRecorder()
    @Environment(\.scenePhase) private var scenePhase
    /// Index of the active sentence — advances on the 8s sentence-tick
    /// boundary regardless of speech quality so the user sees the prompt
    /// move forward. Quality is evaluated separately per row.
    @State private var sentenceIndex = 0
    /// Per-sentence pass/fail flags from the on-device quality gate.
    /// `nil` = not yet evaluated (the recorder hasn't reached this
    /// window). `true` = green (duration + dBFS thresholds met).
    /// `false` = amber + "we didn't hear you".
    @State private var sentenceQuality: [Bool?] = Array(repeating: nil, count: 4)
    @State private var canProceed = false
    @State private var permissionDenied = false
    /// Set when stop fires but at least one sentence row failed the
    /// quality gate. Shown as a banner above the record button so the
    /// user knows WHY Continue is disabled.
    @State private var qualityCheckFailed = false

    private let minimumDuration: TimeInterval = 15
    /// Bug C — duration floor per sentence window. 2.0s is the spec
    /// threshold. Even at a leisurely pace, reading any of the four
    /// sentences below takes well past 2s — anything under is silence
    /// or a barely-audible mumble.
    private let perSentenceMinimumDurationSec: TimeInterval = 2.0
    /// Bug C — mean amplitude floor per sentence window, expressed as
    /// AVAudioRecorder.averagePower (dBFS, -60..0 in practice). Spec
    /// threshold is -45 dBFS — quiet normal speech sits around -30 to
    /// -20 dBFS at conversational distance; -45 catches the "phone in
    /// pocket, user said nothing" failure mode.
    private let perSentenceMeanDbFloor: Float = -45.0

    private let sentences = [
        L("onboarding.voiceRec.sentence1"),
        L("onboarding.voiceRec.sentence2"),
        L("onboarding.voiceRec.sentence3"),
        L("onboarding.voiceRec.sentence4"),
    ]

    /// 8-second sentence window — the user reads one sentence per
    /// `sentenceInterval` so a 4-sentence card covers ~32s, comfortably
    /// inside the 30–60s embedding-quality range.
    private let sentenceInterval: TimeInterval = 8.0

    var body: some View {
        // Marie (2026-06-06): at larger Dynamic Type sizes the previous
        // single VStack overflowed the viewport — the instruction, 4
        // sentence rows, audio bars, record button, status text, and
        // Continue button all stacked vertically with `Spacer()` between,
        // but Spacer() can't shrink content; once total height > screen
        // height the Continue button falls off the bottom and the user
        // is hard-stuck on onboarding.
        //
        // Two-zone layout fixes this for every Dynamic Type size:
        //   1. Top content (instruction + sentence list + live audio
        //      bars + status) lives in a ScrollView so it can grow
        //      arbitrarily and stays reachable via scroll.
        //   2. Actionable controls (record button + Continue button +
        //      re-record link) ride in a .safeAreaInset(edge: .bottom)
        //      footer so they're always tappable — even at AX5 / dyslexia
        //      modes where the top content takes the entire viewport.
        //
        // Test matrix when retouching: Default / Larger / Largest /
        // AX5 (Accessibility XL). All must keep Continue visible on
        // an iPhone Mini.
        ScrollView {
            VStack(spacing: 24) {
                Text(L("onboarding.voiceRec.instruction"))
                    .aurionFont(20, weight: .semibold, relativeTo: .title3)
                    .foregroundColor(.aurionTextPrimary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .aurionStagger(order: 0, baseDelay: 0.05)

                sentenceList
                    .aurionStagger(order: 1)

                if recorder.isRecording {
                    VStack(spacing: 14) {
                        AurionAudioBars(level: recorder.audioLevel)
                            .padding(.horizontal, 40)
                        Text(String(format: "%.0fs", recorder.duration))
                            .aurionFont(22, weight: .regular, relativeTo: .title2)
                            .monospacedDigit()
                            .foregroundColor(.aurionTextPrimary)
                    }
                    .transition(.opacity)
                }

                Text(statusText)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(statusColor)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, 20)
                    .transition(.opacity)
                    .id(statusText)
                    .animation(.aurionIOS, value: statusText)
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            // Bottom padding inside the ScrollView so the last content
            // row doesn't kiss the inset footer's top edge when scrolled
            // all the way down.
            .padding(.bottom, 12)
        }
        .safeAreaInset(edge: .bottom) {
            VStack(spacing: 12) {
                recordButton

                // Mic-denied recovery: the record button is disabled, so
                // without this the clinician is hard-stuck. "Open Settings"
                // deep-links to the app's privacy page; returning grants
                // are picked up by the scenePhase re-check below. Skip is
                // offered when the host flow wires one (enrollment is
                // optional).
                if permissionDenied {
                    AurionGoldButton(label: L("onboarding.voiceRec.openSettings"), full: true) {
                        openSettings()
                    }
                    .transition(.opacity)

                    if let onSkip {
                        Button(L("common.skip")) { onSkip() }
                            .aurionFont(12, relativeTo: .caption)
                            .foregroundColor(.aurionTextPrimary)
                    }
                }

                if canProceed, let url = recorder.lastRecordingURL {
                    AurionGoldButton(label: L("setup.continue"), full: true) { onComplete(url) }
                        .transition(.move(edge: .bottom).combined(with: .opacity))
                }

                Button(L("onboarding.voiceRec.rerecord")) { resetRecording() }
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionTextPrimary)
                    .frame(minHeight: 44)
                    .opacity(canProceed || qualityCheckFailed ? 1 : 0)
                    // An opacity-0 view still receives taps; gate hit-testing
                    // so the hidden re-record link can't silently reset the
                    // recording mid-capture.
                    .allowsHitTesting(canProceed || qualityCheckFailed)
            }
            .padding(.horizontal, 20)
            .padding(.top, 12)
            .padding(.bottom, 8)
            .background(.ultraThinMaterial)
        }
        .animation(.aurionIOS, value: recorder.isRecording)
        .animation(.aurionIOS, value: canProceed)
        .animation(.aurionIOS, value: qualityCheckFailed)
        .animation(.aurionIOS, value: permissionDenied)
        .onAppear { Task { await ensurePermission() } }
        .onChange(of: scenePhase) { _, newPhase in
            // Returning from Settings (or any foregrounding) — re-read the
            // mic authorization so a permission granted out-of-app
            // immediately re-enables the record button instead of leaving
            // the clinician stuck on the denied state.
            if newPhase == .active { refreshPermissionStatus() }
        }
        .onChange(of: recorder.audioLevel) { _, newLevel in
            // Feed each meter tick into the per-sentence accumulator so
            // the quality gate has real data to evaluate when the
            // sentence window closes.
            guard recorder.isRecording,
                  sentenceIndex < sentences.count else { return }
            recorder.recordSampleForSentence(sentenceIndex, normalizedLevel: newLevel)
        }
        .onChange(of: recorder.duration) { _, newValue in
            let newIndex = min(Int(newValue / sentenceInterval), sentences.count)
            if newIndex > sentenceIndex {
                // Close the previous window — evaluate its quality.
                let closingIndex = sentenceIndex
                if closingIndex < sentences.count {
                    let pass = recorder.evaluateSentenceWindow(
                        index: closingIndex,
                        minimumDurationSec: perSentenceMinimumDurationSec,
                        meanDbFloor: perSentenceMeanDbFloor
                    )
                    sentenceQuality[closingIndex] = pass
                }
                withAnimation(.aurionIOS) { sentenceIndex = newIndex }
            }
            if sentenceIndex >= sentences.count && recorder.isRecording {
                stopRecording()
            }
        }
    }

    // MARK: - Sentence list (rows fade-confirm as they complete)

    private var sentenceList: some View {
        VStack(alignment: .leading, spacing: 12) {
            ForEach(Array(sentences.enumerated()), id: \.offset) { index, sentence in
                let quality = sentenceQuality[safe: index] ?? nil
                let active = index == sentenceIndex
                let pass = quality == true
                let fail = quality == false
                HStack(alignment: .top, spacing: 10) {
                    sentenceIcon(pass: pass, fail: fail, active: active)
                        .padding(.top, 2) // optical-align with first text line
                    VStack(alignment: .leading, spacing: 4) {
                        Text(sentence)
                            .aurionFont(16, weight: .regular, relativeTo: .body)
                            .foregroundColor(
                                active ? .aurionNavy :
                                (pass ? .aurionTextSecondary :
                                    (fail ? .aurionNavy : .secondary))
                            )
                            .opacity(pass ? 0.7 : 1)
                            .multilineTextAlignment(.leading)
                            // Bug B — without fixedSize, a Text inside an
                            // HStack inside a card padded by 16px on each
                            // side can hit greedy horizontal layout and
                            // ellipsis-clip on iPhone Mini (320pt content
                            // width). Pinning vertical sizing forces the
                            // row to grow to fit the full sentence.
                            .fixedSize(horizontal: false, vertical: true)
                            .frame(maxWidth: .infinity, alignment: .leading)
                        if fail {
                            Text(L("onboarding.voiceRec.notHeardRow"))
                                .aurionFont(12, weight: .medium, relativeTo: .caption)
                                .foregroundColor(.aurionGold)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }
                // The pass/fail/active state is conveyed only by icon
                // color+shape, which carries no VoiceOver label. Collapse
                // the row into one element and speak the state alongside
                // the sentence so the core feedback loop is audible.
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(rowAccessibilityLabel(sentence: sentence, pass: pass, fail: fail, active: active))
            }
        }
        .padding(16)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.aurionCardBackground)
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
    }

    /// Sentence-row leading icon. Three states:
    /// - pass: filled green checkmark.
    /// - fail: filled amber exclamation (matches the "we didn't hear
    ///   you" copy below).
    /// - active / pending: hollow circle.
    @ViewBuilder
    private func sentenceIcon(pass: Bool, fail: Bool, active: Bool) -> some View {
        if pass {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 16))
                .foregroundColor(.aurionGreen)
        } else if fail {
            Image(systemName: "exclamationmark.circle.fill")
                .font(.system(size: 16))
                .foregroundColor(.aurionGold)
        } else {
            Image(systemName: "circle")
                .font(.system(size: 16))
                .foregroundColor(active ? .aurionNavy.opacity(0.6) : .aurionNavy.opacity(0.3))
        }
    }

    /// VoiceOver label for a sentence row: the sentence text followed by
    /// its capture state. Mirrors the icon states in `sentenceIcon`.
    private func rowAccessibilityLabel(sentence: String, pass: Bool, fail: Bool, active: Bool) -> String {
        let state: String
        if pass {
            state = L("onboarding.voiceRec.a11yRowCaptured")
        } else if fail {
            state = L("onboarding.voiceRec.a11yRowNotHeard")
        } else if active {
            state = L("onboarding.voiceRec.a11yRowCurrent")
        } else {
            state = ""
        }
        return state.isEmpty ? sentence : "\(sentence) \(state)"
    }

    // MARK: - Record button (gold disc with breathing halo on press)

    private var recordButton: some View {
        // Halo + ring + disc. Single animation source (HaloRing) so we
        // never stack two infinite GPU-blurred animations on the same
        // node — that combo was causing a Core Animation crash.
        let coreColor = recorder.isRecording ? Color.aurionRed : Color.aurionGold
        return Button(action: toggleRecording) {
            ZStack {
                HaloRing(color: coreColor, animate: !recorder.isRecording)
                Circle()
                    .stroke(coreColor.opacity(0.18), lineWidth: 8)
                    .frame(width: 88, height: 88)
                Circle()
                    .fill(coreColor)
                    .frame(width: 80, height: 80)
                    .shadow(color: coreColor.opacity(0.36), radius: 16, x: 0, y: 12)
                if recorder.isRecording {
                    RoundedRectangle(cornerRadius: 6)
                        .fill(Color.white)
                        .frame(width: 28, height: 28)
                } else {
                    Circle()
                        .fill(Color.aurionNavy)
                        .frame(width: 28, height: 28)
                }
            }
            .frame(width: 140, height: 140)
        }
        .buttonStyle(.plain)
        .disabled(permissionDenied)
        .scaleEffect(permissionDenied ? 0.95 : 1)
        .opacity(permissionDenied ? 0.55 : 1)
        // VoiceOver: the disc is shape-only, so spell out what it does and
        // mirror the recording state in the label. `.startsMediaSession`
        // tells VoiceOver tapping begins capture (dropped while recording).
        .accessibilityLabel(recorder.isRecording
            ? L("onboarding.voiceRec.a11yStop")
            : L("onboarding.voiceRec.a11yStart"))
        .accessibilityHint(recorder.isRecording
            ? L("onboarding.voiceRec.a11yStopHint")
            : L("onboarding.voiceRec.a11yStartHint"))
        .accessibilityAddTraits(recorder.isRecording ? [] : .startsMediaSession)
    }

    private var statusText: String {
        if permissionDenied { return L("onboarding.voiceRec.micDenied") }
        if recorder.isRecording { return L("onboarding.voiceRec.tapStop") }
        if qualityCheckFailed { return L("onboarding.voiceRec.qualityCheckFailed") }
        if canProceed { return L("onboarding.voiceRec.captured") }
        return L("onboarding.voiceRec.tapStart")
    }

    /// Error/blocked status copy reads in amber to match the per-row
    /// `.aurionGold` signal it summarizes, so the headline explaining WHY
    /// Continue is disabled isn't visually weaker than the rows below it.
    /// Neutral hints stay low-emphasis secondary.
    private var statusColor: Color {
        if permissionDenied || qualityCheckFailed { return .aurionGold }
        return .secondary
    }

    // MARK: - Recording control

    private func ensurePermission() async {
        let granted = await AVCaptureDevice.requestAccess(for: .audio)
        permissionDenied = !granted
    }

    /// Re-read the current mic authorization without prompting again.
    /// Called on foreground so a permission granted in Settings flips the
    /// UI back to a usable record button. `.notDetermined` is left to the
    /// initial `ensurePermission()` prompt.
    private func refreshPermissionStatus() {
        switch AVCaptureDevice.authorizationStatus(for: .audio) {
        case .authorized:
            permissionDenied = false
        case .denied, .restricted:
            permissionDenied = true
        case .notDetermined:
            break
        @unknown default:
            break
        }
    }

    private func openSettings() {
        if let url = URL(string: UIApplication.openSettingsURLString) {
            UIApplication.shared.open(url)
        }
    }

    private func toggleRecording() {
        if recorder.isRecording { stopRecording() } else { startRecording() }
    }

    private func startRecording() {
        AurionHaptics.impact(.medium)
        sentenceIndex = 0
        canProceed = false
        qualityCheckFailed = false
        sentenceQuality = Array(repeating: nil, count: sentences.count)
        recorder.resetSentenceWindows(count: sentences.count)
        recorder.start()
    }

    private func stopRecording() {
        recorder.stop()
        // Close the in-flight window if the user stopped mid-sentence.
        if sentenceIndex < sentences.count,
           sentenceQuality[sentenceIndex] == nil {
            let pass = recorder.evaluateSentenceWindow(
                index: sentenceIndex,
                minimumDurationSec: perSentenceMinimumDurationSec,
                meanDbFloor: perSentenceMeanDbFloor
            )
            sentenceQuality[sentenceIndex] = pass
        }

        // Quality gate: every required-sentence row must have passed
        // AND total duration must clear the 15s minimum the embedding
        // pipeline needs. Anything else surfaces the amber banner.
        let allEvaluatedRows = sentenceQuality.compactMap { $0 }
        let anyFailures = allEvaluatedRows.contains(false)
        let coveredAllRows = allEvaluatedRows.count == sentences.count
        let durationOK = recorder.duration >= minimumDuration

        if anyFailures || !coveredAllRows || !durationOK {
            withAnimation(.aurionIOS) { qualityCheckFailed = true }
            canProceed = false

            // Audit each rejected window so post-pilot we can tune the
            // thresholds. No PHI — the only payload is the gate's
            // numeric configuration + observed values.
            for (idx, pass) in sentenceQuality.enumerated() where pass == false {
                let observed = recorder.observedStatsForSentence(idx)
                AuditLogger.logRaw(
                    eventType: "voice_enrollment_sentence_rejected_low_quality",
                    extra: [
                        "sentence_index": "\(idx)",
                        "duration_floor_sec": String(format: "%.1f", perSentenceMinimumDurationSec),
                        "mean_db_floor": String(format: "%.1f", perSentenceMeanDbFloor),
                        "observed_duration_sec": String(format: "%.2f", observed.durationSec),
                        "observed_mean_db": String(format: "%.1f", observed.meanDb),
                        "observed_sample_count": "\(observed.sampleCount)",
                    ]
                )
            }
            return
        }

        withAnimation(.aurionIOS) { canProceed = true }
    }

    private func resetRecording() {
        canProceed = false
        qualityCheckFailed = false
        sentenceIndex = 0
        sentenceQuality = Array(repeating: nil, count: sentences.count)
        recorder.resetSentenceWindows(count: sentences.count)
        recorder.discardLast()
    }
}

// MARK: - Safe subscript

private extension Array {
    /// `nil`-returning indexed access. Avoids out-of-range crashes when
    /// SwiftUI re-renders mid-state-mutation with a stale index.
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}

// MARK: - Voice Recorder

@MainActor
final class VoiceRecorder: ObservableObject {
    @Published private(set) var lastRecordingURL: URL?

    private let recorder = AurionAudioFileRecorder()
    private var cancellables = Set<AnyCancellable>()

    /// Per-sentence sample accumulators. Each entry holds the meter
    /// samples that landed during that sentence's 8-second window
    /// (normalized 0…1) plus the corresponding dBFS we reconstruct from
    /// the inverse of `AurionAudioFileRecorder`'s clamp. We compute
    /// pass/fail in `evaluateSentenceWindow` to keep the per-tick path
    /// allocation-free.
    private struct SentenceAccumulator {
        var sampleCount: Int = 0
        var summedDb: Float = 0
        /// First and last sample timestamps (recorder.currentTime) so
        /// we can compute the actual covered duration. Otherwise an
        /// 8-second nominal window with one sample at t=0 and another
        /// at t=7.95s would look like an 8-second window of "speech."
        var firstSampleAt: TimeInterval?
        var lastSampleAt: TimeInterval?
    }
    private var sentenceAccumulators: [SentenceAccumulator] = []

    var isRecording: Bool { recorder.isRecording }
    var duration: TimeInterval { recorder.duration }
    var audioLevel: Float { recorder.audioLevel }

    init() {
        // Hop to main before forwarding objectWillChange. AurionAudioFileRecorder
        // is @MainActor today, but a Combine pipeline can still deliver on the
        // upstream's queue — being explicit here removes a whole class of
        // "publishing changes from background thread" runtime traps.
        recorder.objectWillChange
            .receive(on: DispatchQueue.main)
            .sink { [weak self] in self?.objectWillChange.send() }
            .store(in: &cancellables)
    }

    func start() {
        do {
            try recorder.start(filenamePrefix: "voice-enrollment", fileExtension: "caf",
                               sessionOptions: .voiceEnrollment)
        } catch {
            // Voice enrollment is best-effort; the user can re-record on failure.
        }
    }

    func stop() {
        if let url = recorder.stop() {
            lastRecordingURL = url
        }
    }

    func discardLast() {
        if let url = lastRecordingURL {
            try? FileManager.default.removeItem(at: url)
        }
        lastRecordingURL = nil
    }

    // MARK: - Sentence-window quality gate (Marie bug-bash Bug C)

    /// Clear the per-sentence accumulators so a fresh recording starts
    /// with no carryover. Called from `VoiceRecordingView.startRecording`
    /// and `resetRecording`.
    func resetSentenceWindows(count: Int) {
        sentenceAccumulators = Array(repeating: SentenceAccumulator(), count: count)
    }

    /// Append one meter tick to the running window for `index`. The
    /// input is the normalized `audioLevel` (0…1) from
    /// `AurionAudioFileRecorder`; we invert its `(dB + 60) / 60` clamp
    /// to recover an approximate dBFS value for the threshold check.
    /// Approximation, not byte-perfect — the inversion loses sub-dB
    /// fidelity below -60 dBFS, but our floor is -45 so we're safe.
    func recordSampleForSentence(_ index: Int, normalizedLevel: Float) {
        guard index < sentenceAccumulators.count else { return }
        let clamped = max(0, min(1, normalizedLevel))
        // Inverse of AurionAudioFileRecorder's `(avgPower + 60) / 60`
        // clamp. avgPower = clamped * 60 - 60.
        let db = clamped * 60.0 - 60.0
        var acc = sentenceAccumulators[index]
        acc.sampleCount += 1
        acc.summedDb += db
        if acc.firstSampleAt == nil { acc.firstSampleAt = duration }
        acc.lastSampleAt = duration
        sentenceAccumulators[index] = acc
    }

    /// Compute pass/fail for a closed sentence window.
    ///
    /// Pass requires BOTH:
    ///   * Covered duration (last sample - first sample) ≥
    ///     `minimumDurationSec`. Without this, a 0.2s burst of throat-
    ///     clearing followed by silence would look like a "loud" window
    ///     by mean-dB alone.
    ///   * Mean dBFS over the accumulated samples > `meanDbFloor`. Mean
    ///     not peak — a single loud cough can clear a peak threshold
    ///     trivially.
    func evaluateSentenceWindow(
        index: Int,
        minimumDurationSec: TimeInterval,
        meanDbFloor: Float
    ) -> Bool {
        guard index < sentenceAccumulators.count else { return false }
        let acc = sentenceAccumulators[index]
        guard acc.sampleCount > 0,
              let first = acc.firstSampleAt,
              let last = acc.lastSampleAt else {
            return false
        }
        let coveredDuration = last - first
        let meanDb = acc.summedDb / Float(acc.sampleCount)
        return coveredDuration >= minimumDurationSec && meanDb > meanDbFloor
    }

    /// Read-only accessor for the audit-log payload after a rejection.
    /// No PHI — just numeric meter stats.
    func observedStatsForSentence(_ index: Int) -> (durationSec: Double, meanDb: Float, sampleCount: Int) {
        guard index < sentenceAccumulators.count else { return (0, 0, 0) }
        let acc = sentenceAccumulators[index]
        let coveredDuration: Double = {
            guard let first = acc.firstSampleAt, let last = acc.lastSampleAt else { return 0 }
            return last - first
        }()
        let meanDb = acc.sampleCount > 0 ? acc.summedDb / Float(acc.sampleCount) : 0
        return (coveredDuration, meanDb, acc.sampleCount)
    }
}

// MARK: - Halo Ring
//
// Single-source breathing halo behind the record button. Replaces the
// earlier stack of nested blurred + breathing-modifier circles that was
// triggering an off-main `EXC_BAD_ACCESS` on Thread 9 in the simulator.

private struct HaloRing: View {
    let color: Color
    let animate: Bool
    @State private var pulse = false

    var body: some View {
        Circle()
            .fill(color.opacity(0.22))
            .frame(width: 120, height: 120)
            .blur(radius: 14)
            .scaleEffect(pulse ? 1.15 : 0.95)
            .opacity(animate ? (pulse ? 0.85 : 0.45) : 0)
            .onAppear {
                guard animate else { return }
                withAnimation(.easeInOut(duration: 2.4).repeatForever(autoreverses: true)) {
                    pulse = true
                }
            }
            .animation(.aurionIOS, value: animate)
    }
}
