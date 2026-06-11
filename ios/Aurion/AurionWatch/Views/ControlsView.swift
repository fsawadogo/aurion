import SwiftUI

/// #65 — recording controls. Pause/Resume + Stop, with the live elapsed
/// timer. Stop is disabled until the phone's minimum-recording floor
/// passes (`canStop`). Buttons disable optimistically on tap and re-enable
/// when the next state context confirms the transition — avoids a
/// double-fire on a laggy link.
struct ControlsView: View {
    @EnvironmentObject private var client: WatchConnectivityClient
    let isRecording: Bool

    @State private var pending = false

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 6) {
                Circle()
                    .fill(isRecording ? WatchTheme.recording : WatchTheme.paused)
                    .frame(width: 8, height: 8)
                    .opacity(isRecording ? 1 : 0.9)
                Text(isRecording
                     ? WL("watch.state.recording", "Recording")
                     : WL("watch.state.paused", "Paused"))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(isRecording ? WatchTheme.recording : WatchTheme.paused)
            }

            ElapsedView(
                startedAtEpoch: client.sessionState.startedAtEpoch,
                isRunning: isRecording
            )

            HStack(spacing: 8) {
                if isRecording {
                    controlButton(
                        title: WL("watch.action.pause", "Pause"),
                        icon: "pause.fill",
                        tint: WatchTheme.paused
                    ) { client.send(.pause) }
                } else {
                    controlButton(
                        title: WL("watch.action.resume", "Resume"),
                        icon: "play.fill",
                        tint: WatchTheme.gold
                    ) { client.send(.resume) }
                }

                controlButton(
                    title: WL("watch.action.stop", "Stop"),
                    icon: "stop.fill",
                    tint: WatchTheme.recording,
                    disabled: !client.sessionState.canStop
                ) { client.send(.stop) }
            }
        }
        .padding(.horizontal, 4)
        // A new context from the phone means the transition we optimistically
        // fired has landed (or was rejected) — re-enable the buttons.
        .onChange(of: client.sessionState.state) { _, _ in pending = false }
    }

    @ViewBuilder
    private func controlButton(
        title: String,
        icon: String,
        tint: Color,
        disabled: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button {
            pending = true
            action()
        } label: {
            VStack(spacing: 2) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .semibold))
                Text(title)
                    .font(.system(size: 12, weight: .medium))
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 4)
        }
        .tint(tint)
        .disabled(disabled || pending)
    }
}
