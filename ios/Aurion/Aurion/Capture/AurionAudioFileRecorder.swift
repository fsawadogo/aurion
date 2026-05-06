import Foundation
import AVFoundation
import Combine

/// Shared AVAudioRecorder wrapper used by every audio-only recording path
/// (voice enrollment, BluetoothAudioSource). Owns the AVAudioSession lifecycle,
/// the temp-file URL, the level-meter timer, and the dB→amplitude conversion.
///
/// Callers wrap this and add their own state (status pills, recordedData, etc.)
/// — keeps the AVFoundation plumbing in one place.
@MainActor
final class AurionAudioFileRecorder: ObservableObject {
    @Published private(set) var audioLevel: Float = 0
    @Published private(set) var duration: TimeInterval = 0
    @Published private(set) var isRecording = false

    /// AVAudioSession setup parameters. The voice-enrollment flow defaults
    /// to the device speaker; the BT-input source allows A2DP routing so a
    /// connected Bluetooth mic can be used.
    struct SessionOptions {
        let category: AVAudioSession.Category
        let mode: AVAudioSession.Mode
        let options: AVAudioSession.CategoryOptions

        static let voiceEnrollment = SessionOptions(
            category: .playAndRecord,
            mode: .measurement,
            options: [.defaultToSpeaker, .allowBluetoothHFP]
        )
        static let bluetoothInput = SessionOptions(
            category: .playAndRecord,
            mode: .measurement,
            options: [.allowBluetoothHFP, .allowBluetoothA2DP]
        )
    }

    private var recorder: AVAudioRecorder?
    private var levelTimer: Timer?
    private var currentURL: URL?

    /// Begin recording to a fresh temp file. Returns the file URL.
    @discardableResult
    func start(
        filenamePrefix: String,
        fileExtension: String = "wav",
        sessionOptions: SessionOptions
    ) throws -> URL {
        let session = AVAudioSession.sharedInstance()
        try session.setCategory(sessionOptions.category, mode: sessionOptions.mode, options: sessionOptions.options)
        try session.setActive(true)

        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("\(filenamePrefix)-\(UUID().uuidString).\(fileExtension)")

        let r = try AVAudioRecorder(url: url, settings: AurionAudioFormat.recorderSettings)
        r.isMeteringEnabled = true
        guard r.record() else {
            throw AurionAudioFileRecorderError.failedToStart
        }
        recorder = r
        currentURL = url
        isRecording = true
        duration = 0
        audioLevel = 0
        startLevelTimer()
        return url
    }

    func pause() {
        recorder?.pause()
        levelTimer?.invalidate()
        levelTimer = nil
        isRecording = false
    }

    func resume() {
        guard recorder?.record() == true else { return }
        startLevelTimer()
        isRecording = true
    }

    /// Stops recording and returns the file URL (caller owns deletion).
    @discardableResult
    func stop() -> URL? {
        recorder?.stop()
        levelTimer?.invalidate()
        levelTimer = nil
        let url = currentURL
        recorder = nil
        currentURL = nil
        isRecording = false
        try? AVAudioSession.sharedInstance().setActive(false, options: .notifyOthersOnDeactivation)
        return url
    }

    private func startLevelTimer() {
        levelTimer = Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { [weak self] _ in
            Task { @MainActor [weak self] in
                guard let self, let recorder = self.recorder else { return }
                recorder.updateMeters()
                let avgPower = recorder.averagePower(forChannel: 0)
                // dB (typically -60..0) → 0..1 amplitude
                self.audioLevel = max(0, min(1, (avgPower + 60) / 60))
                self.duration = recorder.currentTime
            }
        }
    }
}

enum AurionAudioFileRecorderError: LocalizedError {
    case failedToStart

    var errorDescription: String? {
        switch self {
        case .failedToStart: return "Could not start the audio recorder."
        }
    }
}
