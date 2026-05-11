import SwiftUI

@main
struct AurionApp: App {
    @StateObject private var appState = AppState()
    @StateObject private var remoteConfig = RemoteConfig.shared

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .environmentObject(remoteConfig)
                // Lock to light appearance. The Aurion UI is a clinical-day
                // colorway (navy on cream, gold accents) — `aurionNavy` is
                // used as a solid text token in many places without a dark
                // variant, so iOS dark mode collapses navy-text-on-navy-bg
                // contrast. A full dark theme is out of scope for the MVP
                // pilot; pin to .light so the design renders as intended
                // regardless of the user's system setting.
                .preferredColorScheme(.light)
                .task(id: appState.isAuthenticated) {
                    // Refresh remote config when the user signs in (or on cold launch
                    // when already signed in). The endpoint requires auth, so calling
                    // it before sign-in would just 401.
                    if appState.isAuthenticated {
                        await remoteConfig.refresh()
                    }
                }
        }
    }
}
