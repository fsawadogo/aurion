import AVFoundation
import Combine
import CoreMedia
@preconcurrency import Speech

/// `CMSampleBuffer` is documented thread-safe by Apple but isn't `Sendable`
/// in Swift 6 strict concurrency. This shim lets us hand a buffer across
/// the audio-delegate-queue → MainActor boundary without each call site
/// having to declare `@unchecked Sendable` itself.
private struct SampleBufferEnvelope: @unchecked Sendable {
    let buffer: CMSampleBuffer
}

/// On-device live captioning during a recording session.
///
/// Fed by a parallel tap on `CaptureManager`'s audio delegate, this passes
/// every `CMSampleBuffer` to `SFSpeechRecognizer` configured with
/// `requiresOnDeviceRecognition = true`. The result is a `@Published`
/// `transcript` string the capture screen displays as live captions —
/// physician sees roughly what the system is hearing while still recording.
///
/// **This is UX sugar, not the canonical transcript.** When `Stop` is hit
/// the WAV is uploaded to Whisper as before, and the resulting batch
/// transcript is what enters Stage 1 note generation. Live caption text is
/// discarded on stop.
///
/// **Privacy:** `requiresOnDeviceRecognition = true` means audio bytes never
/// leave the device for the live path. If the user's locale lacks an
/// on-device model, `isAvailable` flips to false and the capture screen
/// hides the caption strip — we never fall back to Apple's cloud, which
/// would conflict with CLAUDE.md's audio-locality guarantees. No additional
/// audit event is needed: live captioning is a derivative of the same audio
/// stream covered by `recording_started`.
///
/// **Continuous capture:** an `SFSpeechAudioBufferRecognitionRequest` is
/// capped at ~1 minute by Apple. When the task delegate reports `isFinal`
/// mid-recording we automatically open a new request so captions never
/// freeze. Pause/resume halts and restarts cleanly.
@MainActor
final class LiveTranscriber: ObservableObject {

    // MARK: - Published

    /// Best-guess running transcript of the current encounter.
    /// Reset to "" on each `start()` and on `stop()`.
    @Published private(set) var transcript: String = ""

    /// Whether the live caption strip should be shown. False when:
    /// authorization denied, the device/locale lacks on-device speech, or
    /// the recognizer is unavailable for any other reason. The capture
    /// screen reads this to decide whether to render the strip — recording
    /// continues regardless.
    @Published private(set) var isAvailable: Bool = false

    /// Last user-facing error, if any. Surfaced for debug logging only — the
    /// capture screen does not currently show it (failures are silent so
    /// recording is never interrupted).
    @Published private(set) var error: String?

    // MARK: - Internals

    private var recognizer: SFSpeechRecognizer?
    private var request: SFSpeechAudioBufferRecognitionRequest?
    private var task: SFSpeechRecognitionTask?

    /// Set when `prepare(language:)` succeeds; used as the request's
    /// expected input format when wrapping incoming `CMSampleBuffer`s.
    /// `SFSpeechAudioBufferRecognitionRequest` accepts any common PCM
    /// format and resamples internally.
    private var inputFormat: AVAudioFormat?

    /// Tracks whether we're inside an active recognition session (between
    /// `start()` and `stop()`). Used to decide whether to auto-restart the
    /// request when SFSpeechRecognizer hits its 1-minute cap mid-recording.
    private var isRunning = false

    // MARK: - Lifecycle

    /// Prepare the recognizer for the given language code (e.g. "en", "fr").
    /// Idempotent — re-prepares if the language changed or the recognizer
    /// became unavailable. Triggers the iOS Speech permission prompt on
    /// first call. After this returns, check `isAvailable` to decide
    /// whether to call `start()`.
    func prepare(language: String) async {
        let locale = Self.locale(for: language)
        let r = SFSpeechRecognizer(locale: locale)
        recognizer = r

        // SFSpeechRecognizer is nil if the locale is entirely unsupported.
        guard let r else {
            isAvailable = false
            error = "Live captions not available for \(locale.identifier)."
            return
        }

        // We require on-device recognition for the privacy guarantee — if
        // the device/locale lacks a downloaded on-device model we surface
        // unavailable rather than fall back to Apple's cloud.
        guard r.supportsOnDeviceRecognition else {
            isAvailable = false
            error = "On-device speech model unavailable for \(locale.identifier)."
            return
        }

        let auth = await Self.requestAuthorization()
        guard auth == .authorized else {
            isAvailable = false
            error = "Speech recognition permission \(auth)."
            return
        }

        guard r.isAvailable else {
            isAvailable = false
            error = "Speech recognizer not available right now."
            return
        }

        isAvailable = true
        error = nil
    }

    /// Begin a live recognition request. Safe to call repeatedly — if
    /// already running it tears down the previous task before starting a
    /// new one. No-op when `isAvailable == false`.
    func start() {
        guard isAvailable, let recognizer else { return }
        cancelCurrentTask()

        let req = SFSpeechAudioBufferRecognitionRequest()
        req.requiresOnDeviceRecognition = true
        req.shouldReportPartialResults = true
        // Hint the recognizer to bias toward dictation (longer free-form
        // speech) rather than search queries. Improves clinical phrasing.
        req.taskHint = .dictation

        request = req
        isRunning = true

        task = recognizer.recognitionTask(with: req) { [weak self] result, taskError in
            guard let self else { return }
            Task { @MainActor [weak self] in
                guard let self else { return }
                if let result {
                    self.transcript = result.bestTranscription.formattedString
                    if result.isFinal {
                        // Apple finalized this segment — either silence
                        // detected or the ~1-minute cap hit. Restart so
                        // captions continue without a frozen line.
                        self.handleFinalSegment()
                    }
                } else if taskError != nil {
                    // Most "errors" here are benign — task cancelled, audio
                    // ended cleanly. We swallow them and let `stop()` /
                    // `start()` drive lifecycle deterministically.
                    self.handleFinalSegment()
                }
            }
        }
    }

    /// Feed a sample buffer from the audio capture path. Called from the
    /// audio delegate queue (nonisolated) — we hop to the main actor for
    /// the published-state writes inside the recognition callback above,
    /// but the buffer append itself is thread-safe per Apple's Speech docs.
    ///
    /// `CMSampleBuffer` is documented thread-safe by Apple but isn't
    /// formally `Sendable`. We wrap it in a small unchecked-Sendable shim
    /// so Swift 6 strict concurrency lets us hand it across the actor hop.
    nonisolated func feed(sampleBuffer: CMSampleBuffer) {
        let envelope = SampleBufferEnvelope(buffer: sampleBuffer)
        Task { @MainActor [weak self] in
            self?.feedOnMain(envelope.buffer)
        }
    }

    private func feedOnMain(_ sampleBuffer: CMSampleBuffer) {
        guard isRunning, let request else { return }

        // Establish the input format from the first buffer we see and stash
        // it for subsequent calls. Capture format is stable for the life of
        // a session so this is a one-time cost.
        if inputFormat == nil {
            guard let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
                  let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc) else {
                return
            }
            var asbd = asbdPtr.pointee
            inputFormat = AVAudioFormat(streamDescription: &asbd)
        }
        guard let inputFormat,
              let pcmBuffer = AudioBufferConverter.pcmBuffer(
                from: sampleBuffer,
                format: inputFormat
              ) else { return }

        request.append(pcmBuffer)
    }

    /// Stop the current recognition task and discard interim text. Called
    /// on session pause and on session stop. Resets `transcript` so the
    /// caption strip clears between sessions.
    func stop() {
        isRunning = false
        request?.endAudio()
        cancelCurrentTask()
        transcript = ""
        inputFormat = nil
    }

    // MARK: - Internals

    private func cancelCurrentTask() {
        task?.cancel()
        task = nil
        request = nil
    }

    /// Apple finalized the current segment. If we're still in an active
    /// recording (i.e. caller hasn't called stop()) we open a new request
    /// to keep captions continuous past the ~1-minute cap.
    private func handleFinalSegment() {
        guard isRunning else { return }
        cancelCurrentTask()
        // Tear down + restart in the same tick. transcript is left in place
        // so the user sees the last finalized text continue accumulating
        // when the next request fires.
        start()
    }

    // MARK: - Static helpers

    /// Map our 2-letter language codes to Apple-locale identifiers.
    /// Falls back to en_US for anything we don't recognize.
    private static func locale(for language: String) -> Locale {
        switch language.lowercased() {
        case "fr", "fr-fr", "fr_fr": return Locale(identifier: "fr_FR")
        case "fr-ca", "fr_ca": return Locale(identifier: "fr_CA")
        case "en", "en-us", "en_us": return Locale(identifier: "en_US")
        default: return Locale(identifier: "en_US")
        }
    }

    private static func requestAuthorization() async -> SFSpeechRecognizerAuthorizationStatus {
        await withCheckedContinuation { continuation in
            SFSpeechRecognizer.requestAuthorization { status in
                continuation.resume(returning: status)
            }
        }
    }
}
