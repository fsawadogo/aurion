import Foundation
import Combine

/// How the physician wants Aurion to capture this encounter. The value is
/// chosen at session start (per-session, not per-profile — common case is
/// the same physician switching modes between visits) and surfaced on the
/// capture screen as a pill so the physician can confirm at a glance.
///
/// Behavior:
/// - `multimodal`  — full audio + video; vision pipeline runs Stage 2.
/// - `audioOnly`   — audio capture only; video stream suppressed.
/// - `smartDictation` — audio + live caption-forward UI; intended for short
///                      free-form dictations rather than ambient encounters.
///
/// Backend currently treats all three as a session — the capture-mode value
/// is iOS-side state today; if/when the backend wants per-mode behavior we
/// add a `capture_mode` column and pass it through `POST /sessions`.
enum CaptureMode: String, Codable, CaseIterable, Identifiable {
    case multimodal
    case audioOnly = "audio_only"
    case smartDictation = "smart_dictation"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .multimodal: return L("captureMode.multimodal.title")
        case .audioOnly: return L("captureMode.audioOnly.title")
        case .smartDictation: return L("captureMode.smartDictation.title")
        }
    }

    var subtitle: String {
        switch self {
        case .multimodal: return L("captureMode.multimodal.sub")
        case .audioOnly: return L("captureMode.audioOnly.sub")
        case .smartDictation: return L("captureMode.smartDictation.sub")
        }
    }

    var icon: String {
        switch self {
        case .multimodal: return "video.and.waveform"
        case .audioOnly: return "waveform"
        case .smartDictation: return "text.viewfinder"
        }
    }

    /// Whether this mode runs the camera. audioOnly/smartDictation must
    /// not light the LED — checked at the CaptureManager input level.
    var includesVideo: Bool {
        self == .multimodal
    }

    /// Whether this mode is *eligible* for screen capture. The actual
    /// runtime gate also requires the `screen_capture_enabled` feature
    /// flag (RemoteConfig) — eligibility alone isn't enough.
    var includesScreen: Bool {
        self == .multimodal
    }
}

/// How the patient gave consent for this session. Selected by the
/// clinician at consent-confirmation time; flows into the audit log so
/// compliance can prove the method per session.
enum ConsentMethod: String, Codable, CaseIterable, Identifiable {
    case verbal
    case paperForm = "paper_form"
    case digitalForm = "digital_form"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .verbal: return L("consentMethod.verbal")
        case .paperForm: return L("consentMethod.paperForm")
        case .digitalForm: return L("consentMethod.digitalForm")
        }
    }

    var icon: String {
        switch self {
        case .verbal: return "mic.fill"
        case .paperForm: return "doc.text.fill"
        case .digitalForm: return "iphone.gen3"
        }
    }
}

/// One non-physician participant in a collaborative encounter — nurse, PA,
/// resident, fellow, or student. The capture screen renders names so every
/// person in the room sees themselves on the shared encounter pill.
struct SessionParticipant: Identifiable, Hashable {
    let name: String
    let role: String
    var id: String { "\(role)-\(name)" }

    /// Title-cased role label for UI display ("nurse" → "Nurse").
    var displayRole: String {
        role
            .replacingOccurrences(of: "_", with: " ")
            .split(separator: " ")
            .map { $0.prefix(1).uppercased() + $0.dropFirst() }
            .joined(separator: " ")
    }
}

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
    /// Chosen at session start; defaults to `.multimodal`. Read by `CaptureView`
    /// to render the mode pill and (eventually) by `CaptureManager` to suppress
    /// the video stream when the physician picks an audio-only mode.
    let captureMode: CaptureMode
    /// Encounter shape selected on the start sheet — one of the three
    /// participant combinations (#321), keyed on whether the attending
    /// physician is present:
    /// - `doctor_patient`        — attending + patient (standard 1:1).
    /// - `doctor_team_patient`   — attending + team member(s) + patient.
    /// - `team_patient`          — team member(s) + patient, attending absent.
    /// Free-form on the wire (`POST /sessions` `encounter_type` is an open
    /// `str` column). Used by `CaptureView` to render the shared-encounter
    /// pill when the room includes more than the physician.
    let encounterType: String
    /// Non-physician collaborators in the same encounter. Empty for
    /// `doctor_patient`. Surfaced on the capture screen so everyone present
    /// sees their name on the shared-encounter pill.
    let participants: [SessionParticipant]
    @Published var state: SessionState = .consentPending
    @Published var consentMethod: ConsentMethod?
    @Published var consentConfirmedAt: Date?
    @Published var pausedAt: Date?
    @Published var isPauseExpired = false
    /// Patient identifier (#61). Set / cleared by PatientIdentifierEditor
    /// in the post-encounter screen; the editor calls the backend
    /// PATCH route + writes back here on success. Stays nil until
    /// the physician chooses to set one. Never logged.
    @Published var externalReferenceId: String?
    /// Per-session provider routing overrides (P1-7). When set, the
    /// dispatcher reads `providerOverrides?.visualEvidenceMode` first
    /// before falling back to the AppConfig pipeline default. nil for
    /// sessions created with no overrides (the common case). Decoded
    /// from the backend SessionResponse at creation/adoption time.
    let providerOverrides: ProviderOverrides?

    /// Derived from the consent metadata so the three never desynchronize.
    /// Setting consent goes through `confirmConsent(method:)`; recovery
    /// paths assign a placeholder method + timestamp.
    var isConsentConfirmed: Bool { consentMethod != nil }

    /// Maximum pause duration before session times out (30 minutes)
    static let maxPauseDuration: TimeInterval = 1800

    var recordButtonEnabled: Bool {
        state == .recording || (state == .consentPending && isConsentConfirmed)
    }

    var pauseDuration: TimeInterval? {
        guard let pausedAt, state == .paused else { return nil }
        return Date().timeIntervalSince(pausedAt)
    }

    init(
        id: String = UUID().uuidString,
        specialty: String,
        captureMode: CaptureMode = .multimodal,
        encounterType: String = "doctor_patient",
        participants: [SessionParticipant] = [],
        externalReferenceId: String? = nil,
        providerOverrides: ProviderOverrides? = nil
    ) {
        self.id = id
        self.specialty = specialty
        self.captureMode = captureMode
        self.encounterType = encounterType
        self.participants = participants
        self.externalReferenceId = externalReferenceId
        self.providerOverrides = providerOverrides
    }

    /// `true` when there's more than just doctor + patient in the room —
    /// drives the shared-encounter pill on the capture screen.
    var isCollaborative: Bool {
        encounterType != "doctor_patient" || !participants.isEmpty
    }

    func confirmConsent(method: ConsentMethod) {
        guard state == .consentPending else { return }
        consentMethod = method
        consentConfirmedAt = Date()
        persist()
        AuditLogger.log(
            event: .consentConfirmed,
            sessionId: id,
            extra: ["consent_method": method.rawValue]
        )
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
        SessionPersistence.save(
            sessionId: id,
            specialty: specialty,
            state: state,
            consentMethod: consentMethod,
            consentConfirmedAt: consentConfirmedAt
        )
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
    private static let consentMethodKey = "aurion.active_session_consent_method"
    private static let consentAtKey = "aurion.active_session_consent_at"

    static func save(
        sessionId: String,
        specialty: String,
        state: SessionState,
        consentMethod: ConsentMethod?,
        consentConfirmedAt: Date?
    ) {
        guard state.isActive else {
            clear()
            return
        }
        UserDefaults.standard.set(sessionId, forKey: sessionIdKey)
        UserDefaults.standard.set(specialty, forKey: specialtyKey)
        UserDefaults.standard.set(state.rawValue, forKey: stateKey)
        UserDefaults.standard.set(consentMethod?.rawValue, forKey: consentMethodKey)
        UserDefaults.standard.set(consentConfirmedAt, forKey: consentAtKey)
    }

    static func clear() {
        UserDefaults.standard.removeObject(forKey: sessionIdKey)
        UserDefaults.standard.removeObject(forKey: specialtyKey)
        UserDefaults.standard.removeObject(forKey: stateKey)
        UserDefaults.standard.removeObject(forKey: consentMethodKey)
        UserDefaults.standard.removeObject(forKey: consentAtKey)
    }

    /// Restore a CaptureSession from persisted state. Recovered sessions
    /// must have had consent confirmed to reach an active state — if the
    /// persisted record is missing the method (older app version), we fall
    /// back to `.verbal` so the chip renders rather than going silent. The
    /// real consent event is still in the immutable audit log.
    @MainActor
    static func restore() -> CaptureSession? {
        guard let sessionId = UserDefaults.standard.string(forKey: sessionIdKey),
              let specialty = UserDefaults.standard.string(forKey: specialtyKey),
              let stateRaw = UserDefaults.standard.string(forKey: stateKey),
              let state = SessionState(rawValue: stateRaw),
              state.isActive else {
            return nil
        }
        let session = CaptureSession(id: sessionId, specialty: specialty)
        session.state = state

        let methodRaw = UserDefaults.standard.string(forKey: consentMethodKey)
        session.consentMethod = methodRaw.flatMap(ConsentMethod.init(rawValue:)) ?? .verbal
        session.consentConfirmedAt = UserDefaults.standard.object(forKey: consentAtKey) as? Date ?? Date()

        AuditLogger.log(event: .appCrashDetected, sessionId: sessionId,
                        extra: ["recovered_state": state.rawValue])
        return session
    }
}
