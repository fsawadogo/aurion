import SwiftUI

/// #65 — shown in CONSENT_PENDING once consent is confirmed: a single
/// large Record button starts the session from the wrist (drives the
/// phone's `startRecording`). Reaching this screen means the consent
/// audit event is already written on the phone — recording is unblocked.
struct StartView: View {
    @EnvironmentObject private var client: WatchConnectivityClient
    @State private var pending = false

    var body: some View {
        VStack(spacing: 12) {
            Image(systemName: "checkmark.shield.fill")
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(WatchTheme.gold)
            Text(WL("watch.start.title", "Consent confirmed"))
                .font(.system(size: 15, weight: .semibold))
                .multilineTextAlignment(.center)

            Button {
                pending = true
                client.send(.start)
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "record.circle.fill")
                    Text(WL("watch.action.record", "Start recording"))
                        .font(.system(size: 15, weight: .semibold))
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 4)
            }
            .tint(WatchTheme.recording)
            .disabled(pending)
        }
        .padding(.horizontal, 8)
        // On a successful start the phone flips to RECORDING and this view
        // is replaced by ControlsView; the reset just covers a re-render.
        .onChange(of: client.sessionState.state) { _, _ in pending = false }
    }
}
