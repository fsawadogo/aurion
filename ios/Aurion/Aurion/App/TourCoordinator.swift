import Combine
import SwiftUI

/// Dashboard elements the first-run coach-mark tour spotlights. Views publish
/// their on-screen frame for these via `.tourAnchor(_:)`. The final "tab bar"
/// step highlights a computed region instead of an anchored view.
enum TourAnchor: Hashable {
    case greeting
    case startSession
    case recentSessions
}

/// One coach-mark step. `anchor == nil` + `highlightsTabBar == false` means a
/// centered card with no spotlight (an intro). `highlightsTabBar` lights the
/// bottom tab-bar strip, which the native `TabView` can't expose as an anchor.
struct TourStep: Identifiable {
    let id = UUID()
    let anchor: TourAnchor?
    let titleKey: String
    let messageKey: String
    let highlightsTabBar: Bool

    init(
        anchor: TourAnchor?,
        titleKey: String,
        messageKey: String,
        highlightsTabBar: Bool = false
    ) {
        self.anchor = anchor
        self.titleKey = titleKey
        self.messageKey = messageKey
        self.highlightsTabBar = highlightsTabBar
    }
}

/// Drives the first-run coach-mark tour over the dashboard. Owned by
/// `ContentView` and shared into the tab tree via the environment. It only
/// tracks tour state — persistence of "seen" lives in `AppState`, which
/// `ContentView` updates via the `onDismiss` callback so this stays free of
/// storage concerns.
@MainActor
final class TourCoordinator: ObservableObject {
    @Published private(set) var isActive = false
    @Published private(set) var stepIndex = 0
    /// Bound to the "Don't show again" checkbox. Defaults on, so the common
    /// "watch once" path permanently dismisses the tour; unchecking re-arms
    /// it for the next launch.
    @Published var dontShowAgain = true

    let steps: [TourStep] = [
        TourStep(
            anchor: .greeting,
            titleKey: "tour.welcome.title",
            messageKey: "tour.welcome.body"
        ),
        TourStep(
            anchor: .startSession,
            titleKey: "tour.start.title",
            messageKey: "tour.start.body"
        ),
        TourStep(
            anchor: .recentSessions,
            titleKey: "tour.review.title",
            messageKey: "tour.review.body"
        ),
        TourStep(
            anchor: nil,
            titleKey: "tour.explore.title",
            messageKey: "tour.explore.body",
            highlightsTabBar: true
        ),
    ]

    /// Guards against re-triggering on every dashboard re-appear within a
    /// launch (e.g. tab switches) when "Don't show again" was left unchecked.
    private var hasAutoStartedThisLaunch = false
    private var onDismiss: ((_ dontShowAgain: Bool) -> Void)?

    var currentStep: TourStep { steps[min(stepIndex, steps.count - 1)] }
    var isLastStep: Bool { stepIndex >= steps.count - 1 }

    /// Wire the persistence callback. `dontShowAgain` is forwarded so the
    /// host can decide whether to set the "seen" flag.
    func configure(onDismiss: @escaping (_ dontShowAgain: Bool) -> Void) {
        self.onDismiss = onDismiss
    }

    /// Auto-launch on the first dashboard appearance for a user who hasn't
    /// seen it — at most once per app launch.
    func autoStartIfNeeded(seen: Bool) {
        guard !seen, !hasAutoStartedThisLaunch, !isActive else { return }
        hasAutoStartedThisLaunch = true
        start()
    }

    /// Manual replay (from Profile). Re-arms "Don't show again" so finishing
    /// the replay doesn't accidentally un-suppress the tour.
    func replay() {
        dontShowAgain = true
        start()
    }

    private func start() {
        stepIndex = 0
        withAnimation(AurionAnimation.smooth) { isActive = true }
    }

    func next() {
        if isLastStep {
            finish()
        } else {
            withAnimation(AurionAnimation.spring) { stepIndex += 1 }
        }
    }

    func skip() { finish() }

    private func finish() {
        withAnimation(AurionAnimation.smooth) { isActive = false }
        onDismiss?(dontShowAgain)
    }
}

// MARK: - Anchor plumbing

/// Collects the on-screen bounds of tour-highlighted views. Children publish
/// `[anchor: Anchor<CGRect>]`; the host resolves them against its own
/// `GeometryProxy` so frames are in a single, consistent coordinate space.
struct TourAnchorKey: PreferenceKey {
    static let defaultValue: [TourAnchor: Anchor<CGRect>] = [:]
    static func reduce(
        value: inout [TourAnchor: Anchor<CGRect>],
        nextValue: () -> [TourAnchor: Anchor<CGRect>]
    ) {
        value.merge(nextValue()) { _, new in new }
    }
}

extension View {
    /// Publish this view's bounds so the coach-mark overlay can spotlight it.
    func tourAnchor(_ anchor: TourAnchor) -> some View {
        anchorPreference(key: TourAnchorKey.self, value: .bounds) { [anchor: $0] }
    }
}
