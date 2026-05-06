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
