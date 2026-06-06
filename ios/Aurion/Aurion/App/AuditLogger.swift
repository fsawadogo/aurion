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

        // Fire-and-forget POST to backend
        Task {
            await sendAuditEvent(payload)
        }
    }

    private static func sendAuditEvent(_ payload: [String: String]) async {
        // Disabled: the backend has no /api/v1/audit/event endpoint
        // (every relevant lifecycle event is already written server-side
        // when the matching /sessions/* /notes/* call is processed —
        // see DynamoDB aurion-audit-log-dev). The 404 retry pattern from
        // this method was bursting WAF's RateLimitPerIP and causing
        // collateral 403s on legitimate /notes/{id}/stage1 polls.
        //
        // Restore once the backend exposes a typed /audit/event endpoint
        // (tracked: AUR-API-CLIENT-AUDIT).
        _ = payload
    }
}
