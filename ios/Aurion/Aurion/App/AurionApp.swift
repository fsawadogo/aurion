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
                // Dark mode shipped under AUR-DESIGN-DARK (muted slate
                // palette). Adaptive tokens in Theme.swift carry the
                // light + dark pairs; brand-fixed surfaces (login
                // gradient, navy toolbar) stay navy in both modes by
                // design — they're identity, not theme.
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
