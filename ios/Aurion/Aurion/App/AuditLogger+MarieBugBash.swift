import Foundation
import UIKit

/// Audit events introduced by `lane-ios/marie-bug-bash-ux` that don't fit
/// cleanly into a typed `AuditEvent` case yet. Adding raw event strings
/// here keeps PR #243's `AuditLogger.swift` (audio-upload-resilience)
/// untouched while still letting this lane emit:
///
///   * `stage1_ws_fallback_to_poll` — the Stage 1 WebSocket channel went
///     down so the client fell back to polling `GET /notes/{id}/stage1`
///     with a 5-min deadline. Lets the backend tell — from the audit
///     trail alone — whether long Stage 1 latencies came from a slow
///     pipeline or from a flaky push channel forcing a fallback.
///   * `voice_enrollment_sentence_rejected_low_quality` — the on-device
///     quality gate (duration ≥ 2s, mean dBFS > -45) rejected a sentence
///     window. Payload carries the numeric thresholds + observed values
///     so we can tune the gate post-pilot. **No PHI** — the raw audio is
///     never inspected by anything past the meter, and audio levels +
///     durations don't carry patient content.
///
/// Once these events graduate to typed `AuditEvent` cases (post-PR #243
/// merge, when there's no longer a lane conflict on AuditLogger.swift),
/// this file can collapse back into the enum.
extension AuditLogger {
    /// Fire-and-forget audit log with a raw event-type string. Mirrors
    /// the shape of `AuditLogger.log(event:sessionId:extra:)` so the
    /// backend audit ingester sees identical payload semantics.
    static func logRaw(
        eventType: String,
        sessionId: String? = nil,
        extra: [String: String] = [:]
    ) {
        var payload: [String: String] = [
            "event_type": eventType,
            "timestamp": ISO8601DateFormatter().string(from: Date()),
            "device_id": UIDevice.current.identifierForVendor?.uuidString ?? "unknown",
        ]
        if let sid = sessionId {
            payload["session_id"] = sid
        }
        payload.merge(extra) { _, new in new }

        // Local-only for now — mirrors AuditLogger.sendAuditEvent which
        // is disabled until the backend exposes `/api/v1/audit/event`.
        // See AuditLogger.swift for the rationale (AUR-API-CLIENT-AUDIT).
        #if DEBUG
        print("[AUDIT] \(payload)")
        #endif
    }
}
