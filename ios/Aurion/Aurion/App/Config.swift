import Foundation

/// Environment-based configuration for API endpoints.
enum AppConfig {
    #if DEBUG
    // Simulator runs against a local backend via loopback. Physical
    // device DEBUG builds (USB-C install, no TestFlight needed) hit
    // the dev cloud — the LAN-IP fallback path used to live here but
    // assumed an unrealistic "phone on Mac WiFi + docker-compose up"
    // setup. If you actually want local-backend dev on device, define
    // `LOCAL_BACKEND` in Build Settings (Other Swift Flags: -DLOCAL_BACKEND)
    // and set the IP below.
    #if targetEnvironment(simulator)
    static let apiBaseURL = "http://localhost:8080"
    static let wsBaseURL  = "ws://localhost:8080"
    #elseif LOCAL_BACKEND
    static let apiBaseURL = "http://10.0.0.225:8080"
    static let wsBaseURL  = "ws://10.0.0.225:8080"
    #else
    static let apiBaseURL = "https://api-dev.aurionclinical.com"
    static let wsBaseURL  = "wss://api-dev.aurionclinical.com"
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

    /// Upload timeout for the multipart audio POST to `/transcription/{id}`.
    /// 5 minutes covers the longest plausible upload over a slow link without
    /// stranding the user on a misconfigured cell connection forever.
    ///
    /// NOTE: this is NOT a Stage 1 SLA. Stage 1 delivery is signalled
    /// out-of-band via `/ws/notes/{id}` — Bug A (Marie's 3:30min session
    /// blew past the old 30s wall-clock cap). The upload cap covers only
    /// the HTTP request itself.
    static let stage1UploadTimeoutSeconds: TimeInterval = 300

    /// After this many seconds with no Stage 1 result we swap the
    /// processing-screen label to "Still working — long sessions take
    /// longer" to reassure the clinician the app isn't frozen. The
    /// ring stays parked at 95%. Pre-Bug A this elapsed point used to
    /// trigger a hard timeout + retry prompt; now it's just a status
    /// flip.
    static let stage1LongRunStatusFlipSeconds: TimeInterval = 45
}
