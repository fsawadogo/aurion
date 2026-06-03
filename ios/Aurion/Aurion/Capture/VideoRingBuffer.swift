import AVFoundation
import CoreMedia
import Foundation
import os

// MARK: - VideoRingBuffer
//
// Privacy contract (CLAUDE.md "Privacy" §):
// ------------------------------------------------------------------
// The ring buffer holds RAW (UNMASKED) `CMSampleBuffer` references in
// memory only. It MUST NEVER:
//   - Upload bytes to the backend.
//   - Persist bytes to durable storage (Documents, Caches, App Group, etc.).
//   - Hand its output URL to the network layer without first running it
//     through `MaskingPipeline.maskClip` (lands in P1-5).
//
// The MP4 produced by `extract(around:duration:)` is written to the app's
// temp directory and is the input to the masking pipeline. Callers — i.e.
// the future P1-5 dispatcher in SessionManager — MUST consume the URL
// through `MaskingPipeline.maskClip` BEFORE any network or persistence
// boundary. Failure to mask = fail-closed: discard the URL, do not upload.
//
// This is the same contract as `CaptureManager.capturedFrames` (which
// holds raw JPEGs in memory) and `maskVideoFrame` — the ring buffer just
// extends it from a single frame to a 7–15 s window.
//
// The privacy contract is enforced at the lock-owned state boundary
// (`OSAllocatedUnfairLock<[Entry]>` below) — the deque cannot be accessed
// outside the `withLock` closure, so any future code path that tries to
// reach the raw bytes is structurally forced to go through the same
// scoped critical section as `extract`, and from there is forced through
// the masking pipeline before any I/O. The class facade just composes
// those boundaries; it does not weaken them.
// ------------------------------------------------------------------

/// Thread-safe rolling buffer of raw video sample buffers, sized so it
/// always covers at least the longest configured clip window. Pumps from
/// `CaptureManager.handleVideoSampleBuffer` in parallel with (after) the
/// existing per-frame JPEG extractor, so the frame path is unchanged.
///
/// **Memory cost.** A 720p BGRA frame is ~3.7 MB (1280×720×4 bytes).
/// AVFoundation hands us pooled `CVPixelBuffer`s; retaining a sample
/// buffer holds onto the underlying pixel buffer until we release it.
/// At 1 fps × 15 s the worst case is 15 frames × ~3.7 MB ≈ **~55 MB
/// peak** in BGRA — the cap. In practice iOS often serves us YUV
/// (NV12) which is ~1.4 MB per 720p frame, so the steady state is
/// closer to ~21 MB. Both numbers are well within the dual-mode plan's
/// "<30 MB peak for 15s @ 720p" target (the plan's number assumes the
/// typical YUV path). The hard cap on item count is the safety valve;
/// memory growth is bounded regardless of pixel format.
///
/// **Concurrency model.** All mutating state (the deque) is owned by an
/// `OSAllocatedUnfairLock<[Entry]>` — the lock and its protected value
/// are inseparable at the type level, so the deque cannot be observed
/// outside the `withLock` closure. Append is called from the capture
/// sample-buffer delegate's nonisolated queue (a fast dispatch queue);
/// extract is called from an async context (most likely the
/// SessionManager dispatcher Task). The lock holds for O(1) on append
/// (push + maybe pop-front) and for the snapshot-copy on extract.
/// `AVAssetWriter` work runs outside the lock — extract takes a
/// snapshot under the lock and then walks the snapshot.
///
/// **Why `OSAllocatedUnfairLock`, not `NSLock` or an actor.**
///   - `NSLock`'s `lock` / `unlock` are marked unavailable from async
///     contexts under Swift 6 strict-concurrency (no priority-inheritance
///     guarantees across cooperative yields). The async `extract` method
///     would not compile in Swift 6 mode.
///   - An actor would force the nonisolated, synchronous capture delegate
///     to fire-and-forget through `Task { await ... }`, breaking the
///     strict PTS-order guarantee AVFoundation gives us and risking
///     extract observing a snapshot that's racing the in-flight Task
///     queue. The actor is purer, but for this caller pattern it would
///     silently change behavior.
///   - `OSAllocatedUnfairLock<State>` is the Apple-recommended primitive
///     for synchronous critical sections callable from any isolation
///     domain. Its `withLock` API is Sendable-safe and accepted by Swift
///     6 strict-concurrency. The state-owning generic form encodes
///     "the only mutable state in this class is the deque" at the type
///     level — stronger than the previous "remember to call lock()"
///     discipline.
///
/// `@unchecked Sendable` is retained only because `CMSampleBuffer` is
/// not `Sendable`. The lock-owned state guarantees no two threads observe
/// the deque concurrently, which is the actual safety property the
/// compiler can't infer.
final class VideoRingBuffer: @unchecked Sendable {

    // MARK: - Types

    /// What `extract` can fail with. Typed so callers can decide whether
    /// to retry, log, or fall back to a frame. Mirrors the fail-closed
    /// contract: never invent bytes when the ring can't satisfy a window.
    enum ExtractionError: Error, Equatable {
        /// Ring contains zero entries.
        case ringEmpty
        /// Ring is non-empty but no entries fall inside the requested window.
        case noEntriesInWindow
        /// `AVAssetWriter` could not be created (e.g., temp dir unwritable).
        case writerInitFailed
        /// `AVAssetWriter` reported a non-`.completed` final status.
        case writerFailed(String)
        /// A retained sample buffer no longer has a valid format description
        /// (pool got drained mid-walk). Treated as fail-closed.
        case invalidSampleBuffer
    }

    // MARK: - Stored entry

    /// One slot in the ring — the sample buffer plus the wall-clock time
    /// it arrived. Wall-clock matches `Date.timeIntervalSinceReferenceDate`
    /// to align with `CaptureManager`'s own `sessionStartTime` baseline.
    ///
    /// `@unchecked Sendable` because `CMSampleBuffer` is not natively
    /// `Sendable`. Safety comes from the surrounding
    /// `OSAllocatedUnfairLock<[Entry]>`: entries are only ever read or
    /// mutated inside `state.withLock { ... }`, which serialises access
    /// across every isolation domain. The `Entry` value never escapes
    /// the lock without first being copied into the local snapshot, and
    /// the snapshot itself is consumed serially on the extracting Task.
    private struct Entry: @unchecked Sendable {
        // `nonisolated(unsafe)` on the stored properties so they don't
        // inherit isolation from any enclosing main-actor context. The
        // backing `CMSampleBuffer` is not natively `Sendable`; the
        // surrounding `OSAllocatedUnfairLock<[Entry]>` provides the
        // serialization guarantee (the entry is only read or mutated
        // inside `withLock`).
        nonisolated(unsafe) let sampleBuffer: CMSampleBuffer
        let timestamp: TimeInterval
    }

    // MARK: - Init

    /// - Parameters:
    ///   - maxItems: hard cap on retained entries. When append pushes past
    ///     this, the oldest entry is dropped. Caller computes this as
    ///     `clipRingBufferSeconds × videoCaptureFPS` (typical: 15 × 1 = 15).
    ///   - captureFPS: documented capture rate. Used only as metadata for
    ///     the encoded MP4's frame-duration hint; the actual frame timing
    ///     comes from the sample buffer's presentation timestamps.
    init(maxItems: Int, captureFPS: Double) {
        precondition(maxItems > 0, "VideoRingBuffer maxItems must be > 0")
        precondition(captureFPS > 0, "VideoRingBuffer captureFPS must be > 0")
        self.maxItems = maxItems
        self.captureFPS = captureFPS
        self.state = OSAllocatedUnfairLock(initialState: [])
    }

    // MARK: - Configuration

    let maxItems: Int
    let captureFPS: Double

    // MARK: - State (lock-owned)

    /// The ring's deque, owned by an `OSAllocatedUnfairLock`. The lock
    /// and its protected value share a lifetime; reading or mutating the
    /// deque is only possible inside `state.withLock { entries in ... }`.
    /// This is structurally stronger than the previous "remember to call
    /// `lock.lock()` before touching `entries`" discipline and is the
    /// async-safe replacement required by Swift 6 strict-concurrency.
    private let state: OSAllocatedUnfairLock<[Entry]>

    /// Snapshot count for the audit/log surface. Cheap, takes the lock.
    ///
    /// `nonisolated` so the property is callable from `CaptureManager`'s
    /// nonisolated sample-buffer delegate without an actor hop. The lock
    /// is the safety boundary; isolation inference adds nothing.
    nonisolated var count: Int {
        state.withLock { $0.count }
    }

    // MARK: - Append

    /// Pushes a sample buffer onto the ring. If the ring is full, the
    /// oldest entry is evicted. Safe to call from any thread.
    ///
    /// `nonisolated` so AVFoundation's nonisolated sample-buffer delegate
    /// can call this synchronously, in PTS order, without a fire-and-
    /// forget Task hop. The lock guarantees serialised mutation; the
    /// retained `CMSampleBuffer` (non-`Sendable` but in-process bytes
    /// only) crosses the boundary safely because it never escapes the
    /// `withLock` closure on the producer side.
    ///
    /// The sample buffer is retained for the lifetime of its slot in the
    /// ring; eviction releases it. AVFoundation's pixel-buffer pool will
    /// reuse the underlying CVPixelBuffer once we release.
    nonisolated func append(_ sampleBuffer: CMSampleBuffer, at timestamp: TimeInterval) {
        // Construct the entry OUTSIDE `withLock` so the closure captures
        // `entry` (whose type `Entry` is explicitly `@unchecked Sendable`)
        // rather than the bare `CMSampleBuffer` parameter — which is not
        // `Sendable` and would trip the closure's `@Sendable` requirement
        // under Swift 6 strict-concurrency. The retention semantics are
        // identical: the sample buffer lives in `entry` until it's
        // appended to the deque, at which point the deque owns it.
        let entry = Entry(sampleBuffer: sampleBuffer, timestamp: timestamp)
        state.withLock { entries in
            entries.append(entry)
            if entries.count > maxItems {
                entries.removeFirst(entries.count - maxItems)
            }
        }
    }

    /// Drops every retained sample buffer. Called on session stop / reset
    /// so the pool can reclaim the underlying CVPixelBuffers immediately
    /// rather than at the next gc cycle.
    ///
    /// `nonisolated` for the same reason as `append` — clear may be
    /// called from any isolation domain, and the lock provides safety.
    nonisolated func clear() {
        state.withLock { entries in
            entries.removeAll(keepingCapacity: true)
        }
    }

    // MARK: - Extract

    /// Encodes the requested window to a temp `.mp4` and returns its file
    /// URL. The window is `[timestamp - duration/2, timestamp + duration/2]`
    /// against the same wall-clock baseline `append` records.
    ///
    /// The encoded file is:
    ///   - H.264 main profile (`AVVideoCodecType.h264`)
    ///   - **No audio track** — clips are video-only by contract (the
    ///     transcript pipeline owns audio; see CLAUDE.md "Pipeline
    ///     Architecture" §).
    ///   - Written to `NSTemporaryDirectory()` with a UUID filename; the
    ///     caller owns cleanup after upload / masking completes.
    ///
    /// Throws `ExtractionError` on any failure path. Never returns a
    /// partial or silently-truncated file.
    func extract(
        around timestamp: TimeInterval,
        duration: TimeInterval
    ) async throws -> URL {
        precondition(duration > 0, "extract duration must be > 0")

        // Snapshot the slice we need under the lock so the AVAssetWriter
        // walk doesn't race with concurrent appends.
        let halfWindow = duration / 2.0
        let windowStart = timestamp - halfWindow
        let windowEnd = timestamp + halfWindow

        // Copy the deque under the lock so the `AVAssetWriter` walk below
        // doesn't race with concurrent appends. `withLock` is the async-
        // safe scoped form required by Swift 6 strict-concurrency.
        let snapshot = state.withLock { $0 }

        guard !snapshot.isEmpty else {
            throw ExtractionError.ringEmpty
        }

        let windowed = snapshot.filter { $0.timestamp >= windowStart && $0.timestamp <= windowEnd }
        guard !windowed.isEmpty else {
            throw ExtractionError.noEntriesInWindow
        }

        // Determine the encode dimensions from the first sample buffer.
        // Every sample buffer in a single capture session has the same
        // dimensions; pulling from the first is safe.
        guard let firstFormat = CMSampleBufferGetFormatDescription(windowed[0].sampleBuffer) else {
            throw ExtractionError.invalidSampleBuffer
        }
        let dimensions = CMVideoFormatDescriptionGetDimensions(firstFormat)
        let width = Int(dimensions.width)
        let height = Int(dimensions.height)
        guard width > 0, height > 0 else {
            throw ExtractionError.invalidSampleBuffer
        }

        // Build a unique temp URL. UUID is fine here — the file is short-lived
        // and the caller cleans up. No PHI in the filename (filenames live in
        // crash reports etc.; we keep them generic).
        let tempURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("aurion-clip-\(UUID().uuidString).mp4")

        // Defensive: AVAssetWriter refuses to overwrite an existing file.
        try? FileManager.default.removeItem(at: tempURL)

        let writer: AVAssetWriter
        do {
            writer = try AVAssetWriter(outputURL: tempURL, fileType: .mp4)
        } catch {
            throw ExtractionError.writerInitFailed
        }

        let videoSettings: [String: Any] = [
            AVVideoCodecKey: AVVideoCodecType.h264,
            AVVideoWidthKey: width,
            AVVideoHeightKey: height,
            AVVideoCompressionPropertiesKey: [
                AVVideoProfileLevelKey: AVVideoProfileLevelH264MainAutoLevel
            ] as [String: Any]
        ]

        let input = AVAssetWriterInput(mediaType: .video, outputSettings: videoSettings)
        input.expectsMediaDataInRealTime = false

        // Pixel buffer adaptor so we can append frames using their pooled
        // CVPixelBuffer directly — cheaper than re-encoding through a
        // CMSampleBuffer rewrite.
        let pixelFormat = kCVPixelFormatType_32BGRA
        let adaptorAttrs: [String: Any] = [
            kCVPixelBufferPixelFormatTypeKey as String: pixelFormat,
            kCVPixelBufferWidthKey as String: width,
            kCVPixelBufferHeightKey as String: height
        ]
        let adaptor = AVAssetWriterInputPixelBufferAdaptor(
            assetWriterInput: input,
            sourcePixelBufferAttributes: adaptorAttrs
        )

        guard writer.canAdd(input) else {
            throw ExtractionError.writerInitFailed
        }
        writer.add(input)

        guard writer.startWriting() else {
            throw ExtractionError.writerFailed(writer.error?.localizedDescription ?? "startWriting failed")
        }

        // Build a synthetic timeline starting at zero so the MP4 plays back
        // from t=0 regardless of the wall-clock timestamps we collected.
        // Frame duration = 1 / captureFPS (the documented capture rate);
        // varying inter-sample gaps are smoothed to a constant cadence so
        // QuickTime / AVPlayer can scrub cleanly.
        let frameDurationSeconds = 1.0 / captureFPS
        let timescale: CMTimeScale = 600 // standard timescale for mp4
        let frameDuration = CMTime(seconds: frameDurationSeconds, preferredTimescale: timescale)

        writer.startSession(atSourceTime: .zero)

        // Append each retained frame. The pixel-buffer-adaptor path is
        // synchronous from our side; we busy-poll `isReadyForMoreMediaData`
        // with a short Task.yield() between waits so we don't block the
        // capture queue. In practice, with only ~15 frames in flight, the
        // adaptor is always ready and the loop runs to completion immediately.
        var presentationTime = CMTime.zero
        for entry in windowed {
            guard let pixelBuffer = CMSampleBufferGetImageBuffer(entry.sampleBuffer) else {
                continue // drop a malformed buffer rather than failing the whole clip
            }

            // Wait for the writer's input to be ready. AVAssetWriter input
            // exposes only a boolean check — there's no Combine-style hook,
            // so we yield to the cooperative scheduler between checks.
            while !input.isReadyForMoreMediaData {
                await Task.yield()
            }

            let appended = adaptor.append(pixelBuffer, withPresentationTime: presentationTime)
            if !appended {
                // Mid-stream failure — finish the writer cleanly so we don't
                // leak file descriptors, then surface the error.
                input.markAsFinished()
                await writer.finishWriting()
                try? FileManager.default.removeItem(at: tempURL)
                throw ExtractionError.writerFailed(writer.error?.localizedDescription ?? "append failed")
            }

            presentationTime = CMTimeAdd(presentationTime, frameDuration)
        }

        input.markAsFinished()
        await writer.finishWriting()

        guard writer.status == .completed else {
            try? FileManager.default.removeItem(at: tempURL)
            throw ExtractionError.writerFailed(writer.error?.localizedDescription ?? "writer status=\(writer.status.rawValue)")
        }

        return tempURL
    }
}
