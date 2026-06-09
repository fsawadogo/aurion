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

import Foundation
import Testing
@testable import Aurion

struct ClipPipelineTelemetryTests {

    // MARK: - Wire-enum contract

    /// The raw values are the wire contract with the backend `ClipDropReason`
    /// in app/api/v1/clips.py. If either side renames a case, this pins the
    /// iOS side so the drift is caught in CI rather than at runtime (the
    /// backend rejects an unknown reason with a 422).
    @Test func dropReasonRawValuesMatchWire() {
        #expect(ClipDropReason.ringEmpty.rawValue == "ring_empty")
        #expect(ClipDropReason.maskingFailed.rawValue == "masking_failed")
        #expect(ClipDropReason.uploadFailed.rawValue == "upload_failed")
        #expect(ClipDropReason.cadenceSecondsZero.rawValue == "cadence_seconds_zero")
        #expect(ClipDropReason.modeNotClipsOrHybrid.rawValue == "mode_not_clips_or_hybrid")
        #expect(ClipDropReason.videoSourceNotBuiltin.rawValue == "video_source_not_builtin")
        #expect(ClipDropReason.captureModeNotMultimodal.rawValue == "capture_mode_not_multimodal")
    }

    /// iOS must never emit the server-only reason — there is no case for it.
    @Test func noServerOnlyReasonCase() {
        #expect(ClipDropReason(rawValue: "server_s3_put_failed") == nil)
    }

    // MARK: - Counters

    @Test func countersStartAtZero() {
        let c = ClipPipelineCounters()
        #expect(c.clipsExtracted == 0)
        #expect(c.clipsMasked == 0)
        #expect(c.clipsUploaded == 0)
        #expect(c.clipsDropped == 0)
    }

    @Test func clipsDroppedSumsAllReasons() {
        var c = ClipPipelineCounters()
        c.dropsRingEmpty = 3
        c.dropsMaskingFailed = 2
        c.dropsUploadFailed = 1
        #expect(c.clipsDropped == 6)
    }

    @Test func resetClearsEveryCounter() {
        var c = ClipPipelineCounters()
        c.clipsExtracted = 5
        c.clipsMasked = 4
        c.clipsUploaded = 4
        c.dropsRingEmpty = 1
        c.dropsMaskingFailed = 1
        c.dropsUploadFailed = 1
        c.reset()
        #expect(c.clipsExtracted == 0)
        #expect(c.clipsMasked == 0)
        #expect(c.clipsUploaded == 0)
        #expect(c.clipsDropped == 0)
    }

    // MARK: - summaryBody

    @Test func summaryBodyCarriesAllCountersAndKind() {
        var c = ClipPipelineCounters()
        c.clipsExtracted = 12
        c.clipsMasked = 11
        c.clipsUploaded = 10
        c.dropsRingEmpty = 1
        c.dropsMaskingFailed = 1
        c.dropsUploadFailed = 0

        let body = c.summaryBody(ringFramesAppended: 240)

        #expect(body["kind"] as? String == "summary")
        #expect(body["clips_extracted"] as? Int == 12)
        #expect(body["clips_masked"] as? Int == 11)
        #expect(body["clips_uploaded"] as? Int == 10)
        #expect(body["clips_dropped"] as? Int == 2)   // 1 + 1 + 0
        #expect(body["drops_ring_empty"] as? Int == 1)
        #expect(body["drops_masking_failed"] as? Int == 1)
        #expect(body["drops_upload_failed"] as? Int == 0)
        #expect(body["ring_frames_appended"] as? Int == 240)
    }

    /// Audio-only sessions have no video ring, so ringFramesAppended is nil
    /// and the key must be ABSENT (not null) — the backend whitelist accepts
    /// a subset, and a null would be a needless field.
    @Test func summaryBodyOmitsRingFramesWhenNil() {
        let body = ClipPipelineCounters().summaryBody(ringFramesAppended: nil)
        #expect(body["ring_frames_appended"] == nil)
        // The counter keys are still present (all zero).
        #expect(body["clips_uploaded"] as? Int == 0)
        #expect(body["clips_dropped"] as? Int == 0)
    }
}
