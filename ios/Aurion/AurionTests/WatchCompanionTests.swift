//
//  WatchCompanionTests.swift
//  AurionTests
//
//  #65: Apple Watch companion — device-independent unit coverage for the
//  pieces that live in the iOS app target. (WCSession reachability +
//  haptics + the watch views require a paired device / the watchOS target
//  and are verified on-device per docs/plans/watch-companion.md §10.)
//
//  Coverage:
//   - WatchCommandMessage dictionary round-trip (incl. consentMethod
//     present/absent) and rejection of malformed input.
//   - WatchSessionState dictionary round-trip (incl. nil state /
//     startedAtEpoch and the defaulting on a sparse dictionary).
//   - WatchSessionBridge.hapticCue state-delta → cue mapping.
//

import Foundation
import Testing
@testable import Aurion

// MARK: - WatchCommandMessage

struct WatchCommandMessageTests {

    @Test func roundTrip_confirmConsent_carriesMethod() {
        let msg = WatchCommandMessage(command: .confirmConsent, consentMethod: "paper_form")
        let decoded = WatchCommandMessage(dictionary: msg.asDictionary())
        #expect(decoded?.command == .confirmConsent)
        #expect(decoded?.consentMethod == "paper_form")
    }

    @Test func roundTrip_plainCommand_hasNoMethod() {
        let msg = WatchCommandMessage(command: .start)
        let dict = msg.asDictionary()
        #expect(dict["consentMethod"] == nil)
        let decoded = WatchCommandMessage(dictionary: dict)
        #expect(decoded?.command == .start)
        #expect(decoded?.consentMethod == nil)
    }

    @Test func decode_rejectsMissingOrUnknownCommand() {
        #expect(WatchCommandMessage(dictionary: [:]) == nil)
        #expect(WatchCommandMessage(dictionary: ["command": "selfDestruct"]) == nil)
        #expect(WatchCommandMessage(dictionary: ["command": 42]) == nil)
    }

    @Test func everyCommand_roundTrips() {
        for command in [WatchCommand.confirmConsent, .start, .pause, .resume, .stop] {
            let decoded = WatchCommandMessage(
                dictionary: WatchCommandMessage(command: command).asDictionary()
            )
            #expect(decoded?.command == command)
        }
    }
}

// MARK: - WatchSessionState

struct WatchSessionStateTests {

    @Test func roundTrip_recording_preservesAllFields() {
        let state = WatchSessionState(
            state: "RECORDING",
            consentConfirmed: true,
            startedAtEpoch: 1_700_000_000.5,
            canStop: true
        )
        let decoded = WatchSessionState(dictionary: state.asDictionary())
        #expect(decoded == state)
    }

    @Test func roundTrip_idle_hasNilStateAndAnchor() {
        let decoded = WatchSessionState(dictionary: WatchSessionState.idle.asDictionary())
        #expect(decoded.state == nil)
        #expect(decoded.startedAtEpoch == nil)
        #expect(decoded.consentConfirmed == false)
        #expect(decoded.canStop == false)
    }

    @Test func decode_sparseDictionary_defaultsSafely() {
        // A dictionary missing the bool keys must not crash and must
        // default to the safe (false) values — never a spurious canStop.
        let decoded = WatchSessionState(dictionary: ["state": "PAUSED"])
        #expect(decoded.state == "PAUSED")
        #expect(decoded.consentConfirmed == false)
        #expect(decoded.canStop == false)
        #expect(decoded.startedAtEpoch == nil)
    }

    @Test func asDictionary_omitsNilStateAndAnchor() {
        let dict = WatchSessionState.idle.asDictionary()
        #expect(dict["state"] == nil)
        #expect(dict["startedAtEpoch"] == nil)
        // Bools are always present.
        #expect(dict["consentConfirmed"] as? Bool == false)
        #expect(dict["canStop"] as? Bool == false)
    }
}

// MARK: - Haptic cue mapping

struct WatchHapticCueTests {

    @Test func startFromConsent_isRecordingStarted() {
        #expect(WatchSessionBridge.hapticCue(from: "CONSENT_PENDING", to: "RECORDING") == .recordingStarted)
    }

    @Test func startFromPaused_isResumed() {
        #expect(WatchSessionBridge.hapticCue(from: "PAUSED", to: "RECORDING") == .resumed)
    }

    @Test func toPaused_isPaused() {
        #expect(WatchSessionBridge.hapticCue(from: "RECORDING", to: "PAUSED") == .paused)
    }

    @Test func toProcessing_isStopped() {
        #expect(WatchSessionBridge.hapticCue(from: "RECORDING", to: "PROCESSING_STAGE1") == .stopped)
    }

    @Test func noCueForUnremarkableTransitions() {
        #expect(WatchSessionBridge.hapticCue(from: nil, to: "CONSENT_PENDING") == nil)
        #expect(WatchSessionBridge.hapticCue(from: "AWAITING_REVIEW", to: "EXPORTED") == nil)
        #expect(WatchSessionBridge.hapticCue(from: "RECORDING", to: nil) == nil)
    }
}
