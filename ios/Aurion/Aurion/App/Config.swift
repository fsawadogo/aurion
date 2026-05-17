import Foundation

/// Environment-based configuration for API endpoints.
enum AppConfig {
    #if DEBUG
    // Use localhost for Simulator, Mac IP for physical device
    #if targetEnvironment(simulator)
    static let apiBaseURL = "http://localhost:8080"
    static let wsBaseURL = "ws://localhost:8080"
    #else
    static let apiBaseURL = "http://10.0.0.225:8080"
    static let wsBaseURL = "ws://10.0.0.225:8080"
    #endif
    #else
    static let apiBaseURL = ProcessInfo.processInfo.environment["API_BASE_URL"] ?? ""
    static let wsBaseURL = ProcessInfo.processInfo.environment["WS_BASE_URL"] ?? ""
    #endif

    static let apiVersion = "v1"
    static var baseAPIPath: String { "\(apiBaseURL)/api/\(apiVersion)" }

    /// Hard wall-clock cap for Stage 1 (record-stop → note-delivered).
    /// Matches the MVP SLA. Should move to `RemoteConfig.pipeline` once
    /// the backend exposes a `stage1_latency_ms_target` field.
    static let stage1TimeoutSeconds: TimeInterval = 30
}
