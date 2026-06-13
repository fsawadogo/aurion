//
//  VideoClipSourceTests.swift
//  AurionTests
//
//  #440 — the VideoClipSource protocol generalizes the clip pipeline so any
//  video source (not just the iPhone camera) can feed masking + upload. These
//  prove the protocol is satisfiable by a non-iPhone source (the shape the
//  Meta-glasses source #443 will adopt) and that the `as? VideoClipSource`
//  casts SessionManager now uses resolve as expected. BuiltInCaptureSource's
//  own conformance is enforced at compile time by its declaration.
//

import AVFoundation
import Foundation
import Testing
@testable import Aurion

/// A minimal external clip source — owns its own ring, no AVCaptureSession.
/// Mirrors how MetaWearablesSource (#443) will conform without the iPhone
/// camera machinery.
@MainActor
private final class MockClipSource: CaptureSource, VideoClipSource {
    override var id: String { "mock-clip" }
    override var capabilities: CaptureCapability { [.video] }

    let ring = VideoRingBuffer(maxItems: 5, captureFPS: 1.0)
    var clipRingBuffer: VideoRingBuffer { ring }
    func extractCadenceClip(windowMs: Int) async -> (url: URL, timestampMs: Int)? { nil }
    func applyPipelineConfig(videoCaptureFPS: Double, clipWindowMs: Int) {}
}

@MainActor
struct VideoClipSourceTests {

    @Test func externalSource_conformsAndCastsAsVideoClipSource() {
        // SessionManager's cadence gate / emit / submit paths all do
        // `activeVideoSource as? VideoClipSource`; prove a non-iPhone source
        // resolves through that cast and exposes its ring.
        let source: CaptureSource = MockClipSource()
        #expect(source is VideoClipSource)
        let clip = source as? VideoClipSource
        #expect(clip != nil)
        #expect(clip?.clipRingBuffer.count == 0)
    }

    @Test func plainCaptureSource_doesNotConform() {
        // A non-clip source (e.g. a future BLE/audio-only source) must NOT pass
        // the cadence gate's `is VideoClipSource` check — clips would have no
        // ring to extract from.
        let plain = CaptureSource()
        #expect((plain as? VideoClipSource) == nil)
    }

    @Test func externalSource_feedsItsRingViaPixelBuffer() {
        // End-to-end shape: an external source appends decoded frames to the
        // ring it exposes through the protocol.
        let source = MockClipSource()
        var pixelBuffer: CVPixelBuffer?
        CVPixelBufferCreate(
            kCFAllocatorDefault, 16, 16, kCVPixelFormatType_32BGRA, nil, &pixelBuffer
        )
        #expect(pixelBuffer != nil)
        source.clipRingBuffer.append(pixelBuffer!, at: 0)
        #expect(source.clipRingBuffer.count == 1)
    }
}
