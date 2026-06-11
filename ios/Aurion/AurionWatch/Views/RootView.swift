import SwiftUI

/// #65 — root watch screen. Switches on the latest `WatchSessionState`
/// the phone published. Control-only: no patient content ever renders.
struct RootView: View {
    @EnvironmentObject private var client: WatchConnectivityClient

    var body: some View {
        ZStack {
            content
        }
        .overlay(alignment: .top) { disconnectedBanner }
    }

    @ViewBuilder
    private var content: some View {
        switch client.sessionState.state {
        case "CONSENT_PENDING":
            ConsentView()
        case "RECORDING":
            ControlsView(isRecording: true)
        case "PAUSED":
            ControlsView(isRecording: false)
        case "PROCESSING_STAGE1", "PROCESSING_STAGE2":
            StatusScreen(
                systemImage: "gearshape.2.fill",
                tint: WatchTheme.gold,
                title: WL("watch.processing.title", "Processing"),
                subtitle: WL("watch.processing.sub", "Finishing on iPhone…")
            )
        case "AWAITING_REVIEW", "REVIEW_COMPLETE":
            StatusScreen(
                systemImage: "doc.text.magnifyingglass",
                tint: WatchTheme.gold,
                title: WL("watch.review.title", "Ready to review"),
                subtitle: WL("watch.review.sub", "Open Aurion on iPhone")
            )
        case "EXPORTED", "PURGED":
            StatusScreen(
                systemImage: "checkmark.seal.fill",
                tint: WatchTheme.gold,
                title: WL("watch.done.title", "Encounter complete"),
                subtitle: nil
            )
        default:
            // nil / IDLE / not yet synced — the session is created on the
            // phone (specialty + visit-type live there).
            StatusScreen(
                systemImage: "iphone.gen3",
                tint: WatchTheme.gold,
                title: WL("watch.idle.title", "No active session"),
                subtitle: WL("watch.idle.sub", "Start a session on iPhone")
            )
        }
    }

    @ViewBuilder
    private var disconnectedBanner: some View {
        if !client.reachable && client.sessionState.state == "RECORDING" {
            Text(WL("watch.disconnected", "iPhone unreachable"))
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(WatchTheme.recording)
                .padding(.top, 2)
        }
    }
}

/// Simple centered status screen for the read-only phases.
struct StatusScreen: View {
    let systemImage: String
    let tint: Color
    let title: String
    let subtitle: String?

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: systemImage)
                .font(.system(size: 28, weight: .semibold))
                .foregroundStyle(tint)
            Text(title)
                .font(.system(size: 16, weight: .semibold))
                .multilineTextAlignment(.center)
            if let subtitle {
                Text(subtitle)
                    .font(.system(size: 13))
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            }
        }
        .padding(.horizontal, 8)
    }
}
