import AVFoundation
import Combine
import SwiftUI

// MARK: - Resume recording (note-options phase 4)
//
// Records a SHORT follow-up audio clip into an already-generated encounter and
// uploads it to POST /transcription/{id}/append, which merges the transcript
// and regenerates the note covering both clips. Deliberately a self-contained
// AVAudioRecorder (WAV) rather than the full CaptureManager/SessionManager
// arc — the encounter is already past the RECORDING state machine, and this
// only needs audio to merge into the transcript.

/// Standalone WAV recorder for the append flow. Writes 16 kHz mono PCM — the
/// same shape the transcription pipeline expects.
final class AudioAppendRecorder: NSObject, ObservableObject {
    @Published var isRecording = false
    @Published var elapsed: TimeInterval = 0

    private var recorder: AVAudioRecorder?
    private var timer: Timer?
    private var fileURL: URL?

    func requestPermission() async -> Bool {
        await withCheckedContinuation { cont in
            AVAudioSession.sharedInstance().requestRecordPermission { granted in
                cont.resume(returning: granted)
            }
        }
    }

    func start() -> Bool {
        let session = AVAudioSession.sharedInstance()
        do {
            try session.setCategory(.record, mode: .default)
            try session.setActive(true)
            let url = FileManager.default.temporaryDirectory
                .appendingPathComponent("resume_\(UUID().uuidString).wav")
            let settings: [String: Any] = [
                AVFormatIDKey: Int(kAudioFormatLinearPCM),
                AVSampleRateKey: 16000.0,
                AVNumberOfChannelsKey: 1,
                AVLinearPCMBitDepthKey: 16,
                AVLinearPCMIsFloatKey: false,
                AVLinearPCMIsBigEndianKey: false,
            ]
            let rec = try AVAudioRecorder(url: url, settings: settings)
            guard rec.record() else { return false }
            recorder = rec
            fileURL = url
            isRecording = true
            elapsed = 0
            timer = Timer.scheduledTimer(withTimeInterval: 0.2, repeats: true) { [weak self] _ in
                guard let self, let rec = self.recorder else { return }
                self.elapsed = rec.currentTime
            }
            return true
        } catch {
            return false
        }
    }

    /// Stop and return the recorded WAV bytes (nil if nothing was captured).
    func stop() -> Data? {
        recorder?.stop()
        timer?.invalidate()
        timer = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false)
        guard let url = fileURL else { return nil }
        return try? Data(contentsOf: url)
    }

    /// Abandon the recording and delete the temp file.
    func cancel() {
        recorder?.stop()
        timer?.invalidate()
        timer = nil
        isRecording = false
        if let url = fileURL { try? FileManager.default.removeItem(at: url) }
        try? AVAudioSession.sharedInstance().setActive(false)
    }

    func cleanupFile() {
        if let url = fileURL { try? FileManager.default.removeItem(at: url) }
    }
}

struct ResumeRecordingSheet: View {
    let sessionId: String
    /// Called after a successful merge+regenerate so the note screen reloads.
    let onFinished: () -> Void
    let onClose: () -> Void

    @StateObject private var recorder = AudioAppendRecorder()
    @State private var phase: Phase = .idle
    @State private var error: String?
    @State private var permissionDenied = false

    private enum Phase { case idle, recording, uploading }

    var body: some View {
        NavigationStack {
            VStack(spacing: AurionSpacing.xxl) {
                Spacer()

                ZStack {
                    Circle()
                        .fill(phase == .recording ? Color.clinicalAlert.opacity(0.12) : Color.aurionSurfaceAlt)
                        .frame(width: 120, height: 120)
                    Image(systemName: phase == .recording ? "waveform" : "mic.fill")
                        .font(.system(size: 44, weight: .light))
                        .foregroundColor(phase == .recording ? .clinicalAlert : .aurionGold)
                }

                VStack(spacing: AurionSpacing.sm) {
                    if phase == .uploading {
                        Text(L("resume.merging")).aurionTitle()
                        Text(L("resume.mergingSub"))
                            .aurionFont(15, relativeTo: .subheadline)
                            .foregroundColor(.aurionTextSecondary)
                            .multilineTextAlignment(.center)
                    } else if phase == .recording {
                        Text(timeString(recorder.elapsed))
                            .font(.system(size: 40, weight: .semibold, design: .rounded).monospacedDigit())
                            .foregroundColor(.aurionTextPrimary)
                        Text(L("resume.recordingSub"))
                            .aurionFont(14, relativeTo: .subheadline)
                            .foregroundColor(.aurionTextSecondary)
                    } else {
                        Text(L("resume.title")).aurionTitle()
                        Text(permissionDenied ? L("resume.permissionDenied") : L("resume.hint"))
                            .aurionFont(15, relativeTo: .subheadline)
                            .foregroundColor(.aurionTextSecondary)
                            .multilineTextAlignment(.center)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, AurionSpacing.xl)
                    }
                }

                if phase == .uploading {
                    ProgressView()
                } else if phase == .recording {
                    Button(L("resume.stop")) { Task { await stopAndUpload() } }
                        .buttonStyle(AurionPrimaryButtonStyle())
                        .padding(.horizontal, AurionSpacing.xl)
                } else {
                    Button(L("resume.start")) { Task { await beginRecording() } }
                        .buttonStyle(AurionPrimaryButtonStyle())
                        .padding(.horizontal, AurionSpacing.xl)
                        .disabled(permissionDenied)
                }

                Spacer()
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(Color.aurionBackground.ignoresSafeArea())
            .navigationTitle(L("resume.navTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("common.cancel")) {
                        recorder.cancel()
                        onClose()
                    }
                    .disabled(phase == .uploading)
                }
            }
            .interactiveDismissDisabled(phase != .idle)
            .alert(
                L("resume.failedShort"),
                isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }),
                presenting: error
            ) { _ in
                Button(L("common.ok"), role: .cancel) { error = nil }
            } message: { Text($0) }
        }
    }

    private func beginRecording() async {
        let granted = await recorder.requestPermission()
        guard granted else { permissionDenied = true; return }
        if recorder.start() {
            phase = .recording
            AurionHaptics.impact(.medium)
        } else {
            error = L("resume.startFailed")
        }
    }

    private func stopAndUpload() async {
        guard let audio = recorder.stop() else {
            error = L("resume.startFailed")
            phase = .idle
            return
        }
        phase = .uploading
        do {
            _ = try await APIClient.shared.appendRecording(sessionId: sessionId, audio: audio)
            recorder.cleanupFile()
            AurionHaptics.notification(.success)
            onFinished()
        } catch {
            recorder.cleanupFile()
            self.error = (error as? APIError)?.errorDescription ?? error.localizedDescription
            phase = .idle
        }
    }

    private func timeString(_ t: TimeInterval) -> String {
        let s = Int(t)
        return String(format: "%02d:%02d", s / 60, s % 60)
    }
}
