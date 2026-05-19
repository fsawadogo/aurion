import ActivityKit
import Foundation

/// Thin wrapper around ``ActivityKit`` so ``SessionManager`` doesn't need
/// to know about authorization checks, optional handle storage, or the
/// availability gate. Lives at MainActor isolation because everything
/// it touches (the ``Activity`` handle, ``SessionManager`` state) is
/// main-actor by contract.
///
/// Designed to fail soft: if the user has Live Activities disabled in
/// Settings, the coordinator becomes a no-op. The capture session still
/// runs normally — the activity is a glanceability nicety, not load-
/// bearing.
@MainActor
final class LiveActivityCoordinator {
    private var activity: Activity<AurionCaptureActivityAttributes>?

    /// Starts a Live Activity for an in-flight session. Idempotent —
    /// calling twice for the same session ends the prior activity and
    /// starts a fresh one. Returns silently on any error so the capture
    /// pipeline never blocks on widget concerns.
    func start(sessionID: String, specialty: String) {
        guard ActivityAuthorizationInfo().areActivitiesEnabled else { return }

        // Tear down any orphaned activity from a previous session
        // before starting a new one.
        if activity != nil {
            Task { await endIfActive() }
        }

        let attributes = AurionCaptureActivityAttributes(
            specialty: specialty,
            sessionID: sessionID
        )
        let state = AurionCaptureActivityAttributes.ContentState(
            startedAt: Date(),
            isPaused: false
        )

        do {
            activity = try Activity.request(
                attributes: attributes,
                content: .init(state: state, staleDate: nil),
                pushType: nil
            )
        } catch {
            // Authorization revoked between the gate check and request,
            // or system threw for another reason. Swallow — same fail-
            // soft contract as the gate.
            activity = nil
        }
    }

    /// Updates the activity's content state when the session is paused
    /// or resumed. Drives the Dynamic Island icon swap (record dot ↔
    /// pause glyph) and the lock-screen "Recording / Paused" label.
    func setPaused(_ paused: Bool) {
        guard let activity else { return }
        // The activity's `state` is immutable; we project a new one
        // from the previous wall-clock anchor so the timer in the
        // widget keeps counting from the same start (the user's intent
        // when they pause is "freeze the displayed time" — handled in
        // the widget by showing a pause glyph instead of the timer).
        let next = AurionCaptureActivityAttributes.ContentState(
            startedAt: activity.content.state.startedAt,
            isPaused: paused
        )
        Task {
            await activity.update(.init(state: next, staleDate: nil))
        }
    }

    /// Ends the activity. Called from ``SessionManager.stopRecording``
    /// and from ``endSession``. Drop the Dynamic Island immediately;
    /// keep nothing on the lock screen after the session completes —
    /// follow-up navigation lives in the Sessions inbox / Spotlight.
    func end() {
        Task { await endIfActive() }
    }

    private func endIfActive() async {
        guard let current = activity else { return }
        activity = nil
        await current.end(nil, dismissalPolicy: .immediate)
    }
}
