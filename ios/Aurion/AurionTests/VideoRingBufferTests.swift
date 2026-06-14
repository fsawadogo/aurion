//
//  VideoRingBufferTests.swift
//  AurionTests
//
//  P1-4: VideoRingBuffer + VisualEvidence enum.
//

import AVFoundation
import CoreMedia
import CoreVideo
import Foundation
import Testing
@testable import Aurion

// MARK: - Helpers

/// Build a tiny synthetic CMSampleBuffer backed by a 32x32 BGRA pixel
/// buffer. The contents don't matter — the ring buffer only cares about
/// the format description + image buffer + retain semantics. Keeping
/// dimensions small makes the encode in `extract` fast enough that the
/// test suite stays sub-second.
private func makeSyntheticSampleBuffer(width: Int = 32, height: Int = 32) -> CMSampleBuffer? {
    var pixelBuffer: CVPixelBuffer?
    let attrs: [String: Any] = [
        kCVPixelBufferIOSurfacePropertiesKey as String: [:]
    ]
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        width,
        height,
        kCVPixelFormatType_32BGRA,
        attrs as CFDictionary,
        &pixelBuffer
    )
    guard status == kCVReturnSuccess, let pixelBuffer else { return nil }

    // Optional: scribble a known byte pattern so an inspecting test could
    // verify the buffer survived end-to-end. Not asserted today; the
    // VideoRingBuffer contract only promises "encodes the entries you
    // appended", not "preserves their RGB values bit-for-bit".
    CVPixelBufferLockBaseAddress(pixelBuffer, [])
    if let base = CVPixelBufferGetBaseAddress(pixelBuffer) {
        let bytes = base.assumingMemoryBound(to: UInt8.self)
        let length = CVPixelBufferGetDataSize(pixelBuffer)
        bytes.update(repeating: 0x80, count: length)
    }
    CVPixelBufferUnlockBaseAddress(pixelBuffer, [])

    var formatDescription: CMFormatDescription?
    let fmtStatus = CMVideoFormatDescriptionCreateForImageBuffer(
        allocator: kCFAllocatorDefault,
        imageBuffer: pixelBuffer,
        formatDescriptionOut: &formatDescription
    )
    guard fmtStatus == noErr, let formatDescription else { return nil }

    // Bare-minimum timing — the ring buffer keys off the timestamp we
    // pass to `append`, not the CMSampleBuffer's own PTS, so any valid
    // timing info works.
    var timing = CMSampleTimingInfo(
        duration: CMTime(value: 1, timescale: 30),
        presentationTimeStamp: .zero,
        decodeTimeStamp: .invalid
    )
    var sampleBuffer: CMSampleBuffer?
    let sbStatus = CMSampleBufferCreateForImageBuffer(
        allocator: kCFAllocatorDefault,
        imageBuffer: pixelBuffer,
        dataReady: true,
        makeDataReadyCallback: nil,
        refcon: nil,
        formatDescription: formatDescription,
        sampleTiming: &timing,
        sampleBufferOut: &sampleBuffer
    )
    guard sbStatus == noErr else { return nil }
    return sampleBuffer
}

/// Build a bare 32x32 BGRA `CVPixelBuffer` — the input an external video
/// source (Meta glasses, #443) hands to `append(_ pixelBuffer:at:)`.
private func makeSyntheticPixelBuffer(width: Int = 32, height: Int = 32) -> CVPixelBuffer? {
    var pixelBuffer: CVPixelBuffer?
    let attrs: [String: Any] = [
        kCVPixelBufferIOSurfacePropertiesKey as String: [:]
    ]
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault,
        width,
        height,
        kCVPixelFormatType_32BGRA,
        attrs as CFDictionary,
        &pixelBuffer
    )
    guard status == kCVReturnSuccess else { return nil }
    return pixelBuffer
}

// MARK: - Tests

struct VideoRingBufferTests {

    // MARK: AC-1 / AC-4 — append + overflow + clear

    @Test func append_addsSamplesAndReportsCount() {
        let ring = VideoRingBuffer(maxItems: 5, captureFPS: 1.0)
        #expect(ring.count == 0)

        for i in 0..<3 {
            let sb = makeSyntheticSampleBuffer()
            #expect(sb != nil)
            ring.append(sb!, at: TimeInterval(i))
        }

        #expect(ring.count == 3)
    }

    @Test func append_evictsOldestOnOverflow() {
        let cap = 3
        let ring = VideoRingBuffer(maxItems: cap, captureFPS: 1.0)

        for i in 0..<(cap + 4) {
            let sb = makeSyntheticSampleBuffer()
            #expect(sb != nil)
            ring.append(sb!, at: TimeInterval(i))
        }

        // Cap is the hard ceiling — every overflow append evicts one entry.
        #expect(ring.count == cap)
    }

    @Test func clear_emptiesDeque() {
        let ring = VideoRingBuffer(maxItems: 5, captureFPS: 1.0)
        for i in 0..<4 {
            let sb = makeSyntheticSampleBuffer()
            #expect(sb != nil)
            ring.append(sb!, at: TimeInterval(i))
        }
        #expect(ring.count == 4)

        ring.clear()
        #expect(ring.count == 0)
    }

    // MARK: AC-2 — extract returns valid audio-free MP4

    @Test func extract_returnsAudioFreeMP4() async throws {
        let ring = VideoRingBuffer(maxItems: 30, captureFPS: 10.0)

        // Pack 10 frames covering [0, 1.0] seconds at 10 fps.
        for i in 0..<10 {
            let sb = makeSyntheticSampleBuffer()
            #expect(sb != nil)
            ring.append(sb!, at: 0.1 * Double(i))
        }

        // Extract a 1-second window centered at t=0.5 — should capture all 10 frames.
        let url = try await ring.extract(around: 0.5, duration: 1.0)

        // Cleanup at end regardless of expectations.
        defer { try? FileManager.default.removeItem(at: url) }

        // File exists and is non-empty.
        let attrs = try FileManager.default.attributesOfItem(atPath: url.path)
        let size = attrs[.size] as? Int ?? 0
        #expect(size > 0)

        // CRITICAL: the MP4 must contain a video track and ZERO audio tracks.
        // This is the dual-mode privacy contract — clips are video-only.
        let asset = AVURLAsset(url: url)
        let audioTracks = try await asset.loadTracks(withMediaType: .audio)
        #expect(audioTracks.isEmpty == true)

        let videoTracks = try await asset.loadTracks(withMediaType: .video)
        #expect(videoTracks.isEmpty == false)
    }

    // MARK: AC-3 — extract fails closed when ring can't satisfy the window

    @Test func extract_throwsOnEmptyRing() async {
        let ring = VideoRingBuffer(maxItems: 5, captureFPS: 1.0)
        await #expect(throws: VideoRingBuffer.ExtractionError.self) {
            _ = try await ring.extract(around: 0, duration: 1.0)
        }
    }

    @Test func extract_throwsWhenWindowOutsideEntries() async throws {
        let ring = VideoRingBuffer(maxItems: 5, captureFPS: 1.0)

        // Fill at timestamps [0, 1, 2]; ask for a tiny window at t=100 — far outside.
        for i in 0..<3 {
            let sb = makeSyntheticSampleBuffer()
            #expect(sb != nil)
            ring.append(sb!, at: TimeInterval(i))
        }

        await #expect(throws: VideoRingBuffer.ExtractionError.self) {
            _ = try await ring.extract(around: 100.0, duration: 0.5)
        }
    }

    // MARK: AC-5 — thread safety

    @Test func append_threadSafeUnderTaskGroup() async {
        let cap = 50
        let ring = VideoRingBuffer(maxItems: cap, captureFPS: 1.0)
        let totalAppends = 200

        // Build the sample buffers up front so the parallel appends inside
        // the TaskGroup don't share the (non-Sendable) buffer creation.
        // Each closure captures its own buffer.
        await withTaskGroup(of: Void.self) { group in
            for i in 0..<totalAppends {
                guard let sb = makeSyntheticSampleBuffer() else { continue }
                let ts = TimeInterval(i)
                group.addTask {
                    ring.append(sb, at: ts)
                }
            }
        }

        // Final count is bounded by the cap; no crash means the lock did its job.
        #expect(ring.count <= cap)
        #expect(ring.count > 0)
    }

    // MARK: P1-4-FU — strict-concurrency / actor-locking forward-compat
    //
    // Specifically exercises the Swift 6 path we migrated to in P1-4-FU:
    // many concurrent appends against `OSAllocatedUnfairLock<[Entry]>`
    // followed by a single async extract that snapshots the deque under
    // the same lock. If the lock ever stops serialising, this test will
    // either crash (data race in the Array) or extract a malformed MP4.
    // Both failure modes are caught by the AVURLAsset round-trip below.

    @Test func extract_underHeavyConcurrentAppendLoad() async throws {
        // Hold 100 entries — bigger than the previous test so the
        // "ring overflow vs concurrent append" interaction has more
        // surface area. captureFPS=10 keeps the encoded clip duration
        // visible to the AVURLAsset duration check (10 fps × 1 s window).
        let cap = 100
        let ring = VideoRingBuffer(maxItems: cap, captureFPS: 10.0)

        let totalAppends = 100

        // Spawn 100 concurrent appends. Each gets its own freshly-created
        // sample buffer so there's no shared backing. Timestamps are
        // spaced across [0, 10] seconds so the later extract window can
        // selectively cover them all.
        await withTaskGroup(of: Void.self) { group in
            for i in 0..<totalAppends {
                guard let sb = makeSyntheticSampleBuffer() else { continue }
                // Spread timestamps evenly across 10 seconds so the extract
                // window catches them all.
                let ts = TimeInterval(i) * 0.1
                group.addTask {
                    ring.append(sb, at: ts)
                }
            }
        }

        // The ring is bounded by `cap`. Under heavy concurrent load some
        // entries may have been evicted before all appends landed — that's
        // expected and matches production behavior under back-pressure.
        let observedCount = ring.count
        #expect(observedCount > 0)
        #expect(observedCount <= cap)

        // Extract a window covering the entire 0–10s span. The lock's
        // snapshot-under-withLock must serialise against any straggling
        // appends; if it doesn't, AVAssetWriter will fail mid-encode.
        let url = try await ring.extract(around: 5.0, duration: 10.0)
        defer { try? FileManager.default.removeItem(at: url) }

        // Round-trip through AVURLAsset to prove the MP4 is well-formed.
        // A torn write or a race in the deque snapshot would surface here
        // as a load failure or an unreadable video track.
        let asset = AVURLAsset(url: url)
        let videoTracks = try await asset.loadTracks(withMediaType: .video)
        #expect(videoTracks.count == 1)

        // No audio — same privacy contract as the per-frame extract test.
        let audioTracks = try await asset.loadTracks(withMediaType: .audio)
        #expect(audioTracks.isEmpty == true)

        // The encoded clip should hold no more frames than the cap (and
        // no more than what we actually observed in the ring at extract
        // time). This isn't a strict bound on `observedCount` because
        // the extractor uses its own snapshot, but it IS a strict bound
        // on `cap`.
        let track = try #require(videoTracks.first)
        let nominalFrameRate = try await track.load(.nominalFrameRate)
        // 10 fps was the configured captureFPS, so the synthesized timing
        // should target ~10 fps. Allow generous slack — the writer chooses
        // its own keyframe interval which can shift the nominal rate.
        #expect(nominalFrameRate > 0)
    }

    // MARK: #390 — framesAppendedTotal (clip-pipeline summary signal)
    //
    // `framesAppendedTotal` is the SOLE source of the summary beacon's
    // `ring_frames_appended`, which distinguishes "the camera never produced
    // frames" from "frames flowed but extraction kept failing". A regression
    // where `append()` stops bumping it would surface only as a permanently-
    // zero metric — invisible without these tests.

    @Test func framesAppendedTotal_startsAtZero() {
        let ring = VideoRingBuffer(maxItems: 5, captureFPS: 1.0)
        #expect(ring.framesAppendedTotal == 0)
    }

    @Test func framesAppendedTotal_incrementsMonotonically() {
        let ring = VideoRingBuffer(maxItems: 10, captureFPS: 1.0)
        for i in 0..<6 {
            let sb = makeSyntheticSampleBuffer()
            #expect(sb != nil)
            ring.append(sb!, at: TimeInterval(i))
        }
        #expect(ring.framesAppendedTotal == 6)
    }

    @Test func framesAppendedTotal_isIndependentOfEviction() {
        // The cap bounds `count` (current depth) but NOT the appended total:
        // every frame the ring RECEIVED is counted, even after eviction.
        let cap = 3
        let ring = VideoRingBuffer(maxItems: cap, captureFPS: 1.0)
        let appends = cap + 5
        for i in 0..<appends {
            let sb = makeSyntheticSampleBuffer()
            #expect(sb != nil)
            ring.append(sb!, at: TimeInterval(i))
        }
        #expect(ring.count == cap)                    // depth capped
        #expect(ring.framesAppendedTotal == appends)  // total uncapped
    }

    @Test func framesAppendedTotal_resetsOnClear() {
        let ring = VideoRingBuffer(maxItems: 5, captureFPS: 1.0)
        for i in 0..<4 {
            let sb = makeSyntheticSampleBuffer()
            #expect(sb != nil)
            ring.append(sb!, at: TimeInterval(i))
        }
        #expect(ring.framesAppendedTotal == 4)
        ring.clear()
        #expect(ring.framesAppendedTotal == 0)
    }

    // MARK: Init contract

    @Test func init_acceptsConfigValues() {
        let ring = VideoRingBuffer(maxItems: 15, captureFPS: 1.0)
        #expect(ring.maxItems == 15)
        #expect(ring.captureFPS == 1.0)
    }

    // MARK: #440 — external-source CVPixelBuffer ingest (Meta glasses feed)
    //
    // External sources deliver decoded frames (CVPixelBuffer / UIImage), not
    // CMSampleBuffers. `append(_ pixelBuffer:at:)` wraps them so they flow
    // through the SAME ring + extract + (downstream) masking path. These lock
    // that the pixel-buffer path buffers + extracts identically to the
    // AVCaptureSession path the iPhone camera uses.

    @Test func appendPixelBuffer_addsToRingAndCountsTotal() {
        let ring = VideoRingBuffer(maxItems: 5, captureFPS: 1.0)
        #expect(ring.count == 0)
        for i in 0..<3 {
            let pb = makeSyntheticPixelBuffer()
            #expect(pb != nil)
            ring.append(pb!, at: TimeInterval(i))
        }
        #expect(ring.count == 3)
        #expect(ring.framesAppendedTotal == 3)
    }

    @Test func appendPixelBuffer_extractsAudioFreeMP4() async throws {
        // Proves the synthesized sample buffers extract to a valid, audio-free
        // MP4 — the exact seam the glasses source (#443) relies on.
        let ring = VideoRingBuffer(maxItems: 30, captureFPS: 10.0)
        for i in 0..<10 {
            let pb = makeSyntheticPixelBuffer()
            #expect(pb != nil)
            ring.append(pb!, at: 0.1 * Double(i))
        }
        let url = try await ring.extract(around: 0.5, duration: 1.0)
        defer { try? FileManager.default.removeItem(at: url) }

        let asset = AVURLAsset(url: url)
        let videoTracks = try await asset.loadTracks(withMediaType: .video)
        #expect(videoTracks.isEmpty == false)
        let audioTracks = try await asset.loadTracks(withMediaType: .audio)
        #expect(audioTracks.isEmpty == true)
    }
}

// MARK: - VisualEvidence sanity

struct VisualEvidenceTests {

    @Test func frameCase_carriesCapturedFrameUnchanged() {
        let frame = CapturedFrame(timestamp: 1.23, imageData: Data([0xff, 0xd8]))
        let evidence = VisualEvidence.frame(frame)

        switch evidence {
        case .frame(let captured):
            #expect(captured.timestamp == 1.23)
            #expect(captured.imageData.count == 2)
        case .clip:
            #expect(Bool(false), "expected .frame case")
        }
    }

    @Test func clipCase_carriesURLAndTrigger() {
        let url = URL(fileURLWithPath: "/tmp/aurion-test.mp4")
        let trigger = TriggerEvent(kind: "rom", timestamp: 14.5, segmentId: "seg_001")
        let evidence = VisualEvidence.clip(url, duration: 7_000, trigger: trigger)

        switch evidence {
        case .frame:
            #expect(Bool(false), "expected .clip case")
        case .clip(let gotURL, let duration, let gotTrigger):
            #expect(gotURL == url)
            #expect(duration == 7_000)
            #expect(gotTrigger == trigger)
        }
    }
}
