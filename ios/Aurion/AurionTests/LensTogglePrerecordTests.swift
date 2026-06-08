//
//  LensTogglePrerecordTests.swift
//  AurionTests
//
//  #354 — the ultra-wide 0.5×/1× lens toggle is restricted to PRE-RECORD so it
//  can never reconfigure the live AVCaptureSession mid-recording. A
//  begin/commit input swap on a running session stalls ALL data flow —
//  including the audio output delegate — for the commit, dropping
//  tens-to-low-hundreds of ms of PCM. Audio is the spine, so a clipped word
//  degrades the transcript. These tests pin the pure session-state gate that
//  drives the toggle's visibility (`CaptureSession.isLensToggleAllowed`) and
//  the cached, once-resolved `ultraWideAvailable` lookup.
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct LensTogglePrerecordTests {

    private func session(in state: SessionState) -> CaptureSession {
        let s = CaptureSession(specialty: "orthopedic_surgery")
        s.state = state
        return s
    }

    /// The framing / consent gate is the one state that may offer the lens
    /// toggle — the physician sets 0.5×/1× before tapping record.
    @Test func lensToggleAllowed_inConsentPending() {
        #expect(session(in: .consentPending).isLensToggleAllowed)
    }

    @Test func lensToggleBlocked_whileRecording() {
        #expect(session(in: .recording).isLensToggleAllowed == false)
    }

    /// PAUSED is still wired to the live capture pipeline — a swap here would
    /// stall the audio output the moment recording resumes, so it stays locked.
    @Test func lensToggleBlocked_whilePaused() {
        #expect(session(in: .paused).isLensToggleAllowed == false)
    }

    /// Exhaustive: the gate is true for `.consentPending` and false for every
    /// other state in the 10-state machine.
    @Test func gate_isTrueOnlyForConsentPending() {
        let allStates: [SessionState] = [
            .idle, .consentPending, .recording, .paused, .processingStage1,
            .awaitingReview, .processingStage2, .reviewComplete, .exported, .purged,
        ]
        for state in allStates {
            let expected = (state == .consentPending)
            #expect(
                session(in: state).isLensToggleAllowed == expected,
                "isLensToggleAllowed for \(state.rawValue) should be \(expected)"
            )
        }
    }

    /// `ultraWideAvailable` is resolved once at init and stored (#354), so
    /// repeated reads return a stable value rather than re-hitting the
    /// AVCaptureDevice discovery registry on every CaptureView body pass.
    @Test func ultraWideAvailable_isStableAcrossReads() {
        let manager = CaptureManager()
        let first = manager.ultraWideAvailable
        let second = manager.ultraWideAvailable
        #expect(first == second)
    }
}
