import Foundation
import Combine

/// Live AppConfig values pulled from the backend's GET /config endpoint.
/// Falls back to safe defaults that match the AppConfig schema defaults
/// when the backend is unreachable or the user is signed out.
///
/// The values here drive feature gating and pipeline timing — frame
/// windows, capture FPS, screen-capture toggle, etc. Per CLAUDE.md these
/// must NEVER be hardcoded in the iOS app.
@MainActor
final class RemoteConfig: ObservableObject {
    static let shared = RemoteConfig()

    @Published private(set) var providers = ClientProvidersResponse(
        transcription: "whisper",
        noteGeneration: "anthropic",
        vision: "openai"
    )
    @Published private(set) var pipeline = ClientPipelineResponse(
        stage1SkipWindowSeconds: 60,
        frameWindowClinicMs: 3_000,
        frameWindowProceduralMs: 7_000,
        screenCaptureFps: 2,
        videoCaptureFps: 1
    )
    @Published private(set) var featureFlags = ClientFeatureFlagsResponse(
        screenCaptureEnabled: true,
        noteVersioningEnabled: true,
        sessionPauseResumeEnabled: true,
        perSessionProviderOverride: true,
        metaWearablesEnabled: false
    )
    @Published private(set) var lastUpdated: Date?
    @Published private(set) var lastError: String?

    private init() {}

    /// Fetches the current config from /api/v1/config. Safe to call repeatedly;
    /// failures fall back to whatever values are currently held (defaults on first run).
    func refresh() async {
        do {
            let response = try await APIClient.shared.getClientConfig()
            providers = response.providers
            pipeline = response.pipeline
            featureFlags = response.featureFlags
            lastUpdated = Date()
            lastError = nil
        } catch {
            lastError = error.localizedDescription
        }
    }
}
