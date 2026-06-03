//
//  SessionModeOverrideTests.swift
//  AurionTests
//
//  P1-7: per-session visual_evidence_mode override (vertical slice).
//
//  Coverage:
//   - `SessionManager.resolveEvidenceMode` returns the parsed session
//     override when set; falls back to the global default when nil,
//     empty, or unparseable.
//   - `ProviderOverrides` decodes from a snake-cased JSON payload as
//     the backend emits it.
//   - `SessionResponse` decodes `provider_overrides` as a structured
//     object (not a JSON string).
//

import AVFoundation
import CoreMedia
import CoreVideo
import Foundation
import Testing
@testable import Aurion

// MARK: - resolveEvidenceMode

struct ResolveEvidenceModeTests {

    @Test func sessionOverride_clipsOnly_winsOverGlobalFramesOnly() {
        let resolved = SessionManager.resolveEvidenceMode(
            sessionOverride: "clips_only",
            globalDefault: .framesOnly
        )
        #expect(resolved == .clipsOnly)
    }

    @Test func sessionOverride_hybrid_winsOverGlobalClipsOnly() {
        let resolved = SessionManager.resolveEvidenceMode(
            sessionOverride: "hybrid",
            globalDefault: .clipsOnly
        )
        #expect(resolved == .hybrid)
    }

    @Test func noOverride_returnsGlobalDefault() {
        let resolved = SessionManager.resolveEvidenceMode(
            sessionOverride: nil,
            globalDefault: .framesOnly
        )
        #expect(resolved == .framesOnly)
    }

    @Test func emptyStringOverride_returnsGlobalDefault() {
        let resolved = SessionManager.resolveEvidenceMode(
            sessionOverride: "",
            globalDefault: .clipsOnly
        )
        #expect(resolved == .clipsOnly)
    }

    /// Unparseable string falls through to the global default — must
    /// never crash the dispatcher. Mirrors the backend resolver's
    /// "invalid string → ValueError → caller falls back" contract:
    /// iOS swallows the error in-place because there is no second
    /// fallback layer on the device.
    @Test func unparseableOverride_returnsGlobalDefault() {
        let resolved = SessionManager.resolveEvidenceMode(
            sessionOverride: "not_a_real_mode",
            globalDefault: .framesOnly
        )
        #expect(resolved == .framesOnly)
    }

    @Test func resolverDoesNotMutateGlobalDefault() {
        // Sanity: calling the resolver doesn't change the input enum
        // state (Swift value type, but a regression check for future
        // refactors that might surprise the dispatcher).
        let global: VisualEvidenceMode = .framesOnly
        _ = SessionManager.resolveEvidenceMode(
            sessionOverride: "clips_only",
            globalDefault: global
        )
        #expect(global == .framesOnly)
    }
}

// MARK: - ProviderOverrides decode

struct ProviderOverridesDecodeTests {

    @Test func decodesFromSnakeCasedJSON() throws {
        let json = """
        {
            "visual_evidence_mode": "clips_only",
            "vision_clip": "gemini",
            "note_generation": "anthropic"
        }
        """.data(using: .utf8)!

        let overrides = try JSONDecoder().decode(ProviderOverrides.self, from: json)
        #expect(overrides.visualEvidenceMode == "clips_only")
        #expect(overrides.visionClip == "gemini")
        #expect(overrides.noteGeneration == "anthropic")
        #expect(overrides.vision == nil)
        #expect(overrides.transcription == nil)
    }

    @Test func decodesEmptyObject_allFieldsNil() throws {
        let json = "{}".data(using: .utf8)!
        let overrides = try JSONDecoder().decode(ProviderOverrides.self, from: json)
        #expect(overrides.visualEvidenceMode == nil)
        #expect(overrides.visionClip == nil)
        #expect(overrides.noteGeneration == nil)
        #expect(overrides.vision == nil)
        #expect(overrides.transcription == nil)
    }

    @Test func decodesAllFiveKeys() throws {
        let json = """
        {
            "transcription": "whisper",
            "note_generation": "openai",
            "vision": "anthropic",
            "vision_clip": "gemini",
            "visual_evidence_mode": "hybrid"
        }
        """.data(using: .utf8)!
        let overrides = try JSONDecoder().decode(ProviderOverrides.self, from: json)
        #expect(overrides.transcription == "whisper")
        #expect(overrides.noteGeneration == "openai")
        #expect(overrides.vision == "anthropic")
        #expect(overrides.visionClip == "gemini")
        #expect(overrides.visualEvidenceMode == "hybrid")
    }
}

// MARK: - SessionResponse decode (provider_overrides surface)

struct SessionResponseProviderOverridesDecodeTests {

    @Test func sessionResponse_decodesProviderOverrides_whenPresent() throws {
        let json = """
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "clinician_id": "11111111-1111-1111-1111-111111111111",
            "specialty": "orthopedic_surgery",
            "state": "CONSENT_PENDING",
            "encounter_type": "doctor_patient",
            "capture_mode": "multimodal",
            "external_reference_id": null,
            "provider_overrides": {
                "visual_evidence_mode": "clips_only"
            },
            "created_at": "2026-06-02T00:00:00Z",
            "updated_at": "2026-06-02T00:00:00Z"
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(SessionResponse.self, from: json)
        #expect(response.providerOverrides != nil)
        #expect(response.providerOverrides?.visualEvidenceMode == "clips_only")
    }

    @Test func sessionResponse_decodesNilProviderOverrides_whenAbsent() throws {
        // A backend that hasn't shipped P1-7 yet (or a session created
        // without overrides) omits the key. iOS must decode that
        // payload cleanly with `providerOverrides == nil`.
        let json = """
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "clinician_id": "22222222-2222-2222-2222-222222222222",
            "specialty": "orthopedic_surgery",
            "state": "CONSENT_PENDING",
            "encounter_type": "doctor_patient",
            "capture_mode": "multimodal",
            "external_reference_id": null,
            "created_at": "2026-06-02T00:00:00Z",
            "updated_at": "2026-06-02T00:00:00Z"
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(SessionResponse.self, from: json)
        #expect(response.providerOverrides == nil)
    }

    @Test func sessionResponse_decodesExplicitlyNullProviderOverrides() throws {
        let json = """
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "clinician_id": "33333333-3333-3333-3333-333333333333",
            "specialty": "orthopedic_surgery",
            "state": "CONSENT_PENDING",
            "encounter_type": "doctor_patient",
            "capture_mode": "multimodal",
            "external_reference_id": null,
            "provider_overrides": null,
            "created_at": "2026-06-02T00:00:00Z",
            "updated_at": "2026-06-02T00:00:00Z"
        }
        """.data(using: .utf8)!

        let response = try JSONDecoder().decode(SessionResponse.self, from: json)
        #expect(response.providerOverrides == nil)
    }
}

// MARK: - Dispatcher integration (session override flows into extractEvidence)

struct SessionOverrideDispatcherTests {

    /// `extractEvidence` is called with a mode that has been resolved
    /// from the session override. This test wires the resolver +
    /// dispatcher end-to-end on the values path the production code
    /// follows: `resolveEvidenceMode(sessionOverride:, globalDefault:)`
    /// → `extractEvidence(...:mode:)`. Confirms the override actually
    /// changes the evidence kind the dispatcher emits.
    @MainActor
    @Test func sessionOverride_clipsOnly_routesToClip_evenWhenGlobalFramesOnly() async throws {
        // Build a small ring buffer so the clipsOnly path can succeed.
        let ring = VideoRingBuffer(maxItems: 20, captureFPS: 10.0)
        for i in 0..<8 {
            guard let sb = Self.makeSyntheticSampleBuffer(width: 32, height: 32) else { return }
            ring.append(sb, at: 0.1 * Double(i))
        }

        let resolved = SessionManager.resolveEvidenceMode(
            sessionOverride: "clips_only",
            globalDefault: .framesOnly
        )
        #expect(resolved == .clipsOnly)

        let manager = SessionManager()
        let trigger = TriggerEvent(kind: "clinic", timestamp: 0.4, segmentId: "seg_p17_clip")
        let evidence = try await manager.extractEvidence(
            for: trigger,
            mode: resolved,
            clipWindowMs: 1_000,
            clipTriggerKinds: ["motion"],
            capturedFrame: CapturedFrame(timestamp: 0.4, imageData: Data([0xff])),
            ringBuffer: ring
        )

        switch evidence {
        case .clip(let url, _, _):
            #expect(FileManager.default.fileExists(atPath: url.path))
            try? FileManager.default.removeItem(at: url)
        case .frame:
            Issue.record("session override clips_only must route to .clip")
        }
    }

    @MainActor
    @Test func noSessionOverride_routesToGlobalDefaultFrame() async throws {
        let resolved = SessionManager.resolveEvidenceMode(
            sessionOverride: nil,
            globalDefault: .framesOnly
        )
        #expect(resolved == .framesOnly)

        let manager = SessionManager()
        let captured = CapturedFrame(timestamp: 0.8, imageData: Data([0xfe, 0xed]))
        let trigger = TriggerEvent(kind: "clinic", timestamp: 0.8, segmentId: "seg_p17_frame")
        let evidence = try await manager.extractEvidence(
            for: trigger,
            mode: resolved,
            clipWindowMs: 7_000,
            clipTriggerKinds: ["motion"],
            capturedFrame: captured,
            ringBuffer: nil
        )

        switch evidence {
        case .frame(let frame):
            #expect(frame.timestamp == 0.8)
        case .clip:
            Issue.record("no override + global framesOnly must route to .frame")
        }
    }

    @MainActor
    @Test func unparseableOverride_routesToGlobalDefault_fail_soft() async throws {
        // The dispatcher must NOT crash on a stale or future override
        // value the iOS build doesn't recognize. Resolver returns the
        // global default; dispatcher routes by it.
        let resolved = SessionManager.resolveEvidenceMode(
            sessionOverride: "unknown_future_mode",
            globalDefault: .framesOnly
        )
        #expect(resolved == .framesOnly)

        let manager = SessionManager()
        let captured = CapturedFrame(timestamp: 1.1, imageData: Data([0xff]))
        let trigger = TriggerEvent(kind: "clinic", timestamp: 1.1, segmentId: "seg_p17_unknown")
        let evidence = try await manager.extractEvidence(
            for: trigger,
            mode: resolved,
            clipWindowMs: 7_000,
            clipTriggerKinds: ["motion"],
            capturedFrame: captured,
            ringBuffer: nil
        )
        switch evidence {
        case .frame(let frame):
            #expect(frame.timestamp == 1.1)
        case .clip:
            Issue.record("unparseable override should fall back to global default (.framesOnly)")
        }
    }

    // MARK: helpers (mirror ClipDispatcherTests so each suite stays self-contained)

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
