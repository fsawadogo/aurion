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

/// Why live captions aren't running, when they aren't. The capture screen
/// maps each case to a localized one-liner so the physician sees a concrete
/// reason ("permission needed", "model not downloaded for fr_FR") instead of
/// the strip just silently failing to appear.
enum UnavailableReason: Equatable {
    /// `SFSpeechRecognizer.requestAuthorization` returned anything other
    /// than `.authorized` (denied, restricted, notDetermined).
    case notAuthorized(SFSpeechRecognizerAuthorizationStatus)
    /// Recognizer exists but `supportsOnDeviceRecognition` is false. Apple's
    /// on-device model for this locale isn't downloaded / isn't supported.
    case noOnDeviceModel
    /// Recognizer + on-device model exist but `recognizer.isAvailable` is
    /// false right now (often a transient network or system-load condition).
    case recognizerOffline
    /// `SFSpeechRecognizer(locale:)` returned nil — locale is entirely
    /// unsupported by Apple's Speech framework.
    case localeUnsupported
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

    /// Best-guess running transcript of the current encounter, accumulated
    /// across however many `SFSpeechAudioBufferRecognitionRequest`s the
    /// session needed. Reset to "" on `stop()` only — `start()` preserves
    /// prior text so the ~1-minute auto-restart at `isFinal` doesn't blank
    /// the caption strip mid-encounter.
    @Published private(set) var transcript: String = ""

    /// Whether the live caption strip should be shown. False when:
    /// authorization denied, the device/locale lacks on-device speech, or
    /// the recognizer is unavailable for any other reason. The capture
    /// screen reads this to decide whether to render the strip — recording
    /// continues regardless.
    @Published private(set) var isAvailable: Bool = false

    /// Structured reason captions aren't available. `nil` when isAvailable
    /// is true or when prepare() hasn't run yet. The capture screen uses
    /// this to show a small one-line hint ("Captions need Speech permission",
    /// etc.) instead of silently rendering nothing — silence makes the
    /// feature feel broken when it's just gated on a system toggle.
    @Published private(set) var unavailableReason: UnavailableReason?

    /// Last user-facing error, if any. Kept around for debug logging; the
    /// capture screen reads `unavailableReason` (above) rather than this raw
    /// string so it can localize.
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

    /// Text from previously-finalized recognition requests. When the recognizer
    /// hits its ~1-minute cap and reports `isFinal`, we move the current
    /// request's text into this prefix and start a fresh request. The displayed
    /// `transcript` is rendered as `finalizedPrefix` + currentRequestText so
    /// the caption strip continues unbroken across the seam. Reset on stop().
    private var finalizedPrefix: String = ""

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
            markUnavailable(.localeUnsupported, "Live captions not available for \(locale.identifier).")
            return
        }

        // We require on-device recognition for the privacy guarantee — if
        // the device/locale lacks a downloaded on-device model we surface
        // unavailable rather than fall back to Apple's cloud.
        guard r.supportsOnDeviceRecognition else {
            markUnavailable(.noOnDeviceModel, "On-device speech model unavailable for \(locale.identifier).")
            return
        }

        let auth = await Self.requestAuthorization()
        guard auth == .authorized else {
            markUnavailable(.notAuthorized(auth), "Speech recognition permission \(auth).")
            return
        }

        guard r.isAvailable else {
            markUnavailable(.recognizerOffline, "Speech recognizer not available right now.")
            return
        }

        isAvailable = true
        unavailableReason = nil
        error = nil
    }

    private func markUnavailable(_ reason: UnavailableReason, _ message: String) {
        isAvailable = false
        unavailableReason = reason
        error = message
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
                // Late callbacks after pause() / stop() must not mutate state —
                // both lifecycle calls clear isRunning before tearing down,
                // and pause() seals `finalizedPrefix = transcript`; a late
                // callback here would otherwise re-compose against the freshly
                // sealed prefix and double-paste the in-flight text.
                guard self.isRunning else { return }
                if let result {
                    // bestTranscription.formattedString is the cumulative text
                    // for THIS request only — not the whole encounter. The
                    // displayed transcript is finalizedPrefix (sealed text from
                    // earlier requests) + the current request's running text.
                    let current = result.bestTranscription.formattedString
                    self.transcript = Self.compose(prefix: self.finalizedPrefix, current: current)
                    if result.isFinal {
                        // Apple finalized this segment — either silence
                        // detected or the ~1-minute cap hit. Bake this
                        // request's text into the prefix BEFORE restarting,
                        // so the next request's first partial result doesn't
                        // overwrite the accumulated history with just its
                        // first few words.
                        self.finalizedPrefix = self.transcript
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

    /// Stop the current recognition task and clear all accumulated text.
    /// Called when the session ends — between sessions the caption strip
    /// must start blank. For mid-session pause use `pause()` instead.
    func stop() {
        isRunning = false
        request?.endAudio()
        cancelCurrentTask()
        transcript = ""
        finalizedPrefix = ""
        inputFormat = nil
    }

    /// Pause caption capture *without* clearing the accumulated transcript.
    /// The current request is closed and any in-flight text is baked into
    /// the prefix, so a later `start()` continues from where we left off
    /// rather than blanking the strip. This matches the plan's "old text
    /// remains visible (frozen) during pause" behavior.
    func pause() {
        guard isRunning else { return }
        isRunning = false
        // Seal anything the current request has produced so far into the
        // prefix — the in-flight `result.bestTranscription.formattedString`
        // would otherwise be lost when we cancel the task. `transcript`
        // already reads as `finalizedPrefix + currentRequestText` so a
        // single assignment captures the full visible history.
        finalizedPrefix = transcript
        request?.endAudio()
        cancelCurrentTask()
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

    /// Join two transcript fragments with a single space, skipping the join
    /// when either side is empty. Avoids double-spaces / leading-space artifacts
    /// when stitching successive recognition requests together.
    private static func compose(prefix: String, current: String) -> String {
        if prefix.isEmpty { return current }
        if current.isEmpty { return prefix }
        let needsSpace = !prefix.hasSuffix(" ") && !current.hasPrefix(" ")
        return needsSpace ? prefix + " " + current : prefix + current
    }

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
