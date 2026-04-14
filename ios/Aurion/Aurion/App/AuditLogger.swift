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
    case deviceFailover = "device_failover"
    case noteApproved = "note_approved"
    case noteExported = "note_exported"
    case appCrashDetected = "app_crash_detected"
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
        guard let url = URL(string: "\(AppConfig.baseAPIPath)/audit/event") else { return }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try? JSONEncoder().encode(payload)
        _ = try? await URLSession.shared.data(for: request)
    }
}
