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
        videoCaptureFps: 1,
        // Phase 1 default — byte-identical to today's behavior. The eval
        // team flips this per-session for Phase 2 evaluation runs.
        visualEvidenceMode: .framesOnly,
        clipWindowMs: 7_000,
        clipTriggerKinds: ["motion", "rom", "gait", "procedural"],
        // Off until AppConfig pushes a non-zero floor (#324). Zero means
        // no cadence timer is ever created — strict no-op fallback.
        clipCadenceSeconds: 0
    )
    @Published private(set) var featureFlags = ClientFeatureFlagsResponse(
        // Off for the pilot — matches the backend AppConfig default. This is
        // only the fallback used before/if the /config fetch fails; the live
        // AppConfig value is the runtime source of truth.
        screenCaptureEnabled: false,
        noteVersioningEnabled: true,
        sessionPauseResumeEnabled: true,
        perSessionProviderOverride: true,
        metaWearablesEnabled: false,
        // Card-visibility flags default to `false` so the four post-pilot
        // cards on SessionNoteView stay hidden until an ADMIN flips them
        // via the web portal. Matches the backend FeatureFlagsConfig
        // defaults and the operator's AppConfig v7 push.
        ordersCardEnabled: false,
        codingCardEnabled: false,
        patientSummaryCardEnabled: false,
        emrWritebackCardEnabled: false
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
