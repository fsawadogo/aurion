import Foundation
import Combine

/// 10-state session machine — mirrors backend exactly.
/// Every transition requires an audit log entry.
enum SessionState: String, Codable {
    case idle = "IDLE"
    case consentPending = "CONSENT_PENDING"
    case recording = "RECORDING"
    case paused = "PAUSED"
    case processingStage1 = "PROCESSING_STAGE1"
    case awaitingReview = "AWAITING_REVIEW"
    case processingStage2 = "PROCESSING_STAGE2"
    case reviewComplete = "REVIEW_COMPLETE"
    case exported = "EXPORTED"
    case purged = "PURGED"

    /// States that indicate an active (recoverable) session
    var isActive: Bool {
        switch self {
        case .recording, .paused, .processingStage1, .awaitingReview,
             .processingStage2, .reviewComplete:
            return true
        default:
            return false
        }
    }
}

/// Client-side session model with crash recovery persistence.
@MainActor
final class CaptureSession: ObservableObject, Identifiable {
    let id: String
    let specialty: String
    @Published var state: SessionState = .consentPending
    @Published var isConsentConfirmed = false
    @Published var pausedAt: Date?
    @Published var isPauseExpired = false

    /// Maximum pause duration before session times out (30 minutes)
    static let maxPauseDuration: TimeInterval = 1800

    var recordButtonEnabled: Bool {
        state == .recording || (state == .consentPending && isConsentConfirmed)
    }

    var pauseDuration: TimeInterval? {
        guard let pausedAt, state == .paused else { return nil }
        return Date().timeIntervalSince(pausedAt)
    }

    init(id: String = UUID().uuidString, specialty: String) {
        self.id = id
        self.specialty = specialty
    }

    func confirmConsent() {
        guard state == .consentPending else { return }
        isConsentConfirmed = true
        persist()
        AuditLogger.log(event: .consentConfirmed, sessionId: id)
    }

    func startRecording() {
        guard state == .consentPending && isConsentConfirmed || state == .paused else { return }
        state = .recording
        persist()
        AuditLogger.log(event: .recordingStarted, sessionId: id)
    }

    func pause() {
        guard state == .recording else { return }
        state = .paused
        pausedAt = Date()
        persist()
        AuditLogger.log(event: .sessionPaused, sessionId: id)
    }

    func resume() {
        guard state == .paused else { return }
        // Check pause duration limit
        if let pausedAt, Date().timeIntervalSince(pausedAt) > Self.maxPauseDuration {
            isPauseExpired = true
            AuditLogger.log(event: .recordingStopped, sessionId: id,
                            extra: ["reason": "pause_timeout"])
            return
        }
        pausedAt = nil
        state = .recording
        persist()
        AuditLogger.log(event: .sessionResumed, sessionId: id)
    }

    func stopRecording() {
        guard state == .recording || state == .paused else { return }
        state = .processingStage1
        persist()
        AuditLogger.log(event: .recordingStopped, sessionId: id)
    }

    // MARK: - Crash Recovery Persistence

    private func persist() {
        SessionPersistence.save(sessionId: id, specialty: specialty, state: state)
    }

    func clearPersistence() {
        SessionPersistence.clear()
    }
}

// MARK: - Session Persistence for Crash Recovery

/// Persists active session ID and state to UserDefaults.
/// On relaunch, the app checks for an incomplete session and offers recovery.
enum SessionPersistence {
    private static let sessionIdKey = "aurion.active_session_id"
    private static let specialtyKey = "aurion.active_session_specialty"
    private static let stateKey = "aurion.active_session_state"

    static func save(sessionId: String, specialty: String, state: SessionState) {
        if state.isActive {
            UserDefaults.standard.set(sessionId, forKey: sessionIdKey)
            UserDefaults.standard.set(specialty, forKey: specialtyKey)
            UserDefaults.standard.set(state.rawValue, forKey: stateKey)
        } else {
            // Session completed or purged — clear persistence
            clear()
        }
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: sessionIdKey)
        UserDefaults.standard.removeObject(forKey: specialtyKey)
        UserDefaults.standard.removeObject(forKey: stateKey)
    }

    /// Check if there's an incomplete session from a previous launch.
    static func recoverableSession() -> (id: String, specialty: String, state: SessionState)? {
        guard let sessionId = UserDefaults.standard.string(forKey: sessionIdKey),
              let specialty = UserDefaults.standard.string(forKey: specialtyKey),
              let stateRaw = UserDefaults.standard.string(forKey: stateKey),
              let state = SessionState(rawValue: stateRaw),
              state.isActive else {
            return nil
        }
        return (id: sessionId, specialty: specialty, state: state)
    }

    /// Restore a CaptureSession from persisted state.
    @MainActor
    static func restore() -> CaptureSession? {
        guard let saved = recoverableSession() else { return nil }
        let session = CaptureSession(id: saved.id, specialty: saved.specialty)
        session.state = saved.state
        session.isConsentConfirmed = true // Must have been confirmed to reach active states
        AuditLogger.log(event: .appCrashDetected, sessionId: saved.id,
                        extra: ["recovered_state": saved.state.rawValue])
        return session
    }
}
