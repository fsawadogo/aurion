import Foundation
import Combine
#if canImport(WatchConnectivity)
import WatchConnectivity
#endif

/// #65 — phone-side WatchConnectivity bridge.
///
/// Bridges the `AurionWatch` companion to the existing `SessionManager`:
///   * Watch → phone: decodes a `WatchCommandMessage` and calls the
///     matching `SessionManager` method ON the main actor — the watch is
///     just another trigger for the SAME path a phone tap takes, audit
///     log included. `.confirmConsent` does NOT bypass the consent gate.
///   * Phone → watch: observes `SessionManager.$session` + the session's
///     `$state` and publishes a fresh `WatchSessionState` via
///     `updateApplicationContext` on every transition (and on activation),
///     plus a transient haptic cue on the transitions that warrant one.
///
/// Dormant without a paired watch: `updateApplicationContext` with no
/// reachable watch app is a cheap OS no-op, and no commands arrive, so
/// wiring this into every session is safe even before the watch ships.
///
/// PRIVACY: only the non-PHI control fields in `WatchSessionState` are
/// ever published. No transcript / note / identifier / frames.
@MainActor
final class WatchSessionBridge: NSObject, ObservableObject {
    private weak var sessionManager: SessionManager?
    private var cancellables = Set<AnyCancellable>()
    /// Subscription to the *current* session's `$state`; replaced whenever
    /// `SessionManager.$session` swaps the session out.
    private var stateCancellable: AnyCancellable?
    /// Last state we published — drives local haptic-cue derivation so a
    /// dropped haptic message still feels right on the watch.
    private var lastPublishedState: String?
    /// One-shot re-push so the watch's Stop button enables once the phone's
    /// minimum-recording floor passes (canStop flips without a state change).
    private var stopGateTask: Task<Void, Never>?

    #if canImport(WatchConnectivity)
    private var session: WCSession? {
        WCSession.isSupported() ? WCSession.default : nil
    }
    #endif

    /// Activate the WCSession and start mirroring `manager`'s session
    /// state to the watch. Call once, from `ContentView`, with the app's
    /// `SessionManager` instance.
    func connect(to manager: SessionManager) {
        sessionManager = manager
        activate()
        observe(manager)
    }

    private func activate() {
        #if canImport(WatchConnectivity)
        guard let session else { return }
        session.delegate = self
        session.activate()
        #endif
    }

    // MARK: - Observe phone-side state → publish to watch

    private func observe(_ manager: SessionManager) {
        // Re-subscribe to each new session's state stream, and push an
        // initial context so a freshly-launched watch app syncs at once.
        manager.$session
            .sink { [weak self] session in
                guard let self else { return }
                self.bindState(of: session)
                self.publishState()
            }
            .store(in: &cancellables)
    }

    private func bindState(of session: CaptureSession?) {
        stateCancellable = session?.$state
            .removeDuplicates()
            .sink { [weak self] newState in
                self?.publishState(forStateOverride: newState)
            }
    }

    /// Build the current snapshot and push it to the watch. `forStateOverride`
    /// is the just-changed value from the `$state` publisher (which fires
    /// *before* the stored property updates), so callers from that path pass
    /// it explicitly; everyone else reads the live session.
    private func publishState(forStateOverride overrideState: SessionState? = nil) {
        guard let manager = sessionManager else { return }
        let session = manager.session
        let state = overrideState ?? session?.state
        let stateRaw = state?.rawValue

        let isRecording = state == .recording
        let startedAtEpoch: Double? = isRecording
            ? manager.recordingStartedAt?.timeIntervalSince1970
            : nil

        let snapshot = WatchSessionState(
            state: stateRaw,
            consentConfirmed: session?.isConsentConfirmed ?? false,
            startedAtEpoch: startedAtEpoch,
            canStop: manager.stopAllowed()
        )
        send(context: snapshot)

        // Emit a haptic cue on a genuine transition (computed from the
        // delta, so we don't double-fire on a redundant publish).
        if stateRaw != lastPublishedState {
            if let cue = Self.hapticCue(from: lastPublishedState, to: stateRaw) {
                send(haptic: cue)
            }
            lastPublishedState = stateRaw
        }

        // When recording starts, canStop is false until the phone's
        // minimum-recording floor passes — schedule a single re-push so the
        // watch's Stop button enables without waiting for the next
        // transition. The phone's gate stays authoritative.
        stopGateTask?.cancel()
        if isRecording && !manager.stopAllowed() {
            stopGateTask = Task { [weak self] in
                let floor = SessionManager.minimumRecordingSeconds
                try? await Task.sleep(nanoseconds: UInt64(floor * 1_000_000_000) + 100_000_000)
                guard !Task.isCancelled else { return }
                self?.publishState()
            }
        }
    }

    /// Map a state transition to the haptic cue the watch should feel.
    /// Pure + nonisolated so it's unit-testable without a session. The
    /// consent cue is fired explicitly on the command ack (not derived
    /// here), so this covers only the record-lifecycle transitions.
    nonisolated static func hapticCue(from old: String?, to new: String?) -> WatchHapticCue? {
        switch new {
        case SessionState.recording.rawValue:
            return old == SessionState.paused.rawValue ? .resumed : .recordingStarted
        case SessionState.paused.rawValue:
            return .paused
        case SessionState.processingStage1.rawValue:
            return .stopped
        default:
            return nil
        }
    }

    // MARK: - Send helpers

    private func send(context: WatchSessionState) {
        #if canImport(WatchConnectivity)
        guard let session, session.activationState == .activated else { return }
        // updateApplicationContext throws only on an encoding error; the
        // payload is all plist-legal primitives, so this never throws in
        // practice. try? keeps a stray failure from affecting capture.
        try? session.updateApplicationContext(context.asDictionary())
        #endif
    }

    private func send(haptic cue: WatchHapticCue) {
        #if canImport(WatchConnectivity)
        guard let session, session.isReachable else { return }
        session.sendMessage(["haptic": cue.rawValue], replyHandler: nil, errorHandler: nil)
        #endif
    }

    // MARK: - Handle commands from the watch

    /// Decode + dispatch a command dictionary on the main actor. Extracted
    /// from the delegate callbacks so it's directly unit-testable.
    func handle(commandDictionary dict: [String: Any]) {
        guard let message = WatchCommandMessage(dictionary: dict) else { return }
        dispatch(message)
    }

    private func dispatch(_ message: WatchCommandMessage) {
        guard let manager = sessionManager, let session = manager.session else {
            // No active session — a stale watch tap; re-sync the true state.
            publishState()
            return
        }
        let state = session.state

        // Validate against current state so a stale watch tap can't drive an
        // illegal transition. SessionManager also guards each method, but
        // rejecting here keeps us from firing a no-op network call.
        switch message.command {
        case .confirmConsent:
            guard state == .consentPending, !session.isConsentConfirmed else { break }
            let method = message.consentMethod
                .flatMap(ConsentMethod.init(rawValue:)) ?? .verbal
            Task { await manager.confirmConsent(method: method); self.send(haptic: .consentConfirmed) }

        case .start:
            guard state == .consentPending, session.isConsentConfirmed else { break }
            Task { await manager.startRecording() }

        case .pause:
            guard state == .recording else { break }
            manager.pauseRecording()

        case .resume:
            guard state == .paused else { break }
            manager.resumeRecording()

        case .stop:
            guard state == .recording || state == .paused, manager.stopAllowed() else { break }
            Task { await manager.stopRecording() }
        }

        // Whatever we did (or rejected), push the authoritative state so the
        // watch re-syncs and never sits on a stale optimistic toggle.
        publishState()
    }
}

#if canImport(WatchConnectivity)
extension WatchSessionBridge: WCSessionDelegate {
    nonisolated func session(
        _ session: WCSession,
        activationDidCompleteWith activationState: WCSessionActivationState,
        error: Error?
    ) {
        // Push the current state once activation settles so a watch that
        // launched first still syncs.
        Task { @MainActor [weak self] in self?.publishState() }
    }

    nonisolated func session(_ session: WCSession, didReceiveMessage message: [String: Any]) {
        Task { @MainActor [weak self] in self?.handle(commandDictionary: message) }
    }

    nonisolated func session(
        _ session: WCSession,
        didReceiveMessage message: [String: Any],
        replyHandler: @escaping ([String: Any]) -> Void
    ) {
        Task { @MainActor [weak self] in self?.handle(commandDictionary: message) }
        // Ack immediately so the watch's reachable-path sendMessage resolves.
        replyHandler(["ok": true])
    }

    nonisolated func session(_ session: WCSession, didReceiveUserInfo userInfo: [String: Any]) {
        Task { @MainActor [weak self] in self?.handle(commandDictionary: userInfo) }
    }

    // Required stubs on iOS — the OS can deactivate the session when
    // switching paired watches; reactivate so the link recovers.
    nonisolated func sessionDidBecomeInactive(_ session: WCSession) {}
    nonisolated func sessionDidDeactivate(_ session: WCSession) {
        session.activate()
    }
}
#endif
