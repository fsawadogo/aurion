import Foundation

/// Environment-based configuration for API endpoints.
enum AppConfig {
    #if DEBUG
    static let apiBaseURL = "http://localhost:8080"
    static let wsBaseURL = "ws://localhost:8080"
    #else
    static let apiBaseURL = ProcessInfo.processInfo.environment["API_BASE_URL"] ?? ""
    static let wsBaseURL = ProcessInfo.processInfo.environment["WS_BASE_URL"] ?? ""
    #endif

    static let apiVersion = "v1"
    static var baseAPIPath: String { "\(apiBaseURL)/api/\(apiVersion)" }
}
