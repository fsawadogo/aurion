import Foundation

/// Single source of truth for whether the app may produce fabricated
/// clinical content (demo notes, synthetic audio payloads).
///
/// **P0-03 contract:** demo paths are reachable only in Debug builds running
/// in the iOS Simulator. Release builds (TestFlight, App Store, pilot
/// hardware) NEVER produce demo content under any failure mode. A real
/// transcription failure on a pilot device must surface as an error, never
/// as a fabricated note.
///
/// The runtime override `AURION_DEMO_DISABLED=1` forces demo off even on
/// the simulator so the production-path UX is testable end-to-end.
enum DemoMode {
    /// True only when fabricated content is permitted to surface. Returns
    /// false in any release build, on any physical device, or when the
    /// runtime override is set.
    static var isEnabled: Bool {
        #if DEBUG
        #if targetEnvironment(simulator)
        if ProcessInfo.processInfo.environment["AURION_DEMO_DISABLED"] == "1" {
            return false
        }
        return true
        #else
        return false
        #endif
        #else
        return false
        #endif
    }
}
