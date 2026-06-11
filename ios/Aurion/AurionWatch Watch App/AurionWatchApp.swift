import SwiftUI

/// #65 — AurionWatch companion app entry point.
///
/// A control-only wrist remote for the phone's capture session: confirm
/// consent, start / stop / pause / resume, see live state + elapsed, feel
/// haptic cues. It captures nothing and shows no patient content (see
/// `WatchMessage.swift` for the privacy contract).
///
/// The single `WatchConnectivityClient` is owned here and injected into
/// the view tree; it activates `WCSession` on launch.
@main
struct AurionWatchApp: App {
    @StateObject private var client = WatchConnectivityClient()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(client)
                .onAppear { client.activate() }
        }
    }
}
