import Foundation
import UIKit

/// Client-side audit event logger.
/// Sends audit events to the backend — never contains PHI or embedding data.
enum AuditEvent: String {
    case voiceEnrollmentComplete = "voice_enrollment_complete"
    case voiceEnrollmentSkipped = "voice_enrollment_skipped"
    case biometricConsentConfirmed = "biometric_consent_confirmed"
    case voiceProfileDeleted = "voice_profile_deleted"
    case voiceProfileUpdated = "voice_profile_updated"
    case sessionCreated = "session_created"
    case consentConfirmed = "consent_confirmed"
    case recordingStarted = "recording_started"
    case sessionPaused = "session_paused"
    case sessionResumed = "session_resumed"
    case recordingStopped = "recording_stopped"
    case maskingConfirmed = "masking_confirmed"
    case maskingFailed = "masking_failed"
    case maskingFailureRetried = "masking_failure_retried"
    case maskingFailureSkipped = "masking_failure_skipped"
    case stage1Timeout = "stage1_timeout"
    case stage1Failed = "stage1_failed"
    case stage1Retried = "stage1_retried"
    case deviceFailover = "device_failover"
    case conflictResolved = "conflict_resolved"
    // #322 — note-review re-entry / deferral. The backend has no "saved"
    // state (a saved-for-later session stays AWAITING_REVIEW), so these
    // are iOS-side breadcrumbs marking when the physician re-opened the
    // approve-capable review flow vs. backed out to the inbox without
    // approving. No PHI: only the session id rides along.
    case noteReviewResumed = "note_review_resumed"
    case noteReviewDeferred = "note_review_deferred"
    case noteApproved = "note_approved"
    case noteExported = "note_exported"
    case localDataPurged = "local_data_purged"
    case appCrashDetected = "app_crash_detected"
    case audioQueuedOffline = "audio_queued_offline"
    case offlineUploadSynced = "offline_upload_synced"
    // MARK: - Audio upload chain (lane-ios/audio-upload-resilience)
    //
    // Granular events so we can tell *where* an upload failed from the
    // backend audit trail alone. Before this lane, a failed upload showed
    // up as "session_created → consent_confirmed → recording_started"
    // and then silence — we couldn't distinguish "recorder buffer wasn't
    // finalized" from "network blip mid-POST" from "401". The new events
    // (and their `error_category` payload) make each failure mode legible
    // server-side.
    //
    // PHI-safety: only session_id, byte counts, attempt numbers, elapsed
    // ms, and a fixed-set `error_category` enum string cross the wire.
    // NEVER `error.localizedDescription` — URLError messages can echo
    // the request URL, which carries the session id.
    case recordingStopInitiated = "recording_stop_initiated"
    case recordingFileFinalized = "recording_file_finalized"
    case recordingFinalizationFailed = "recording_finalization_failed"
    case audioUploadStarted = "audio_upload_started"
    case audioUploadProgress = "audio_upload_progress"
    case audioUploadSucceeded = "audio_upload_succeeded"
    case audioUploadFailed = "audio_upload_failed"
}

struct AuditLogger {
    /// Events iOS is the SOLE authority for and the backend does NOT already
    /// emit from the matching API call — the only ones worth transmitting
    /// (everything else is written server-side when the corresponding
    /// /sessions/* · /notes/* call is processed, and posting them would only
    /// duplicate rows). Scoped to the masking FAILURE family: a frame that
    /// fails masking is dropped fail-closed and never uploaded, so the server
    /// otherwise has NO record it existed — the compliance gap
    /// AUR-API-CLIENT-AUDIT closes. Mirrors the backend `CLIENT_AUDIT_EVENTS`
    /// allow-list; the endpoint rejects anything outside it with 422.
    /// Per-event field allow-list, mirroring the backend
    /// `ALLOWED_AUDIT_KWARGS`. The transmitted payload is FILTERED to these
    /// keys so a granular on-device debug key (e.g. the clip pipeline's
    /// per-stage `writer_final_status` detail) can't trip the endpoint's
    /// unknown-field 422 and *lose* the compliance row. The dropped keys
    /// still appear in the local #DEBUG log — they're just debug-grade, not
    /// the compliance signal (`failure_reason` + counts carry that).
    private static let transmittableFields: [AuditEvent: Set<String>] = [
        .maskingFailed: [
            "frame_type", "failure_reason", "faces_detected",
            "phi_regions_redacted", "frames_total", "frames_with_faces",
            "frames_failed",
        ],
        .maskingFailureRetried: ["frame_count"],
        .maskingFailureSkipped: ["frame_count"],
    ]

    static func log(event: AuditEvent, sessionId: String? = nil, extra: [String: String] = [:]) {
        var payload: [String: String] = [
            "event_type": event.rawValue,
            "timestamp": ISO8601DateFormatter().string(from: Date()),
            "device_id": UIDevice.current.identifierForVendor?.uuidString ?? "unknown",
        ]
        if let sid = sessionId {
            payload["session_id"] = sid
        }
        payload.merge(extra) { _, new in new }

        // In production, send to backend API
        // For now, log locally
        #if DEBUG
        print("[AUDIT] \(payload)")
        #endif

        // Transmit only the client-authoritative subset, and only when
        // session-scoped (the endpoint lives under /sessions/{id}). Fire-
        // and-forget; failures are swallowed (best-effort provenance, never
        // retried — that retry storm is what disabled the old sender).
        guard let allowed = transmittableFields[event], let sid = sessionId else { return }
        let fields = extra.filter { allowed.contains($0.key) }
        Task {
            try? await APIClient.shared.postClientAuditEvent(
                sessionId: sid,
                eventType: event.rawValue,
                fields: fields
            )
        }
    }
}
