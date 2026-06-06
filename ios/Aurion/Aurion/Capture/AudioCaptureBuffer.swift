import Foundation

/// Thread-safe PCM accumulator with a capture-active gate.
///
/// Audio sample buffers arrive on a nonisolated capture-queue thread, while
/// the recording lifecycle (start / pause / resume / stop) is driven from the
/// main actor. This type is the single synchronization point between them:
/// `append` is a **no-op unless capture is active**, so paused intervals — and
/// any pre-start / post-stop buffers — never reach the uploaded WAV (#281).
///
/// Pause is a consent boundary in a clinical recorder; before this gate, the
/// `isCapturing && !isPaused` check only guarded the level meter and PCM kept
/// accumulating through a pause. Keeping the gate here (rather than hopping
/// each buffer to the main actor) avoids backpressure on the high-rate audio
/// callback.
final class AudioCaptureBuffer: @unchecked Sendable {
    private let lock = NSLock()
    private var data = Data()
    private var active = false

    /// Begin (or resume) accepting samples.
    func activate() {
        lock.lock()
        active = true
        lock.unlock()
    }

    /// Stop accepting samples WITHOUT dropping what's buffered (pause / stop).
    /// The accumulated PCM stays available for `snapshot()` so a stopped
    /// session can still build its WAV.
    func deactivate() {
        lock.lock()
        active = false
        lock.unlock()
    }

    /// Append PCM only while active — the gate that makes pause actually stop
    /// recording. A no-op when inactive.
    func append(_ pcm: Data) {
        lock.lock()
        if active { data.append(pcm) }
        lock.unlock()
    }

    /// Clear the buffer and stop accepting samples (start-reset / purge).
    func reset() {
        lock.lock()
        data = Data()
        active = false
        lock.unlock()
    }

    /// Snapshot the accumulated PCM (copy under lock).
    func snapshot() -> Data {
        lock.lock()
        defer { lock.unlock() }
        return data
    }

    /// Cheap byte-count for the audit log — no copy.
    var byteCount: Int {
        lock.lock()
        defer { lock.unlock() }
        return data.count
    }
}
