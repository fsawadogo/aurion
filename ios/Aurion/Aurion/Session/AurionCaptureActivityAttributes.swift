import ActivityKit
import Foundation

/// Live Activity attributes for an in-flight Aurion capture session.
///
/// Both the main app target and the ``AurionWidgets`` extension consume
/// this type — the app starts/ends the activity, the widget renders it.
/// Lives under `Aurion/Session/` (auto-included in the main target) and
/// is added to the widget target explicitly via a build-file exception
/// so the same source file backs both sides without duplication.
struct AurionCaptureActivityAttributes: ActivityAttributes {
    public typealias ContentState = State

    /// Static attributes — set once at `Activity.request(...)` time and
    /// never mutated. Anything that changes during the encounter belongs
    /// in ``ContentState`` instead.
    public struct State: Codable, Hashable {
        /// Wall-clock instant when the user tapped Record. Used by the
        /// widget UI to drive a `Text(.timer)` view that ticks without
        /// requiring per-second push updates — iOS handles the redraw.
        public var startedAt: Date
        /// True while paused. Drives the icon swap and dimmed visual
        /// state in the Live Activity / Dynamic Island.
        public var isPaused: Bool

        public init(startedAt: Date, isPaused: Bool) {
            self.startedAt = startedAt
            self.isPaused = isPaused
        }
    }

    /// Specialty slug from ``SessionStartRequest`` ("orthopedic_surgery",
    /// "plastic_surgery", …). Surfaced as the activity title so the
    /// physician can tell at a glance which template is recording.
    public let specialty: String

    /// Backend session UUID. Used by widget tap-throughs to deep-link
    /// back into the right note via the existing ``AppNavigation``
    /// session-id bus (same path as a Spotlight tap).
    public let sessionID: String
}
