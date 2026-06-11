import Foundation
import Combine
import WatchConnectivity
import WatchKit

/// #65 — watch-side WatchConnectivity client.
///
/// The mirror of the phone's `WatchSessionBridge`:
///   * receives `WatchSessionState` snapshots via `applicationContext`
///     (latest-wins, survives disconnect) and publishes them to the UI,
///   * sends `WatchCommandMessage`s to the phone (immediate + acked when
///     reachable, queued via `transferUserInfo` otherwise),
///   * plays haptics — both from explicit phone cues AND derived locally
///     from state deltas, so a dropped cue still feels right.
///
/// The watch holds NO patient content — only the control snapshot. See
/// `WatchMessage.swift` for the privacy contract.
@MainActor
final class WatchConnectivityClient: NSObject, ObservableObject {
    @Published private(set) var sessionState: WatchSessionState = .idle
    @Published private(set) var reachable: Bool = false
    /// True once we've received at least one context from the phone — lets
    /// the UI distinguish "no session" from "not yet synced / phone asleep".
    @Published private(set) var hasSynced: Bool = false

    private var lastState: String?

    private var session: WCSession? {
        WCSession.isSupported() ? WCSession.default : nil
    }

    func activate() {
        guard let session else { return }
        session.delegate = self
        session.activate()
    }

    // MARK: - Send commands to the phone

    func send(_ command: WatchCommand, consentMethod: String? = nil) {
        let message = WatchCommandMessage(command: command, consentMethod: consentMethod)
        let payload = message.asDictionary()
        guard let session else { return }
        if session.isReachable {
            // Immediate with an ack; on error fall back to the queue so the
            // intent isn't lost on a momentary blip.
            session.sendMessage(payload, replyHandler: nil) { _ in
                session.transferUserInfo(payload)
            }
        } else {
            session.transferUserInfo(payload)
        }
    }

    // MARK: - Apply an inbound snapshot

    private func apply(context: [String: Any]) {
        let next = WatchSessionState(dictionary: context)
        hasSynced = true
        sessionState = next
        // Derive a haptic from the state delta (belt-and-suspenders for a
        // dropped explicit cue). Same mapping as the phone bridge.
        if next.state != lastState {
            if let cue = WatchHapticDerivation.cue(from: lastState, to: next.state) {
                play(cue)
            }
            lastState = next.state
        }
    }

    // MARK: - Haptics

    private func play(_ cue: WatchHapticCue) {
        WKInterfaceDevice.current().play(cue.wkHapticType)
    }
}

// MARK: - Haptic mapping

/// watchOS-only mapping from the shared `WatchHapticCue` to `WKHapticType`,
/// kept out of the shared file so that file never imports WatchKit.
extension WatchHapticCue {
    var wkHapticType: WKHapticType {
        switch self {
        case .consentConfirmed: return .success
        case .recordingStarted: return .start
        case .paused:           return .directionUp
        case .resumed:          return .start
        case .stopped:          return .stop
        case .linkLost:         return .failure
        }
    }
}

/// State-delta → cue derivation, mirroring `WatchSessionBridge.hapticCue`.
/// Pure so the watch feels the right cue even if the phone's explicit
/// haptic message is dropped.
enum WatchHapticDerivation {
    static func cue(from old: String?, to new: String?) -> WatchHapticCue? {
        switch new {
        case "RECORDING": return old == "PAUSED" ? .resumed : .recordingStarted
        case "PAUSED": return .paused
        case "PROCESSING_STAGE1": return .stopped
        default: return nil
        }
    }
}

// MARK: - WCSessionDelegate

extension WatchConnectivityClient: WCSessionDelegate {
    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        Task { @MainActor [weak self] in
            self?.reachable = session.isReachable
            // Adopt whatever context the phone last published (delivered on
            // activation), so a watch that launched while a session was
            // already running syncs immediately.
            let ctx = session.receivedApplicationContext
            if !ctx.isEmpty { self?.apply(context: ctx) }
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveApplicationContext applicationContext: [String: Any]) {
        Task { @MainActor [weak self] in self?.apply(context: applicationContext) }
    }

    nonisolated func sessionReachabilityDidChange(_ session: WCSession) {
        Task { @MainActor [weak self] in
            let nowReachable = session.isReachable
            // Lost the link mid-recording → the wrist remote is no longer
            // authoritative; cue the clinician.
            if self?.reachable == true, !nowReachable,
               self?.sessionState.state == "RECORDING" {
                self?.play(.linkLost)
            }
            self?.reachable = nowReachable
        }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        Task { @MainActor [weak self] in
            if let raw = message["haptic"] as? String, let cue = WatchHapticCue(rawValue: raw) {
                self?.play(cue)
            }
        }
    }
}
