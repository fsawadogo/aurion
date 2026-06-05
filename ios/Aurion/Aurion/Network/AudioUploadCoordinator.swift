import Foundation

/// Categorised reason an audio upload attempt failed.
///
/// `error_category` payload values on `audio_upload_failed` events. Keep the
/// string casing wire-stable — the backend audit query in
/// `aurion-audit-log-dev` keys off these exact tokens to slice failures.
///
/// Deliberately NOT carrying `error.localizedDescription` — URLError's
/// `.localizedDescription` echoes the failed URL (which carries the
/// session id), and we owe the audit log a PHI-clean payload.
enum AudioUploadErrorCategory: String, Sendable {
    /// Transport-layer failure that may go away on retry: connection
    /// reset, DNS hiccup, timed out request, etc. Eligible for retry.
    case network
    /// HTTP 4xx — request itself was rejected. Retrying with the same
    /// bytes won't help; surface to the user.
    case server4xx = "server_4xx"
    /// HTTP 5xx — server-side failure. Eligible for retry but only with
    /// backoff; bursting 500s onto an already-broken backend just makes
    /// it worse.
    case server5xx = "server_5xx"
    /// The on-disk WAV the upload chain expected isn't there anymore
    /// (purged mid-flight, sandbox cleared by iOS, etc.). Not retryable
    /// — there's nothing left to upload.
    case fileMissing = "file_missing"
    /// Anything we didn't otherwise classify. Not retried.
    case unknown
}

/// Specific failure mode the UI surfaces to the clinician on the
/// processing screen. Each case maps to a localized retry prompt in
/// ``Stage1Status.retryPrompt``; lane-ios/audio-upload-ux is the matching
/// lane that lands the visual treatment.
///
/// Split out from a single "Stage 1 failed" string so the message tells
/// the truth — "check your connection" vs "recording lost" vs "server
/// error" point at different recovery paths.
enum AudioUploadFailureKind: Equatable, Sendable {
    /// Network couldn't carry the upload (URLError that we'd classify
    /// as `.network`). Retry from the on-disk WAV.
    case network
    /// AVCaptureSession finalization didn't deliver a buffer before the
    /// wait window expired, or we couldn't write the WAV to disk.
    case finalization
    /// The recorded buffer was below the minimum-bytes floor. Practically
    /// always a too-short recording; backend would reject anyway.
    case tooShort
    /// HTTP 5xx from the transcription endpoint. The audio is still on
    /// disk so the user can retry without re-recording.
    case server5xx
    /// HTTP 4xx — bad request, payload rejected, auth missing.
    case server4xx
    /// The on-disk file we were going to retry from is gone. User has to
    /// re-record; no upload is possible.
    case fileMissing
    /// Anything else — generic surface.
    case unknown
}

/// Driver for the audio upload chain. Owns a background-configured
/// URLSession so a POST that started while the app was foregrounded
/// keeps running if the user backgrounds the app mid-upload — the
/// previous foreground `URLSession.shared` path silently suspended at
/// that point and contributed to the 0-segment transcripts Dr. Marie
/// Gdalevitch hit on 2026-06-05.
///
/// The coordinator is intentionally separate from `APIClient` because:
///
/// 1. Background sessions require a stable, app-wide identifier and a
///    single delegate instance; multiplexing that through APIClient's
///    Sendable singleton would force every call site through a delegate
///    queue it doesn't need.
/// 2. Only the audio upload has SLA-critical timing + retry-with-backoff
///    semantics; everything else on APIClient is short, foreground, and
///    fine on the shared ephemeral session.
final class AudioUploadCoordinator: NSObject, @unchecked Sendable {
    static let shared = AudioUploadCoordinator()

    /// Stable identifier so iOS can resume in-flight uploads across an
    /// app re-launch. The reverse-DNS string IS the contract the system
    /// keys off; do not change without coordinating with TestFlight
    /// expectations.
    static let backgroundSessionIdentifier =
        "com.aurionclinical.physician.audio-upload"

    /// Resource timeout for the transcription POST. The backend runs
    /// Whisper synchronously, so cold-start + a 3:30 encounter can sit
    /// in the request well past the 180s used elsewhere. 300s gives
    /// headroom; the URLSession resource timeout is a hard wall-clock
    /// cap (vs. `timeoutIntervalForRequest` which resets every byte).
    static let resourceTimeoutSeconds: TimeInterval = 300

    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.background(
            withIdentifier: Self.backgroundSessionIdentifier
        )
        config.timeoutIntervalForResource = Self.resourceTimeoutSeconds
        // `sessionSendsLaunchEvents = true` lets iOS wake the app to
        // hand back upload-finished callbacks; combined with
        // `isDiscretionary = false` it keeps the POST on cellular when
        // the physician is between Wi-Fi networks.
        config.sessionSendsLaunchEvents = true
        config.isDiscretionary = false
        config.allowsCellularAccess = true
        return URLSession(
            configuration: config,
            delegate: self,
            delegateQueue: nil
        )
    }()

    /// Per-task progress observers. Keyed by `URLSessionTask.taskIdentifier`
    /// rather than the task itself (URLSessionTask is not Hashable across
    /// SDK versions). Mutated only on `delegateQueue`'s thread, so a
    /// dictionary without explicit locking is correct as long as `enqueue`
    /// runs on the same queue — which it does, see `upload(...)`.
    private var progressObservers: [Int: ProgressObserver] = [:]

    private struct ProgressObserver {
        let totalBytes: Int64
        let onProgress: @Sendable (Int64, Int64) -> Void
        /// Tracks which thresholds (25/50/75) we've already emitted so
        /// the audit log doesn't spam at every chunk.
        var emittedThresholds: Set<Int> = []
    }

    /// Upload `fileURL` to the transcription endpoint with retry, returning
    /// the response body on success. The on-disk file is the single source
    /// of truth — callers must keep it on disk until this returns
    /// successfully, and the retry path reads from the same URL on every
    /// attempt.
    ///
    /// - Parameters:
    ///   - fileURL: WAV file on disk. Must exist for the duration of the
    ///     upload chain. Caller is responsible for cleanup.
    ///   - sessionId: Aurion session id, used to build the URL and to
    ///     stamp audit events.
    ///   - bearerToken: JWT pulled from Keychain on the caller's actor.
    ///   - bytes: File size in bytes, audited at upload start.
    ///   - maxAttempts: Total attempts including the first try. The
    ///     classifier in ``classify`` decides whether to retry inside
    ///     that budget — non-retryable categories short-circuit early.
    ///   - onProgress: Called on the URLSession delegate queue at the
    ///     25/50/75% thresholds with `(bytesSent, bytesTotal)`. Used by
    ///     SessionManager to emit `audio_upload_progress` audit events.
    /// - Returns: Decoded response body bytes (the caller decodes the
    ///   transcript JSON itself — keeps this layer model-agnostic).
    /// - Throws: `AudioUploadError` with a final category if every
    ///   attempt in the budget failed.
    func upload(
        fileURL: URL,
        sessionId: String,
        bearerToken: String?,
        bytes: Int64,
        maxAttempts: Int = 3,
        onAttemptStart: @escaping @Sendable (Int) -> Void = { _ in },
        onAttemptFailure: @escaping @Sendable (Int, AudioUploadErrorCategory) -> Void = { _, _ in },
        onProgress: @escaping @Sendable (Int64, Int64) -> Void
    ) async throws -> Data {
        var lastCategory: AudioUploadErrorCategory = .unknown

        for attempt in 1...maxAttempts {
            // Re-check the file is still on disk before every attempt.
            // A LocalDataPurger run, app restart with a cleared sandbox,
            // or a stray cleanup could yank the WAV out from under us;
            // surfacing this as `fileMissing` is more honest than
            // bubbling up a generic NSURLErrorDomain.
            guard FileManager.default.fileExists(atPath: fileURL.path) else {
                throw AudioUploadError(category: .fileMissing, attempt: attempt)
            }

            onAttemptStart(attempt)

            do {
                let data = try await performOneAttempt(
                    fileURL: fileURL,
                    sessionId: sessionId,
                    bearerToken: bearerToken,
                    bytes: bytes,
                    onProgress: onProgress
                )
                return data
            } catch let urlError as URLError {
                lastCategory = classify(urlError: urlError)
            } catch let httpError as HTTPStatusError {
                lastCategory = classify(httpStatus: httpError.statusCode)
            } catch {
                lastCategory = .unknown
            }

            onAttemptFailure(attempt, lastCategory)

            let attemptError = AudioUploadError(
                category: lastCategory,
                attempt: attempt
            )

            // Bail early on non-retryable categories — re-running the same
            // bytes against the same endpoint won't change a 4xx, and
            // we've already verified `fileMissing` above.
            if !lastCategory.isRetryable || attempt == maxAttempts {
                throw attemptError
            }

            // Exponential backoff: 500ms, 1000ms, 2000ms… Capped so a
            // pathological case can't sit longer than the user's
            // patience for "I just stopped recording".
            let delayNs = backoffNanoseconds(forAttempt: attempt)
            try? await Task.sleep(nanoseconds: delayNs)
        }

        // Loop falls through only if maxAttempts == 0, which the
        // signature doesn't allow at the type level — make it explicit.
        throw AudioUploadError(category: lastCategory, attempt: maxAttempts)
    }

    /// Backoff schedule used by the retry loop. Pure function so the
    /// unit-test suite can pin the values without depending on
    /// `Task.sleep`.
    static func backoffNanoseconds(forAttempt attempt: Int) -> UInt64 {
        // 500ms * 2^(attempt-1) — 500, 1000, 2000…
        let baseMs: UInt64 = 500
        let factor: UInt64 = 1 << UInt64(max(0, attempt - 1))
        let cappedMs = min(baseMs * factor, 4_000)
        return cappedMs * 1_000_000
    }
    private func backoffNanoseconds(forAttempt attempt: Int) -> UInt64 {
        Self.backoffNanoseconds(forAttempt: attempt)
    }

    // MARK: - URL classification

    /// URLError → category. Kept `static` + pure so the unit tests can
    /// exercise the table without instantiating the coordinator.
    static func classify(urlError: URLError) -> AudioUploadErrorCategory {
        switch urlError.code {
        case .notConnectedToInternet,
             .networkConnectionLost,
             .cannotConnectToHost,
             .cannotFindHost,
             .dnsLookupFailed,
             .timedOut,
             .secureConnectionFailed,
             .resourceUnavailable,
             .internationalRoamingOff,
             .callIsActive,
             .dataNotAllowed:
            return .network
        case .fileDoesNotExist, .noPermissionsToReadFile, .fileIsDirectory:
            return .fileMissing
        default:
            return .unknown
        }
    }

    static func classify(httpStatus: Int) -> AudioUploadErrorCategory {
        switch httpStatus {
        case 400..<500: return .server4xx
        case 500..<600: return .server5xx
        default: return .unknown
        }
    }

    private func classify(urlError: URLError) -> AudioUploadErrorCategory {
        Self.classify(urlError: urlError)
    }

    private func classify(httpStatus: Int) -> AudioUploadErrorCategory {
        Self.classify(httpStatus: httpStatus)
    }

    // MARK: - One attempt

    private func performOneAttempt(
        fileURL: URL,
        sessionId: String,
        bearerToken: String?,
        bytes: Int64,
        onProgress: @escaping @Sendable (Int64, Int64) -> Void
    ) async throws -> Data {
        guard
            let url = URL(string:
                "\(AppConfig.baseAPIPath)/transcription/\(sessionId)")
        else {
            throw URLError(.badURL)
        }

        // Wrap the WAV in a multipart envelope on disk so the background
        // URLSession can stream from a file (the only upload mode it
        // supports — in-memory `httpBody` is silently dropped).
        let bodyURL = try writeMultipartBody(
            wrapping: fileURL,
            into: FileManager.default.temporaryDirectory
        )
        // The body file is the OS's responsibility once the task is
        // started; clean up on the success or failure side of this call.
        // (Outer retry loop reads fileURL again, not bodyURL.)
        defer { try? FileManager.default.removeItem(at: bodyURL) }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(
            "multipart/form-data; boundary=\(bodyURL.lastPathComponent)",
            forHTTPHeaderField: "Content-Type"
        )
        if let bearerToken {
            request.setValue(
                "Bearer \(bearerToken)",
                forHTTPHeaderField: "Authorization"
            )
        }

        return try await withCheckedThrowingContinuation { continuation in
            let task = self.session.uploadTask(
                with: request,
                fromFile: bodyURL
            ) { data, response, error in
                // Clean up progress observer regardless of outcome —
                // delegate `didCompleteWithError` will also fire and the
                // observer dict is keyed on taskIdentifier.
                if let error = error {
                    if let urlError = error as? URLError {
                        continuation.resume(throwing: urlError)
                    } else {
                        continuation.resume(throwing: URLError(.unknown))
                    }
                    return
                }
                guard
                    let http = response as? HTTPURLResponse,
                    let data = data
                else {
                    continuation.resume(throwing: URLError(.badServerResponse))
                    return
                }
                guard (200..<300).contains(http.statusCode) else {
                    continuation.resume(throwing: HTTPStatusError(
                        statusCode: http.statusCode
                    ))
                    return
                }
                continuation.resume(returning: data)
            }
            // Register the progress observer BEFORE resume() so the
            // first `didSendBodyData` delegate callback already has
            // somewhere to read totalBytes from.
            self.progressObservers[task.taskIdentifier] = ProgressObserver(
                totalBytes: bytes,
                onProgress: onProgress
            )
            task.resume()
        }
    }

    /// Build the multipart envelope on disk so the background URLSession
    /// can stream the upload from a file. Header + WAV + closing
    /// boundary, written sequentially with `FileHandle` so we don't
    /// double-buffer the audio in RAM. Returns the path of the resulting
    /// file; the basename doubles as the multipart boundary, which keeps
    /// `Content-Type: …; boundary=…` in sync.
    private func writeMultipartBody(
        wrapping audioFileURL: URL,
        into directory: URL
    ) throws -> URL {
        let boundary = UUID().uuidString
        let bodyURL = directory.appendingPathComponent(boundary)

        FileManager.default.createFile(atPath: bodyURL.path, contents: nil)
        guard let handle = try? FileHandle(forWritingTo: bodyURL) else {
            throw URLError(.cannotWriteToFile)
        }
        defer { try? handle.close() }

        let header =
            "--\(boundary)\r\n" +
            "Content-Disposition: form-data; name=\"audio_file\"; " +
            "filename=\"recording.wav\"\r\n" +
            "Content-Type: audio/wav\r\n\r\n"
        try handle.write(contentsOf: Data(header.utf8))

        let audioHandle = try FileHandle(forReadingFrom: audioFileURL)
        defer { try? audioHandle.close() }
        while let chunk = try? audioHandle.read(upToCount: 64 * 1024),
              !chunk.isEmpty {
            try handle.write(contentsOf: chunk)
        }

        let trailer = "\r\n--\(boundary)--\r\n"
        try handle.write(contentsOf: Data(trailer.utf8))

        return bodyURL
    }
}

// MARK: - URLSessionTaskDelegate

extension AudioUploadCoordinator: URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didSendBodyData bytesSent: Int64,
        totalBytesSent: Int64,
        totalBytesExpectedToSend: Int64
    ) {
        guard
            var observer = progressObservers[task.taskIdentifier],
            observer.totalBytes > 0
        else { return }

        let percent = Int(
            (Double(totalBytesSent) / Double(observer.totalBytes)) * 100
        )

        for threshold in [25, 50, 75]
            where percent >= threshold
            && !observer.emittedThresholds.contains(threshold)
        {
            observer.emittedThresholds.insert(threshold)
            observer.onProgress(totalBytesSent, observer.totalBytes)
        }
        progressObservers[task.taskIdentifier] = observer
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: Error?
    ) {
        // Continuation in performOneAttempt has already resumed via the
        // completion-handler form; the delegate fires regardless. All
        // we need to do is reap the per-task observer state.
        _ = error
        progressObservers.removeValue(forKey: task.taskIdentifier)
    }
}

extension AudioUploadCoordinator: URLSessionDelegate {
    func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        // Background session re-launch hook. The app's background
        // completion handler (configured in AppDelegate) is invoked by
        // the OS when iOS resumes us specifically to deliver these
        // events; on first ship of this lane the app doesn't yet store
        // one, so this is a no-op.
        //
        // When/if we wire AppDelegate handling, this would call the
        // stored completion handler.
    }
}

// MARK: - Public error type

/// Error thrown by ``AudioUploadCoordinator.upload(...)`` when the entire
/// retry budget has been exhausted. Carries the final classified
/// category so the caller can map it onto a localized message AND emit
/// an audit event with the same string.
struct AudioUploadError: Error, Sendable {
    let category: AudioUploadErrorCategory
    /// The 1-indexed attempt number on which we gave up. Useful for the
    /// audit row so backend dashboards can chart "fails on first try"
    /// vs "fails after every retry".
    let attempt: Int
}

/// Sentinel for non-2xx HTTP responses. Internal to this file; bubbles
/// up to `upload(...)` which translates it into an
/// ``AudioUploadErrorCategory`` via the classifier.
private struct HTTPStatusError: Error {
    let statusCode: Int
}

// MARK: - Category helpers

extension AudioUploadErrorCategory {
    /// Whether the retry loop should burn another attempt on this
    /// category. 4xx and file-missing are terminal: the same bytes
    /// against the same endpoint won't change a 4xx, and there are
    /// no bytes left if the file vanished.
    var isRetryable: Bool {
        switch self {
        case .network, .server5xx: return true
        case .server4xx, .fileMissing, .unknown: return false
        }
    }
}
