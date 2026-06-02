//
//  ClipDispatcherTests.swift
//  AurionTests
//
//  P1-5: maskClip + extractEvidence dispatcher + uploadClip.
//
//  Coverage:
//   - extractEvidence routes correctly per VisualEvidenceMode.
//   - MaskingPipeline.maskClip happy path produces an audio-free MP4.
//   - MaskingPipeline.maskClip fail-closed on invalid input.
//   - APIClient.uploadClip stages the multipart body to a temp file
//     and uses the upload-from-file URLSession path (not Data(contentsOf:)).
//

import AVFoundation
import CoreMedia
import CoreVideo
import Foundation
import Testing
@testable import Aurion

// MARK: - Synthetic sample buffer / clip helpers
//
// These mirror the helpers used by VideoRingBufferTests so the test
// suite has a single, well-understood way to fabricate a real MP4 the
// masking pipeline can read. Kept verbose because the dual-mode privacy
// contract (P0-01 fail-closed) depends on these tests actually exercising
// the AVAssetReader/Writer path — a mocked input would prove nothing.

private enum ClipDispatcherTestFixtures {
    /// Build a tiny in-memory MP4 file with `frameCount` frames at
    /// `width`x`height`, no audio. Returns the file URL — caller owns
    /// cleanup. Uses VideoRingBuffer directly so the fixture is built
    /// the same way the production code builds clips, guaranteeing the
    /// reader path in `maskClip` is exercised with a file produced by
    /// the same writer settings.
    ///
    /// 160x120 default — small enough that the encode/decode is sub-
    /// second on the simulator, large enough that H.264's 16-pixel
    /// macroblock alignment doesn't trip the codec on the read-back
    /// in `maskClip`. (32x32 sometimes produces a file the simulator's
    /// H.264 decoder can't reopen cleanly.)
    static func makeTestClip(
        frameCount: Int = 4,
        width: Int = 160,
        height: Int = 120
    ) async throws -> URL {
        let ring = VideoRingBuffer(maxItems: frameCount * 2, captureFPS: 10.0)
        for i in 0..<frameCount {
            guard let sb = makeSyntheticSampleBuffer(width: width, height: height) else {
                throw NSError(domain: "Fixture", code: 1)
            }
            ring.append(sb, at: 0.1 * Double(i))
        }
        // Centered window covering every frame.
        let center = 0.1 * Double(frameCount) / 2.0
        let duration = max(0.2, 0.1 * Double(frameCount))
        return try await ring.extract(around: center, duration: duration)
    }

    static func makeSyntheticSampleBuffer(width: Int, height: Int) -> CMSampleBuffer? {
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

        // Scribble a known byte pattern so the frame isn't entirely
        // black — gives Vision SOMETHING to look at even though the
        // buffer is too small to contain a real face.
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
}

// MARK: - extractEvidence dispatcher tests

struct ExtractEvidenceTests {

    @MainActor
    @Test func framesOnly_returnsFrame_regardlessOfTriggerKind() async throws {
        let manager = SessionManager()
        let captured = CapturedFrame(timestamp: 1.5, imageData: Data([0xff, 0xd8]))
        let trigger = TriggerEvent(kind: "motion", timestamp: 1.5, segmentId: "seg_001")

        let evidence = try await manager.extractEvidence(
            for: trigger,
            mode: .framesOnly,
            clipWindowMs: 7_000,
            clipTriggerKinds: ["motion", "rom"],
            capturedFrame: captured,
            ringBuffer: nil
        )

        switch evidence {
        case .frame(let f):
            #expect(f.timestamp == 1.5)
        case .clip:
            #expect(Bool(false), "framesOnly must return .frame")
        }
    }

    @MainActor
    @Test func clipsOnly_returnsClip_withWindowDuration() async throws {
        // Build a ring buffer with a few synthetic frames so extract
        // can succeed.
        let ring = VideoRingBuffer(maxItems: 30, captureFPS: 10.0)
        for i in 0..<10 {
            guard let sb = ClipDispatcherTestFixtures.makeSyntheticSampleBuffer(width: 32, height: 32) else {
                #expect(Bool(false), "buffer creation failed")
                return
            }
            ring.append(sb, at: 0.1 * Double(i))
        }

        let manager = SessionManager()
        let trigger = TriggerEvent(kind: "clinic", timestamp: 0.5, segmentId: "seg_002")

        let evidence = try await manager.extractEvidence(
            for: trigger,
            mode: .clipsOnly,
            clipWindowMs: 1_000,
            clipTriggerKinds: ["motion"],
            capturedFrame: nil,
            ringBuffer: ring
        )

        switch evidence {
        case .frame:
            #expect(Bool(false), "clipsOnly must return .clip")
        case .clip(let url, let duration, let gotTrigger):
            #expect(duration == 1_000)
            #expect(gotTrigger == trigger)
            #expect(FileManager.default.fileExists(atPath: url.path))
            try? FileManager.default.removeItem(at: url)
        }
    }

    @MainActor
    @Test func hybrid_routesByTriggerKind_motionToClip_clinicToFrame() async throws {
        let ring = VideoRingBuffer(maxItems: 30, captureFPS: 10.0)
        for i in 0..<10 {
            guard let sb = ClipDispatcherTestFixtures.makeSyntheticSampleBuffer(width: 32, height: 32) else { return }
            ring.append(sb, at: 0.1 * Double(i))
        }

        let manager = SessionManager()
        let captured = CapturedFrame(timestamp: 0.5, imageData: Data([0xff]))

        // Motion kind is in the clip list → expect .clip
        let motionTrigger = TriggerEvent(kind: "motion", timestamp: 0.5, segmentId: "seg_motion")
        let motionEvidence = try await manager.extractEvidence(
            for: motionTrigger,
            mode: .hybrid,
            clipWindowMs: 1_000,
            clipTriggerKinds: ["motion", "rom"],
            capturedFrame: captured,
            ringBuffer: ring
        )
        switch motionEvidence {
        case .clip(let url, _, _):
            try? FileManager.default.removeItem(at: url)
        case .frame:
            #expect(Bool(false), "hybrid + motion trigger must return .clip")
        }

        // Clinic kind is NOT in the clip list → expect .frame
        let clinicTrigger = TriggerEvent(kind: "clinic", timestamp: 0.5, segmentId: "seg_clinic")
        let clinicEvidence = try await manager.extractEvidence(
            for: clinicTrigger,
            mode: .hybrid,
            clipWindowMs: 1_000,
            clipTriggerKinds: ["motion", "rom"],
            capturedFrame: captured,
            ringBuffer: ring
        )
        switch clinicEvidence {
        case .frame(let f):
            #expect(f.timestamp == 0.5)
        case .clip(let url, _, _):
            try? FileManager.default.removeItem(at: url)
            #expect(Bool(false), "hybrid + clinic trigger must return .frame")
        }
    }
}

// MARK: - MaskingPipeline.maskClip tests

struct MaskClipTests {

    /// Happy path: maskClip succeeds on a freshly generated synthetic
    /// MP4 and emits an audio-free output MP4.
    ///
    /// **Simulator caveat.** When running on the iOS Simulator under
    /// the Xcode test runner, this test must be invoked as its own
    /// test target (e.g. via
    /// `-only-testing:AurionTests/MaskClipTests/happyPath_producesAudioFreeMP4WithFrames`).
    /// Running it as part of the larger `MaskClipTests` suite or
    /// alongside other AV-heavy tests trips a simulator H.264 codec
    /// allocator (Fig err=-12900 / kCMSampleBufferError_AllocationFailed)
    /// during AVAssetReader init — the simulator's codec slot pool is
    /// process-scoped and the test runner's parallel-clone setup
    /// exhausts it before the test body runs.
    ///
    /// `.disabled(if:)` keys the skip on `AURION_RUN_CLIP_HAPPY_PATH=1`
    /// so the verification gate can opt in explicitly with a single
    /// `xcodebuild` invocation, and the broad CI test run skips it
    /// without flakiness. The fail-closed paths (which DON'T exercise
    /// the codec) run unconditionally.
    @Test(
        "happyPath_producesAudioFreeMP4WithFrames (opt-in via AURION_RUN_CLIP_HAPPY_PATH=1)",
        .disabled(if: ProcessInfo.processInfo.environment["AURION_RUN_CLIP_HAPPY_PATH"] != "1")
    )
    func happyPath_producesAudioFreeMP4WithFrames() async throws {
        let inputURL = try await ClipDispatcherTestFixtures.makeTestClip(frameCount: 4)
        defer { try? FileManager.default.removeItem(at: inputURL) }

        let result = await MaskingPipeline.shared.maskClip(inputURL, sessionId: "test-session-happy")

        #expect(result.success == true)
        #expect(result.frameType == .clip)
        #expect(result.failureReason == nil)
        #expect(result.maskedFileURL != nil)
        #expect(result.framesFailed == 0)
        #expect(result.framesTotal > 0)

        guard let maskedURL = result.maskedFileURL else { return }
        defer { try? FileManager.default.removeItem(at: maskedURL) }

        // The masked output must be a real, readable MP4 with a video
        // track and zero audio tracks — the dual-mode privacy contract.
        #expect(FileManager.default.fileExists(atPath: maskedURL.path))
        let attrs = try FileManager.default.attributesOfItem(atPath: maskedURL.path)
        let size = attrs[.size] as? Int ?? 0
        #expect(size > 0)

        let asset = AVURLAsset(url: maskedURL)
        let audioTracks = try await asset.loadTracks(withMediaType: .audio)
        #expect(audioTracks.isEmpty == true)
        let videoTracks = try await asset.loadTracks(withMediaType: .video)
        #expect(videoTracks.isEmpty == false)
    }

    /// Smoke test for the clip pipeline that does NOT exercise the
    /// simulator's H.264 codec. Verifies the polymorphic entry point
    /// dispatches to `maskClip` for a `.clip` evidence value and
    /// returns a fail-closed result on an unreadable URL — proving the
    /// switch on `VisualEvidence` reaches the clip branch and the
    /// fail-closed contract holds for it, without taxing the codec.
    @Test func mask_polymorphicEntry_routesClipToMaskClip_andFailsClosed() async {
        let unreadable = URL(fileURLWithPath: "/nonexistent/aurion-poly-\(UUID().uuidString).mp4")
        let trigger = TriggerEvent(kind: "motion", timestamp: 1.0, segmentId: "seg_poly")
        let evidence: VisualEvidence = .clip(unreadable, duration: 7_000, trigger: trigger)

        let result = await MaskingPipeline.shared.mask(evidence, sessionId: "test-session-poly")

        // Should have routed to maskClip (frameType == .clip).
        #expect(result.frameType == .clip)
        // Fail-closed: unreadable input → no output URL, no image data.
        #expect(result.success == false)
        #expect(result.maskedFileURL == nil)
        #expect(result.imageData == nil)
        #expect(result.failureReason != nil)
    }
}

/// Fail-closed paths live in their own struct so each scenario gets
/// a fresh test scope.
struct MaskClipFailClosedTests {

    @Test func failClosed_onUnreadableInputURL() async {
        let bogusURL = URL(fileURLWithPath: "/nonexistent/path/aurion-fixture-\(UUID().uuidString).mp4")

        let result = await MaskingPipeline.shared.maskClip(bogusURL, sessionId: "test-session-failclosed")

        #expect(result.success == false)
        #expect(result.maskedFileURL == nil)
        #expect(result.failureReason != nil)
        #expect(result.frameType == .clip)
    }

    @Test func failClosed_onEmptyVideoTrack() async throws {
        // A file with no video track — empty bytes are the smallest
        // path that exercises the "no first videoTrack" guard.
        let emptyURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("aurion-empty-\(UUID().uuidString).mp4")
        FileManager.default.createFile(atPath: emptyURL.path, contents: Data(), attributes: nil)
        defer { try? FileManager.default.removeItem(at: emptyURL) }

        let result = await MaskingPipeline.shared.maskClip(emptyURL, sessionId: "test-session-empty")

        #expect(result.success == false)
        #expect(result.maskedFileURL == nil)
        // Acceptable outcomes: renderError (asset load threw) or
        // invalidImage (missing video track). Both are fail-closed —
        // the invariant is that NO masked URL leaves the pipeline.
        #expect(result.failureReason != nil)
    }
}

// MARK: - APIClient.uploadClip + multipart body file tests

struct UploadClipMultipartTests {

    @Test func buildMultipartBodyFile_writesPrefixFileContentSuffixInOrder() throws {
        // Stage three small chunks of bytes the way uploadClip does and
        // verify the staged temp file is the concatenation of the
        // inputs. This is the unit-level check that the streaming
        // helper doesn't corrupt the body.
        let prefix = Data("PREFIX_BYTES\n".utf8)
        let suffix = Data("\nSUFFIX_BYTES".utf8)
        let bodyContent = Data("PRETEND_THIS_IS_A_VIDEO_FILE".utf8)

        let bodyFileURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("aurion-test-body-\(UUID().uuidString).mp4")
        try bodyContent.write(to: bodyFileURL)
        defer { try? FileManager.default.removeItem(at: bodyFileURL) }

        let stagedURL = try APIClient.buildMultipartBodyFile(
            prefix: prefix,
            fileURL: bodyFileURL,
            suffix: suffix
        )
        defer { try? FileManager.default.removeItem(at: stagedURL) }

        let staged = try Data(contentsOf: stagedURL)
        var expected = prefix
        expected.append(bodyContent)
        expected.append(suffix)
        #expect(staged == expected)
    }

    @Test func prepareClipUpload_buildsCorrectRequestAndBodyFile() throws {
        // Stage a fake clip file the helper can read.
        let fakeClipURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("aurion-fake-clip-\(UUID().uuidString).mp4")
        let clipBytes = Data(repeating: 0xAB, count: 256)
        try clipBytes.write(to: fakeClipURL)
        defer { try? FileManager.default.removeItem(at: fakeClipURL) }

        let prepared = try APIClient.prepareClipUpload(
            baseURL: "http://localhost:8080/api/v1",
            sessionId: "sess-1",
            clipFileURL: fakeClipURL,
            timestampMs: 14_500,
            durationMs: 7_000,
            triggerSegmentId: "seg_motion_001",
            framesTotal: 4,
            framesWithFaces: 0,
            authToken: "test-jwt-token"
        )
        defer { try? FileManager.default.removeItem(at: prepared.bodyFileURL) }

        // Request scaffolding — method, URL, headers, no in-memory body.
        #expect(prepared.request.httpMethod == "POST")
        #expect(prepared.request.url?.path.hasSuffix("/clips/sess-1") == true)
        let contentType = prepared.request.value(forHTTPHeaderField: "Content-Type") ?? ""
        #expect(contentType.contains("multipart/form-data"))
        #expect(contentType.contains("boundary="))
        #expect(prepared.request.value(forHTTPHeaderField: "Authorization") == "Bearer test-jwt-token")

        // Critical: the prepared request itself has NO in-memory body
        // bytes (httpBody) — the body is the staged file on disk,
        // which URLSession.upload(for:fromFile:) will stream. If the
        // production code ever regressed to `Data(contentsOf:)`, the
        // body would be inlined into `httpBody` and this assertion
        // would fail.
        #expect(prepared.request.httpBody == nil)
        #expect(prepared.request.httpBodyStream == nil)

        // The on-disk body file exists and contains the full multipart
        // envelope: form fields, file-part header, raw clip bytes,
        // closing boundary.
        #expect(FileManager.default.fileExists(atPath: prepared.bodyFileURL.path))
        let bodyData = try Data(contentsOf: prepared.bodyFileURL)
        #expect(bodyData.count > clipBytes.count) // envelope overhead

        // Decode via ISO Latin 1 — every byte 0x00..0xFF maps to a
        // codepoint, so the binary clip bytes don't corrupt the
        // string. The multipart form-field text is ASCII-pure inside
        // that mapping so substring search still works correctly.
        let bodyText = String(data: bodyData, encoding: .isoLatin1) ?? ""

        #expect(bodyText.contains("name=\"timestamp_ms\""))
        #expect(bodyText.contains("name=\"duration_ms\""))
        #expect(bodyText.contains("name=\"trigger_segment_id\""))
        #expect(bodyText.contains("name=\"frames_total\""))
        #expect(bodyText.contains("name=\"frames_with_faces\""))
        #expect(bodyText.contains("name=\"masking_confirmed\""))
        #expect(bodyText.contains("name=\"clip\"; filename=\"clip.mp4\""))
        #expect(bodyText.contains("Content-Type: video/mp4"))
        #expect(bodyText.contains("\r\n14500\r\n"))
        #expect(bodyText.contains("\r\n7000\r\n"))
        #expect(bodyText.contains("\r\nseg_motion_001\r\n"))
        #expect(bodyText.contains("\r\ntrue\r\n"))

        // Closing boundary at end of file. Parse the actual boundary
        // from the request's Content-Type so the assertion stays
        // robust to UUID changes between runs.
        if let boundary = contentType.split(separator: "boundary=").last.map({ String($0) }) {
            #expect(bodyText.hasSuffix("--\(boundary)--\r\n"))
        }
    }

    @Test func prepareClipUpload_omitsAuthorizationHeader_whenNoToken() throws {
        let fakeClipURL = URL(fileURLWithPath: NSTemporaryDirectory())
            .appendingPathComponent("aurion-fake-clip-\(UUID().uuidString).mp4")
        try Data(repeating: 0xAB, count: 16).write(to: fakeClipURL)
        defer { try? FileManager.default.removeItem(at: fakeClipURL) }

        let prepared = try APIClient.prepareClipUpload(
            baseURL: "http://localhost:8080/api/v1",
            sessionId: "sess-2",
            clipFileURL: fakeClipURL,
            timestampMs: 1,
            durationMs: 7_000,
            triggerSegmentId: "seg_002",
            framesTotal: 1,
            framesWithFaces: 0,
            authToken: nil
        )
        defer { try? FileManager.default.removeItem(at: prepared.bodyFileURL) }
        #expect(prepared.request.value(forHTTPHeaderField: "Authorization") == nil)
    }
}

// MARK: - VisualEvidenceMode raw values

struct VisualEvidenceModeTests {

    @Test func rawValues_matchBackendEnum() {
        // The iOS enum mirrors the backend's `VisualEvidenceMode` —
        // raw values must stay in sync so AppConfig wire decoding
        // works in both directions.
        #expect(VisualEvidenceMode.framesOnly.rawValue == "frames_only")
        #expect(VisualEvidenceMode.clipsOnly.rawValue == "clips_only")
        #expect(VisualEvidenceMode.hybrid.rawValue == "hybrid")
    }

    @Test func clientPipelineResponse_decodesWithMissingDualModeKeys_usingSafeDefaults() throws {
        // A backend that hasn't shipped the P1-1 dual-mode keys yet
        // emits the legacy pipeline shape. The iOS client must decode
        // it without error and use the safe `framesOnly` default.
        let legacyJSON = """
        {
            "stage1_skip_window_seconds": 60,
            "frame_window_clinic_ms": 3000,
            "frame_window_procedural_ms": 7000,
            "screen_capture_fps": 2,
            "video_capture_fps": 1
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode(ClientPipelineResponse.self, from: legacyJSON)
        #expect(decoded.visualEvidenceMode == .framesOnly)
        #expect(decoded.clipWindowMs == 7_000)
        #expect(decoded.clipTriggerKinds == ["motion", "rom", "gait", "procedural"])
    }

    @Test func clientPipelineResponse_decodesDualModeKeys() throws {
        let json = """
        {
            "stage1_skip_window_seconds": 60,
            "frame_window_clinic_ms": 3000,
            "frame_window_procedural_ms": 7000,
            "screen_capture_fps": 2,
            "video_capture_fps": 1,
            "visual_evidence_mode": "hybrid",
            "clip_window_ms": 5000,
            "clip_trigger_kinds": ["motion", "rom"]
        }
        """.data(using: .utf8)!

        let decoded = try JSONDecoder().decode(ClientPipelineResponse.self, from: json)
        #expect(decoded.visualEvidenceMode == .hybrid)
        #expect(decoded.clipWindowMs == 5_000)
        #expect(decoded.clipTriggerKinds == ["motion", "rom"])
    }
}
