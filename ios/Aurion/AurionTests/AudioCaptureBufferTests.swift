//
//  AudioCaptureBufferTests.swift
//  AurionTests
//
//  #281 — the capture-active gate that makes PAUSE actually stop recording.
//  Before this, mic PCM was appended unconditionally, so paused (and
//  pre-start / post-stop) audio leaked into the uploaded WAV.
//
//  Locked behavior of AudioCaptureBuffer:
//    - append before activate() is dropped (no pre-start leak)
//    - append while active accumulates
//    - append while deactivated (paused/stopped) is a no-op
//    - reactivate (resume) continues appending, preserving prior bytes
//    - reset() clears bytes and deactivates
//

import Foundation
import Testing
@testable import Aurion

struct AudioCaptureBufferTests {

    private func pcm(_ n: Int) -> Data { Data(repeating: 0xAB, count: n) }

    // AC-1 — pre-start buffers don't leak.
    @Test func dropsBeforeActivate() {
        let buf = AudioCaptureBuffer()
        buf.append(pcm(100))
        #expect(buf.byteCount == 0)
        #expect(buf.snapshot().isEmpty)
    }

    // AC-2 — accumulates while active.
    @Test func accumulatesWhenActive() {
        let buf = AudioCaptureBuffer()
        buf.activate()
        buf.append(pcm(100))
        buf.append(pcm(50))
        #expect(buf.byteCount == 150)
    }

    // AC-3 — THE FIX: paused appends are a no-op.
    @Test func pauseStopsAppending() {
        let buf = AudioCaptureBuffer()
        buf.activate()
        buf.append(pcm(100))
        buf.deactivate()                 // pause
        buf.append(pcm(9999))            // would have leaked before the fix
        #expect(buf.byteCount == 100, "paused audio must not be recorded")
    }

    // AC-4 — resume continues, preserving pre-pause bytes.
    @Test func resumeContinues() {
        let buf = AudioCaptureBuffer()
        buf.activate()
        buf.append(pcm(100))
        buf.deactivate()
        buf.append(pcm(500))             // dropped (paused)
        buf.activate()                   // resume
        buf.append(pcm(40))
        #expect(buf.byteCount == 140)
    }

    // AC-5 — reset clears and deactivates.
    @Test func resetClears() {
        let buf = AudioCaptureBuffer()
        buf.activate()
        buf.append(pcm(100))
        buf.reset()
        #expect(buf.byteCount == 0)
        // reset also deactivates → a subsequent append without re-activating
        // is dropped.
        buf.append(pcm(100))
        #expect(buf.byteCount == 0)
    }

    @Test func snapshotReturnsAccumulatedBytes() {
        let buf = AudioCaptureBuffer()
        buf.activate()
        buf.append(pcm(64))
        #expect(buf.snapshot().count == 64)
    }
}
