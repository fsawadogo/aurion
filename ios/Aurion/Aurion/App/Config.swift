import Foundation

/// Environment-based configuration for API endpoints.
enum AppConfig {
    #if DEBUG
    // Local development. Simulator hits the loopback; physical device
    // on the Mac's LAN reads through the host IP.
    #if targetEnvironment(simulator)
    static let apiBaseURL = "http://localhost:8080"
    static let wsBaseURL  = "ws://localhost:8080"
    #else
    static let apiBaseURL = "http://10.0.0.225:8080"
    static let wsBaseURL  = "ws://10.0.0.225:8080"
    #endif
    #else
    // Release builds (TestFlight + App Store). Pilot points at the
    // dev AWS infrastructure — Phase 4/5 will split this into TestFlight
    // → dev vs App Store → prod via build configurations. For now,
    // both downstream targets land here.
    static let apiBaseURL = "https://api-dev.aurionclinical.com"
    static let wsBaseURL  = "wss://api-dev.aurionclinical.com"
    #endif

    static let apiVersion = "v1"
    static var baseAPIPath: String { "\(apiBaseURL)/api/\(apiVersion)" }

    /// Hard wall-clock cap for Stage 1 (record-stop → note-delivered).
    /// Matches the MVP SLA. Should move to `RemoteConfig.pipeline` once
    /// the backend exposes a `stage1_latency_ms_target` field.
    static let stage1TimeoutSeconds: TimeInterval = 30
}
