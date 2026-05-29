import Combine
import SwiftUI

/// View-model driving a single ``Stage2DashboardTile``. Owns the 5-second
/// poll against ``/notes/{id}/stage2-status``; stops automatically when
/// the status reaches a terminal state, when the view disappears, or
/// when the session leaves ``PROCESSING_STAGE2``.
///
/// SRP: the tile view stays presentational — every async/poll concern
/// lives here.
@MainActor
final class Stage2TileViewModel: ObservableObject {
    @Published private(set) var status: Stage2StatusResponse?
    @Published private(set) var loadFailed = false

    private let sessionId: String
    private var pollTask: Task<Void, Never>?

    init(sessionId: String) {
        self.sessionId = sessionId
    }

    /// Begin polling. Idempotent: cancels any prior task first.
    func start() {
        pollTask?.cancel()
        pollTask = Task { await self.pollLoop() }
    }

    /// Stop polling. Called from `.onDisappear` and from the loop itself
    /// once a terminal status arrives.
    func stop() {
        pollTask?.cancel()
        pollTask = nil
    }

    private func pollLoop() async {
        while !Task.isCancelled {
            await fetchOnce()
            if let s = status, !s.isInProgress, s.hasStarted {
                // Terminal — completed or failed. Caller's parent view
                // observes `status` and refreshes the session list; we
                // don't need to keep hammering the endpoint.
                return
            }
            try? await Task.sleep(nanoseconds: 5_000_000_000)
        }
    }

    private func fetchOnce() async {
        do {
            status = try await APIClient.shared.getStage2Status(sessionId: sessionId)
            loadFailed = false
        } catch {
            // First-load failures matter for UI (show a faint warning);
            // mid-poll transient errors are silently retried.
            if status == nil {
                loadFailed = true
            }
        }
    }
}


/// Dashboard tile rendered for sessions currently in
/// ``SessionState.PROCESSING_STAGE2``. Surfaces async Stage 2 progress
/// so the physician knows whether the visual enrichment is still in
/// flight or stuck.
///
/// Reuses ``AurionCard`` + the design tokens; no new visual primitives.
/// Status iconography uses SF Symbols + ``symbolEffect`` per the iOS HIG.
struct Stage2DashboardTile: View {
    let session: SessionResponse
    /// Fired when the polled status reaches ``completed`` — the dashboard
    /// uses this to refresh ``recentSessions`` so the row moves from
    /// PROCESSING_STAGE2 → AWAITING_REVIEW (and the tile drops out).
    let onCompleted: () -> Void
    /// Fired when the polled status reaches ``failed`` — surfaced for
    /// telemetry / future retry affordance.
    let onFailed: () -> Void

    @StateObject private var viewModel: Stage2TileViewModel

    init(
        session: SessionResponse,
        onCompleted: @escaping () -> Void = {},
        onFailed: @escaping () -> Void = {}
    ) {
        self.session = session
        self.onCompleted = onCompleted
        self.onFailed = onFailed
        _viewModel = StateObject(
            wrappedValue: Stage2TileViewModel(sessionId: session.id)
        )
    }

    var body: some View {
        NavigationLink(destination: SessionNoteView(session: session)) {
            AurionCard(padding: 16, accent: false) {
                HStack(spacing: 12) {
                    statusIcon

                    VStack(alignment: .leading, spacing: 2) {
                        Text(localizedSpecialty(session.specialty))
                            .font(.headline)
                            .foregroundColor(.aurionTextPrimary)
                        Text(statusLine)
                            .font(.subheadline)
                            .foregroundColor(.aurionTextSecondary)
                            .lineLimit(2)
                    }

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.footnote.weight(.semibold))
                        .foregroundColor(.aurionTextSecondary)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel(L("stage2.a11y", localizedSpecialty(session.specialty), statusLine))
                .accessibilityHint(L("stage2.a11yHint"))
            }
        }
        .buttonStyle(.plain)
        // Smooth the icon/label/layout swap when the polled status flips
        // (every ~5s) instead of snapping — the symbolEffects already animate
        // the glyph; this carries the surrounding content with it.
        .animation(AurionAnimation.smooth, value: viewModel.status?.status)
        .onAppear { viewModel.start() }
        .onDisappear { viewModel.stop() }
        .onChange(of: viewModel.status) { _, newValue in
            guard let newValue else { return }
            if newValue.isCompleted { onCompleted() }
            if newValue.isFailed { onFailed() }
        }
    }

    // MARK: - Status presentation

    private var displayKind: Stage2DisplayKind {
        viewModel.status?.displayKind ?? .pending
    }

    @ViewBuilder
    private var statusIcon: some View {
        switch displayKind {
        case .pending:
            AurionIconBubble(symbol: "hourglass", tint: .aurionGold, size: 36)
                .symbolEffect(.pulse, options: .repeating, value: viewModel.status?.status)
        case .running:
            AurionIconBubble(symbol: "arrow.triangle.2.circlepath", tint: .aurionGold, size: 36)
                .symbolEffect(.rotate, options: .repeating, value: viewModel.status?.framesProcessed ?? 0)
        case .completed:
            AurionIconBubble(symbol: "checkmark.circle.fill", tint: .aurionGreen, size: 36)
                .symbolEffect(.bounce, value: viewModel.status?.status)
        case .failed:
            AurionIconBubble(symbol: "exclamationmark.triangle.fill", tint: .aurionRed, size: 36)
        }
    }

    private var statusLine: String {
        switch displayKind {
        case .pending:
            return L("stage2.queued", formatRelativeTime(session.createdAt))
        case .running:
            let frames = viewModel.status?.framesProcessed ?? 0
            return frames > 0
                ? Lplural("stage2.enrichingFrames", frames)
                : L("stage2.enriching")
        case .completed:
            return L("stage2.complete")
        case .failed:
            return viewModel.status?.errorMessage.flatMap { $0.isEmpty ? nil : $0 }
                ?? L("stage2.failed")
        }
    }
}
