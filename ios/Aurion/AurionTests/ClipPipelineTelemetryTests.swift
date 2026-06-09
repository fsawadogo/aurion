//
//  ClipPipelineTelemetryTests.swift
//  AurionTests
//
//  #390: clip-pipeline drop-site telemetry.
//
//  Coverage (pure value types — no network / no SessionManager):
//   - ClipDropReason raw values stay byte-identical to the backend wire
//     enum (a drift would make the backend 422/400 the beacon).
//   - ClipPipelineCounters: per-outcome increments, the clipsDropped sum,
//     reset(), and the summaryBody dict shape (keys + ring-frames omission).
//

import XCTest
@testable import Aurion

final class ClipPipelineTelemetryTests: XCTestCase {

    // MARK: - Wire-enum contract

    /// The raw values are the wire contract with the backend `ClipDropReason`
    /// in app/api/v1/clips.py. If either side renames a case, this pins the
    /// iOS side so the drift is caught in CI rather than at runtime (the
    /// backend rejects an unknown reason with a 422).
    func testDropReasonRawValuesMatchWire() {
        XCTAssertEqual(ClipDropReason.ringEmpty.rawValue, "ring_empty")
        XCTAssertEqual(ClipDropReason.maskingFailed.rawValue, "masking_failed")
        XCTAssertEqual(ClipDropReason.uploadFailed.rawValue, "upload_failed")
        XCTAssertEqual(ClipDropReason.cadenceSecondsZero.rawValue, "cadence_seconds_zero")
        XCTAssertEqual(ClipDropReason.modeNotClipsOrHybrid.rawValue, "mode_not_clips_or_hybrid")
        XCTAssertEqual(ClipDropReason.videoSourceNotBuiltin.rawValue, "video_source_not_builtin")
        XCTAssertEqual(ClipDropReason.captureModeNotMultimodal.rawValue, "capture_mode_not_multimodal")
    }

    /// iOS must never emit the server-only reason — there is no case for it.
    func testNoServerOnlyReasonCase() {
        XCTAssertNil(ClipDropReason(rawValue: "server_s3_put_failed"))
    }

    // MARK: - Counters

    func testCountersStartAtZero() {
        let c = ClipPipelineCounters()
        XCTAssertEqual(c.clipsExtracted, 0)
        XCTAssertEqual(c.clipsMasked, 0)
        XCTAssertEqual(c.clipsUploaded, 0)
        XCTAssertEqual(c.clipsDropped, 0)
    }

    func testClipsDroppedSumsAllReasons() {
        var c = ClipPipelineCounters()
        c.dropsRingEmpty = 3
        c.dropsMaskingFailed = 2
        c.dropsUploadFailed = 1
        XCTAssertEqual(c.clipsDropped, 6)
    }

    func testResetClearsEveryCounter() {
        var c = ClipPipelineCounters()
        c.clipsExtracted = 5
        c.clipsMasked = 4
        c.clipsUploaded = 4
        c.dropsRingEmpty = 1
        c.dropsMaskingFailed = 1
        c.dropsUploadFailed = 1
        c.reset()
        XCTAssertEqual(c.clipsExtracted, 0)
        XCTAssertEqual(c.clipsMasked, 0)
        XCTAssertEqual(c.clipsUploaded, 0)
        XCTAssertEqual(c.clipsDropped, 0)
    }

    // MARK: - summaryBody

    func testSummaryBodyCarriesAllCountersAndKind() {
        var c = ClipPipelineCounters()
        c.clipsExtracted = 12
        c.clipsMasked = 11
        c.clipsUploaded = 10
        c.dropsRingEmpty = 1
        c.dropsMaskingFailed = 1
        c.dropsUploadFailed = 0

        let body = c.summaryBody(ringFramesAppended: 240)

        XCTAssertEqual(body["kind"] as? String, "summary")
        XCTAssertEqual(body["clips_extracted"] as? Int, 12)
        XCTAssertEqual(body["clips_masked"] as? Int, 11)
        XCTAssertEqual(body["clips_uploaded"] as? Int, 10)
        XCTAssertEqual(body["clips_dropped"] as? Int, 2)   // 1 + 1 + 0
        XCTAssertEqual(body["drops_ring_empty"] as? Int, 1)
        XCTAssertEqual(body["drops_masking_failed"] as? Int, 1)
        XCTAssertEqual(body["drops_upload_failed"] as? Int, 0)
        XCTAssertEqual(body["ring_frames_appended"] as? Int, 240)
    }

    /// Audio-only sessions have no video ring, so ringFramesAppended is nil
    /// and the key must be ABSENT (not null) — the backend whitelist accepts
    /// a subset, and a null would be a needless field.
    func testSummaryBodyOmitsRingFramesWhenNil() {
        let body = ClipPipelineCounters().summaryBody(ringFramesAppended: nil)
        XCTAssertNil(body["ring_frames_appended"])
        // The counter keys are still present (all zero).
        XCTAssertEqual(body["clips_uploaded"] as? Int, 0)
        XCTAssertEqual(body["clips_dropped"] as? Int, 0)
    }
}
