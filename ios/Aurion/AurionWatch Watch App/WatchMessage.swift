import Foundation

/// #65 — message shapes exchanged between the iPhone app and the
/// `AurionWatch` companion over WatchConnectivity.
///
/// ⚠️ DUPLICATED, BY DESIGN. Two byte-identical copies exist — one per
/// target, because the iOS app and the watch app are separate modules
/// with no shared framework:
///   • iOS:   Aurion/Watch/WatchMessage.swift           (Aurion target)
///   • watch: AurionWatch Watch App/WatchMessage.swift  (AurionWatch target)
/// They are the WCSession wire contract — keep them IDENTICAL. Any change
/// to a key, raw value, or field must land in BOTH copies, or the two
/// sides will silently fail to decode each other. (The iOS copy is
/// unit-tested in AurionTests/WatchCompanionTests.swift.) Imports only
/// Foundation — no UIKit/WatchKit — so it compiles unchanged on watchOS.
///
/// PRIVACY (CLAUDE.md §Privacy): every field here is a non-PHI control
/// value — a session-state string, a consent-method enum, a consent bool,
/// a wall-clock anchor, and a stop-eligibility bool. NO transcript, note,
/// patient identifier, specialty-as-PHI, or frames ever cross this link.
/// The watch is a control surface only.

// MARK: - Watch → phone

/// A control intent the watch sends to drive the phone's session state
/// machine. The watch never mutates state itself — it asks the phone,
/// which runs the same `SessionManager` path (and audit log) a phone tap
/// would. `.confirmConsent` does NOT bypass the consent gate; it triggers
/// the phone's `confirmConsent`, which writes the consent audit event.
public enum WatchCommand: String, Codable, Sendable {
    case confirmConsent
    case start
    case pause
    case resume
    case stop
}

/// Envelope for a watch → phone command. `consentMethod` is populated
/// only for `.confirmConsent` (one of `ConsentMethod.rawValue` —
/// `verbal` / `paper_form` / `digital_form`); nil for every other command.
public struct WatchCommandMessage: Codable, Sendable {
    public let command: WatchCommand
    public let consentMethod: String?

    public init(command: WatchCommand, consentMethod: String? = nil) {
        self.command = command
        self.consentMethod = consentMethod
    }

    /// WatchConnectivity payloads are `[String: Any]` plist dictionaries.
    /// Encode/decode through a tiny dictionary representation so both
    /// sides avoid hand-rolling key strings.
    public func asDictionary() -> [String: Any] {
        var dict: [String: Any] = ["command": command.rawValue]
        if let consentMethod { dict["consentMethod"] = consentMethod }
        return dict
    }

    public init?(dictionary: [String: Any]) {
        guard let raw = dictionary["command"] as? String,
              let command = WatchCommand(rawValue: raw) else { return nil }
        self.command = command
        self.consentMethod = dictionary["consentMethod"] as? String
    }
}

// MARK: - phone → watch (applicationContext)

/// The latest session snapshot the phone publishes to the watch via
/// `updateApplicationContext` on every state transition + on activation.
/// Latest-wins and survives disconnect, so the watch always sees the
/// freshest control state on reconnect/launch.
public struct WatchSessionState: Codable, Sendable, Equatable {
    /// `SessionState.rawValue` (IDLE / CONSENT_PENDING / RECORDING / …),
    /// or nil when there is no active session on the phone.
    public let state: String?
    public let consentConfirmed: Bool
    /// Wall-clock epoch (seconds) when recording began — the anchor the
    /// watch uses to render a smooth local elapsed timer without a
    /// message per second. Nil when not recording.
    public let startedAtEpoch: Double?
    /// Mirrors the phone's minimum-recording-duration gate so the watch
    /// can't stop a session before the first audio buffers land.
    public let canStop: Bool

    public init(
        state: String?,
        consentConfirmed: Bool,
        startedAtEpoch: Double?,
        canStop: Bool
    ) {
        self.state = state
        self.consentConfirmed = consentConfirmed
        self.startedAtEpoch = startedAtEpoch
        self.canStop = canStop
    }

    /// The "no active session" snapshot — what the phone publishes when
    /// it returns to idle, and the watch's default before first sync.
    public static let idle = WatchSessionState(
        state: nil, consentConfirmed: false, startedAtEpoch: nil, canStop: false
    )

    public func asDictionary() -> [String: Any] {
        var dict: [String: Any] = ["consentConfirmed": consentConfirmed, "canStop": canStop]
        if let state { dict["state"] = state }
        if let startedAtEpoch { dict["startedAtEpoch"] = startedAtEpoch }
        return dict
    }

    public init(dictionary: [String: Any]) {
        self.state = dictionary["state"] as? String
        self.consentConfirmed = dictionary["consentConfirmed"] as? Bool ?? false
        self.startedAtEpoch = dictionary["startedAtEpoch"] as? Double
        self.canStop = dictionary["canStop"] as? Bool ?? false
    }
}

// MARK: - Haptic cue (phone → watch, transient)

/// A transient haptic the phone asks the watch to play on a transition.
/// Fire-and-forget; the watch ALSO derives haptics from state deltas it
/// observes locally (see the watch client), so a dropped cue still feels
/// right. Raw values map to `WKHapticType` on the watch side without the
/// shared file needing to import WatchKit.
public enum WatchHapticCue: String, Codable, Sendable {
    case consentConfirmed
    case recordingStarted
    case paused
    case resumed
    case stopped
    case linkLost
}
