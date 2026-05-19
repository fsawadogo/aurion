import SwiftUI

@main
struct AurionApp: App {
    @StateObject private var appState = AppState()
    @StateObject private var remoteConfig = RemoteConfig.shared
    @Environment(\.scenePhase) private var scenePhase

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
                // Spotlight result tap. The donation lives in SessionNoteView;
                // here we just translate the activity back into the cross-
                // cutting nav bus. ContentView's "active session in flight"
                // branch swallows MainTabView, so the bus values stay buffered
                // on AppNavigation until the inbox is back on screen — no
                // dropped deep-links if the user happens to be mid-capture.
                .onContinueUserActivity(AppNavigation.sessionActivityType) { activity in
                    guard
                        let info = activity.userInfo,
                        let sessionID = info["session_id"] as? String,
                        !sessionID.isEmpty
                    else { return }
                    AppNavigation.shared.requestTab(.sessions)
                    AppNavigation.shared.requestNote(sessionID: sessionID)
                }
        }
        .onChange(of: scenePhase) { _, newPhase in
            // M-12 stale sweep — every time the app comes to foreground we
            // check the iOS temp dir for Aurion artifacts older than 24h
            // and delete them. Cheap (a single directory scan) and runs
            // outside any active session so it never races with capture.
            if newPhase == .active {
                Task { @MainActor in
                    LocalDataPurger.purgeStaleArtifacts()
                }
            }
        }
    }
}
