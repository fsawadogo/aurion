import SwiftUI

@main
struct AurionApp: App {
    @StateObject private var appState = AppState()
    @StateObject private var remoteConfig = RemoteConfig.shared
    @StateObject private var appLock = AppLockManager()
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .environmentObject(remoteConfig)
                .environmentObject(appLock)
                // Biometric app lock over the whole authenticated surface.
                // Never shown pre-sign-in (nothing to protect on the login
                // screen); the lock view self-prompts on appear.
                .overlay {
                    if appState.isAuthenticated && appLock.isLocked {
                        AppLockView()
                            .environmentObject(appLock)
                    }
                }
                .animation(AurionAnimation.smooth, value: appLock.isLocked)
                // User-selectable Light/Dark/System theme (Profile › Appearance).
                // nil follows the device; the system cross-fades the switch.
                .preferredColorScheme(appState.colorSchemeOverride)
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
                        // Drain any encounters captured offline in a prior
                        // session and arm reconnect-driven sync. Gated on auth
                        // because the upload needs a bearer token.
                        OfflineUploadQueue.shared.start()
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
                // Deep-link entry points:
                //   aurion://start-session              ← home-screen widget
                //   aurion://session/{uuid}             ← Live Activity tap
                // Both flow into AppNavigation so the existing dashboard /
                // sessions consumers handle them with no new code paths.
                .onOpenURL { url in
                    guard url.scheme == "aurion" else { return }
                    switch url.host {
                    case "start-session":
                        // Default specialty/consultation type match the
                        // dashboard's first Quick Start card. The user can
                        // still adjust in the encounter-type sheet.
                        let profile = appState.physicianProfile
                        let specialty = profile?.primarySpecialty ?? "general"
                        let firstType = profile?.consultationTypes.first ?? "new_patient"
                        AppNavigation.shared.requestQuickStart(
                            specialty: specialty,
                            consultationType: firstType
                        )
                    case "session":
                        let sessionID = url.pathComponents
                            .dropFirst()
                            .first ?? ""
                        guard !sessionID.isEmpty else { return }
                        AppNavigation.shared.requestTab(.sessions)
                        AppNavigation.shared.requestNote(sessionID: sessionID)
                    default:
                        break
                    }
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
            // Arm/clear the biometric lock based on background-idle time.
            appLock.handleScenePhase(newPhase)
        }
    }
}
