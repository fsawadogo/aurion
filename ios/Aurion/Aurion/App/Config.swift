import Foundation

/// Environment-based configuration for API endpoints.
enum AppConfig {
    #if DEBUG
    // Use localhost for Simulator, Mac IP for physical device
    #if targetEnvironment(simulator)
    static let apiBaseURL = "http://localhost:8080"
    static let wsBaseURL = "ws://localhost:8080"
    #else
    static let apiBaseURL = "http://10.0.0.207:8080"
    static let wsBaseURL = "ws://10.0.0.207:8080"
    #endif
    #else
    static let apiBaseURL = ProcessInfo.processInfo.environment["API_BASE_URL"] ?? ""
    static let wsBaseURL = ProcessInfo.processInfo.environment["WS_BASE_URL"] ?? ""
    #endif

    static let apiVersion = "v1"
    static var baseAPIPath: String { "\(apiBaseURL)/api/\(apiVersion)" }
}
