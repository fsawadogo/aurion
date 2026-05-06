import SwiftUI
import AVFoundation
import Combine

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
struct VoiceRecordingView: View {
    let onComplete: (URL) -> Void

    @StateObject private var recorder = VoiceRecorder()
    @State private var sentenceIndex = 0
    @State private var canProceed = false
    @State private var permissionDenied = false

    private let minimumDuration: TimeInterval = 15
    private let sentences = [
        "Range of motion is restricted to approximately 90 degrees of flexion.",
        "There is tenderness on palpation at the medial joint line.",
        "The wound edges appear well approximated with no signs of infection.",
        "I am reviewing the imaging now — there is no visible fracture displacement.",
    ]

    var body: some View {
        VStack(spacing: 24) {
            Text("Read aloud in your normal clinical voice")
                .font(.title3)
                .fontWeight(.semibold)
                .foregroundColor(.aurionNavy)
                .aurionStagger(order: 0, baseDelay: 0.05)

            sentenceList
                .aurionStagger(order: 1)

            Spacer()

            if recorder.isRecording {
                VStack(spacing: 14) {
                    AurionAudioBars(level: recorder.audioLevel)
                        .padding(.horizontal, 40)
                    Text(String(format: "%.0fs", recorder.duration))
                        .font(.title2)
                        .monospacedDigit()
                        .foregroundColor(.aurionNavy)
                }
                .transition(.opacity)
            }

            recordButton
                .padding(.top, 8)

            Text(statusText)
                .font(.caption)
                .foregroundColor(.secondary)
                .transition(.opacity)
                .id(statusText)
                .animation(.aurionIOS, value: statusText)

            if canProceed, let url = recorder.lastRecordingURL {
                AurionGoldButton(label: "Continue", full: true) { onComplete(url) }
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }

            Button("Re-record") { resetRecording() }
                .font(.caption)
                .foregroundColor(.aurionNavy)
                .opacity(canProceed ? 1 : 0)

            Spacer().frame(height: 20)
        }
        .padding(.horizontal, 20)
        .animation(.aurionIOS, value: recorder.isRecording)
        .animation(.aurionIOS, value: canProceed)
        .onAppear { Task { await ensurePermission() } }
        .onChange(of: recorder.duration) { _, newValue in
            let sentenceInterval = 8.0
            let newIndex = min(Int(newValue / sentenceInterval), sentences.count)
            if newIndex > sentenceIndex {
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
                let done = index < sentenceIndex
                let active = index == sentenceIndex
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: done ? "checkmark.circle.fill" : "circle")
                        .font(.system(size: 16))
                        .foregroundColor(done ? .aurionGreen : .aurionNavy.opacity(0.3))
                        .scaleEffect(done ? 1.0 : 0.95)
                        .animation(.aurionIOS, value: done)
                    Text(sentence)
                        .font(.body)
                        .foregroundColor(active ? .aurionNavy : (done ? .aurionTextSecondary : .secondary))
                        .opacity(done ? 0.6 : 1)
                }
            }
        }
        .padding(16)
        .background(Color.aurionCardBackground)
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
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
    }

    private var statusText: String {
        if permissionDenied { return "Microphone permission required" }
        if recorder.isRecording { return "Tap to stop" }
        if canProceed { return "Recording captured — tap Continue" }
        return "Tap to start recording"
    }

    // MARK: - Recording control

    private func ensurePermission() async {
        let granted = await AVCaptureDevice.requestAccess(for: .audio)
        permissionDenied = !granted
    }

    private func toggleRecording() {
        if recorder.isRecording { stopRecording() } else { startRecording() }
    }

    private func startRecording() {
        AurionHaptics.impact(.medium)
        sentenceIndex = 0
        canProceed = false
        recorder.start()
    }

    private func stopRecording() {
        recorder.stop()
        if recorder.duration >= minimumDuration {
            withAnimation(.aurionIOS) { canProceed = true }
        }
    }

    private func resetRecording() {
        canProceed = false
        sentenceIndex = 0
        recorder.discardLast()
    }
}

// MARK: - Voice Recorder

@MainActor
final class VoiceRecorder: ObservableObject {
    @Published private(set) var lastRecordingURL: URL?

    private let recorder = AurionAudioFileRecorder()
    private var cancellables = Set<AnyCancellable>()

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
