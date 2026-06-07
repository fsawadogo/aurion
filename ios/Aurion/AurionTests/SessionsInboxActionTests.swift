//
//  SessionsInboxActionTests.swift
//  AurionTests
//
//  #276 — the inbox row's trailing affordance + tap target must match the
//  session state. A gold "Resume" pill must appear ONLY on genuinely
//  resumable capture states (which route back into CaptureView), never on
//  AWAITING_REVIEW or PROCESSING (which were mislabeled "Resume" and always
//  opened the note view).
//
//  Locked behavior of SessionsInboxView.rowAction(for:):
//    - RECORDING / PAUSED      → .resume  (→ adoptSession → CaptureView)
//    - AWAITING_REVIEW         → .review  (→ SessionNoteView)
//    - PROCESSING_STAGE1/2     → .status  (non-actionable, → note read-only)
//    - REVIEW_COMPLETE/EXPORTED/PURGED → .status
//

import Foundation
import Testing
@testable import Aurion

struct SessionsInboxActionTests {

    // AC-1 — active capture states resume into the recording screen.
    @Test func recordingAndPausedResume() {
        #expect(SessionsInboxView.rowAction(for: "RECORDING") == .resume)
        #expect(SessionsInboxView.rowAction(for: "PAUSED") == .resume)
    }

    // AC-2 — AWAITING_REVIEW reviews the note (was mislabeled "Resume").
    @Test func awaitingReviewReviews() {
        #expect(SessionsInboxView.rowAction(for: "AWAITING_REVIEW") == .review)
    }

    // AC-3 — processing states are non-actionable status, NOT "Resume".
    @Test func processingIsStatusNotResume() {
        #expect(SessionsInboxView.rowAction(for: "PROCESSING_STAGE1") == .status)
        #expect(SessionsInboxView.rowAction(for: "PROCESSING_STAGE2") == .status)
    }

    // AC-4 — terminal states are status.
    @Test func terminalStatesAreStatus() {
        for state in ["REVIEW_COMPLETE", "EXPORTED", "PURGED", "CONSENT_PENDING", "IDLE"] {
            #expect(SessionsInboxView.rowAction(for: state) == .status, "\(state) should be .status")
        }
    }
}
