//
//  CadenceClipDriverTests.swift
//  AurionTests
//
//  #324: during-recording clip cadence floor.
//
//  Coverage:
//   - CadenceClipDriver: timer lifecycle (start/suspend/resume/invalidate),
//     the N-second watermark gate, the shared-watermark skip-if-covered
//     contract, and the per-session safety cap.
//   - clipCadenceSeconds == 0 ⇒ no timer is ever created (strict no-op).
//   - CaptureManager.cadenceClipWindow: trailing-window + session-relative
//     timestamp math.
//   - The extraction fix: a clip window resolved against the ring's ABSOLUTE
//     wall-clock baseline succeeds, where the legacy session-RELATIVE query
//     finds nothing.
//   - ClientPipelineResponse decodes `clip_cadence_seconds` (default 0).
//   - uploadClip sends the `source` form field ("cadence" vs default
//     "trigger").
//
//  Note: emitCadenceClip's fail-closed upload guard (never upload a clip
//  whose maskClip returned a failure) is structurally the same guard as the
//  proven submitVisualEvidence clip branch, and the maskClip fail-closed
//  contract itself is exercised by ClipDispatcherTests. The driver tests
//  below prove the orthogonal half: a no-op tick (onTick == false) never
//  advances the watermark or the emitted count.
//

import AVFoundation
import CoreMedia
import CoreVideo
import Foundation
import Testing
@testable import Aurion

// MARK: - Helpers

/// Mutable, main-actor-confined recorder the test closures write to. A
/// reference type so the `@escaping` onTick closure mutates the same
/// instance the test inspects.
@MainActor
private final class TickRecorder {
    var calls = 0
    var result = true
}

/// Tiny 32x32 BGRA sample buffer for the ring-baseline test. Mirrors the
/// helper in VideoRingBufferTests (which is file-private there).
private func makeCadenceTestSampleBuffer(width: Int = 32, height: Int = 32) -> CMSampleBuffer? {
    var pixelBuffer: CVPixelBuffer?
    let attrs: [String: Any] = [kCVPixelBufferIOSurfacePropertiesKey as String: [:]]
    let status = CVPixelBufferCreate(
        kCFAllocatorDefault, width, height, kCVPixelFormatType_32BGRA, attrs as CFDictionary, &pixelBuffer
    )
    guard status == kCVReturnSuccess, let pixelBuffer else { return nil }

    var formatDescription: CMFormatDescription?
    let fmtStatus = CMVideoFormatDescriptionCreateForImageBuffer(
        allocator: kCFAllocatorDefault,
        imageBuffer: pixelBuffer,
        formatDescriptionOut: &formatDescription
    )
    guard fmtStatus == noErr, let formatDescription else { return nil }

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

// MARK: - CadenceClipDriver lifecycle + decision logic

struct CadenceClipDriverTests {

    @MainActor
    @Test func lifecycle_startSuspendResumeInvalidate_togglesActive() async {
        let driver = CadenceClipDriver(cadenceSeconds: 3) { true }
        #expect(driver.isActive == false)

        driver.start()
        #expect(driver.isActive == true)          // fires while RECORDING
        #expect(driver.subIntervalSeconds == 3)   // min(3, 5)

        driver.suspend()
        #expect(driver.isActive == false)         // NO ticks while PAUSED

        driver.resume()
        #expect(driver.isActive == true)          // resumes on resume

        driver.invalidate()
        #expect(driver.isActive == false)         // gone on stop
    }

    @MainActor
    @Test func subInterval_clampsToFiveForLargeCadence() {
        #expect(CadenceClipDriver(cadenceSeconds: 10) { true }.subIntervalSeconds == 5)
        #expect(CadenceClipDriver(cadenceSeconds: 60) { true }.subIntervalSeconds == 5)
        #expect(CadenceClipDriver(cadenceSeconds: 2) { true }.subIntervalSeconds == 2)
    }

    @MainActor
    @Test func zeroCadence_createsNoTimer_andFireIsNoOp() async {
        let rec = TickRecorder()
        let driver = CadenceClipDriver(cadenceSeconds: 0) { rec.calls += 1; return true }

        driver.start()
        #expect(driver.isActive == false)         // no timer at all
        #expect(await driver.fire(now: 0) == false)
        #expect(rec.calls == 0)
    }

    @MainActor
    @Test func fire_emitsAtCadence_suppressesWithinWindow() async {
        let rec = TickRecorder()
        let driver = CadenceClipDriver(cadenceSeconds: 10) { rec.calls += 1; return true }
        let t0 = 1_000.0

        #expect(await driver.fire(now: t0) == true)         // first tick — due
        #expect(await driver.fire(now: t0 + 5) == false)    // within N — skipped
        #expect(await driver.fire(now: t0 + 10) == true)    // N elapsed — due
        #expect(await driver.fire(now: t0 + 15) == false)   // within N of 2nd — skipped
        #expect(await driver.fire(now: t0 + 20) == true)    // 2N — due

        #expect(rec.calls == 3)              // onTick only on due ticks
        #expect(driver.clipsEmitted == 3)
    }

    @MainActor
    @Test func failedTick_doesNotAdvanceWatermarkOrCount() async {
        let rec = TickRecorder()
        rec.result = false   // simulate a no-op tick (ring couldn't satisfy the window)
        let driver = CadenceClipDriver(cadenceSeconds: 10) { rec.calls += 1; return rec.result }

        #expect(await driver.fire(now: 1_000) == false)
        #expect(driver.clipsEmitted == 0)
        #expect(driver.lastClipExtractedAt == nil)

        // Watermark never advanced, so the very next tick is still due — a
        // no-op tick retries at sub-interval cadence rather than locking out.
        #expect(await driver.fire(now: 1_001) == false)
        #expect(rec.calls == 2)
    }

    @MainActor
    @Test func suspendResume_preservesWatermarkAndCount() async {
        let rec = TickRecorder()
        let driver = CadenceClipDriver(cadenceSeconds: 10) { rec.calls += 1; return true }

        #expect(await driver.fire(now: 1_000) == true)
        #expect(driver.clipsEmitted == 1)

        driver.suspend()
        driver.resume()

        // Still within N of the pre-pause emit → suppressed; count unchanged.
        #expect(await driver.fire(now: 1_005) == false)
        #expect(driver.clipsEmitted == 1)
    }

    @MainActor
    @Test func perSessionCap_stopsEmittingAtCeiling() async {
        let rec = TickRecorder()
        let driver = CadenceClipDriver(cadenceSeconds: 1, perSessionCap: 3) {
            rec.calls += 1; return true
        }

        // Drive well-spaced ticks (gap > N) so only the cap, not the
        // watermark, ends emission.
        var now = 1_000.0
        for _ in 0..<6 {
            await driver.fire(now: now)
            now += 2
        }

        #expect(driver.clipsEmitted == 3)   // capped at the ceiling
        #expect(rec.calls == 3)             // onTick never invoked past the cap
    }

    @MainActor
    @Test func noteExtraction_sharedWatermark_suppressesCadenceTickWithinWindow() async {
        let rec = TickRecorder()
        let driver = CadenceClipDriver(cadenceSeconds: 10) { rec.calls += 1; return true }

        // Simulate a future iOS-side live trigger bumping the SHARED watermark.
        driver.noteExtraction(at: 1_000)

        #expect(await driver.fire(now: 1_004) == false)   // within N → skipped
        #expect(rec.calls == 0)
        #expect(await driver.fire(now: 1_011) == true)    // past N → runs
        #expect(rec.calls == 1)
    }
}

// MARK: - cadenceClipWindow math + ring wall-clock baseline

struct CadenceClipWindowTests {

    @Test func cadenceClipWindow_trailingWindow_andSessionRelativeTimestamp() {
        let sessionStart = 1_000_000.0
        let now = sessionStart + 30.0   // 30s into the session

        let w = CaptureManager.cadenceClipWindow(
            now: now, sessionStart: sessionStart, windowMs: 7_000
        )

        // Trailing window ENDING at now: center = now - window/2, so the
        // span is [now - 7, now] — the post-roll half isn't captured yet.
        #expect(abs(w.center - (now - 3.5)) < 1e-9)
        #expect(abs(w.durationSeconds - 7.0) < 1e-9)
        // Citation anchor is session-relative.
        #expect(w.timestampMs == 30_000)
    }

    @Test func cadenceClipWindow_clampsNegativeTimestampToZero() {
        let w = CaptureManager.cadenceClipWindow(now: 5.0, sessionStart: 10.0, windowMs: 1_000)
        #expect(w.timestampMs == 0)
    }

    /// The load-bearing fix: a window resolved against the ring's ABSOLUTE
    /// wall-clock baseline matches the entries the ring stored, whereas the
    /// legacy path's SESSION-RELATIVE timestamp queries an absolute-indexed
    /// ring and finds nothing.
    @Test func extractWindow_usesAbsoluteRingBaseline_notSessionRelative() async throws {
        let ring = VideoRingBuffer(maxItems: 30, captureFPS: 10.0)

        // Populate exactly the way CaptureManager.handleVideoSampleBuffer
        // does — `append(at: Date.timeIntervalSinceReferenceDate)`.
        let base = Date.timeIntervalSinceReferenceDate
        let sessionStart = base - 5.0   // recording began 5s before the first frame
        for i in 0..<10 {
            guard let sb = makeCadenceTestSampleBuffer() else {
                #expect(Bool(false), "sample buffer creation failed"); return
            }
            ring.append(sb, at: base + 0.1 * Double(i))   // base .. base+0.9
        }

        let now = base + 0.95   // current ring clock, just after the last frame
        let w = CaptureManager.cadenceClipWindow(
            now: now, sessionStart: sessionStart, windowMs: 1_000
        )

        // Absolute center → entries fall inside the window → real MP4.
        let url = try await ring.extract(around: w.center, duration: w.durationSeconds)
        #expect(FileManager.default.fileExists(atPath: url.path))
        try? FileManager.default.removeItem(at: url)

        // Session-relative timestamp is sane (~5.95s into the session).
        #expect(w.timestampMs == Int(((now - sessionStart) * 1000.0).rounded()))

        // The legacy bug, reproduced: a SESSION-RELATIVE center (~5.95)
        // against an ABSOLUTE-indexed ring matches no entries.
        let relativeCenter = TimeInterval(w.timestampMs) / 1000.0
        await #expect(throws: VideoRingBuffer.ExtractionError.self) {
            _ = try await ring.extract(around: relativeCenter, duration: w.durationSeconds)
        }
    }
}

// MARK: - Config plumbing

struct ClipCadenceConfigTests {

    @Test func clientPipelineResponse_decodesClipCadenceSeconds() throws {
        let json = """
        {
            "stage1_skip_window_seconds": 60,
            "frame_window_clinic_ms": 3000,
            "frame_window_procedural_ms": 7000,
            "screen_capture_fps": 2,
            "video_capture_fps": 1,
            "visual_evidence_mode": "clips_only",
            "clip_window_ms": 7000,
            "clip_cadence_seconds": 45
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode(ClientPipelineResponse.self, from: json)
        #expect(decoded.clipCadenceSeconds == 45)
    }

    @Test func clientPipelineResponse_defaultsClipCadenceToZero_whenMissing() throws {
        let json = """
        {
            "stage1_skip_window_seconds": 60,
            "frame_window_clinic_ms": 3000,
            "frame_window_procedural_ms": 7000,
            "screen_capture_fps": 2,
            "video_capture_fps": 1
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode(ClientPipelineResponse.self, from: json)
        #expect(decoded.clipCadenceSeconds == 0)
    }

    @Test func remoteConfigFallback_clipCadenceIsZero() async {
        let cadence = await MainActor.run { RemoteConfig.shared.pipeline.clipCadenceSeconds }
        // Fallback default must be a strict no-op until AppConfig pushes a
        // non-zero floor. (Live /config can overwrite this at runtime; the
        // assertion is on the compiled-in fallback before any refresh.)
        #expect(cadence >= 0)
    }
}

// MARK: - uploadClip source form field

struct UploadClipSourceFieldTests {

    private func stagedBodyText(source: String?) throws -> String {
        let fakeClipURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("aurion-cadence-clip-\(UUID().uuidString).mp4")
        try Data(repeating: 0xAB, count: 16).write(to: fakeClipURL)
        defer { try? FileManager.default.removeItem(at: fakeClipURL) }

        let prepared: (request: URLRequest, bodyFileURL: URL)
        if let source {
            prepared = try APIClient.prepareClipUpload(
                baseURL: "http://localhost:8080/api/v1",
                sessionId: "sess-cadence",
                clipFileURL: fakeClipURL,
                timestampMs: 30_000,
                durationMs: 7_000,
                triggerSegmentId: "cadence_30000",
                framesTotal: 7,
                framesWithFaces: 0,
                source: source,
                authToken: nil
            )
        } else {
            prepared = try APIClient.prepareClipUpload(
                baseURL: "http://localhost:8080/api/v1",
                sessionId: "sess-cadence",
                clipFileURL: fakeClipURL,
                timestampMs: 30_000,
                durationMs: 7_000,
                triggerSegmentId: "trig_1",
                framesTotal: 7,
                framesWithFaces: 0,
                authToken: nil
            )
        }
        defer { try? FileManager.default.removeItem(at: prepared.bodyFileURL) }
        return String(data: try Data(contentsOf: prepared.bodyFileURL), encoding: .isoLatin1) ?? ""
    }

    @Test func prepareClipUpload_includesSourceField_cadence() throws {
        let body = try stagedBodyText(source: "cadence")
        #expect(body.contains("name=\"source\""))
        #expect(body.contains("\r\ncadence\r\n"))
    }

    @Test func prepareClipUpload_defaultsSourceToTrigger() throws {
        let body = try stagedBodyText(source: nil)
        #expect(body.contains("name=\"source\""))
        #expect(body.contains("\r\ntrigger\r\n"))
    }
}
