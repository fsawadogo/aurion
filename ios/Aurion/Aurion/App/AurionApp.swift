import SwiftUI
import UIKit

/// AUTH-UNIVERSAL-LINKS — UIKit bridge for cold-launch Universal Links.
///
/// On a COLD launch (Aurion not in memory, user taps the reset-password
/// link in Mail/Messages), SwiftUI's `.onContinueUserActivity(...)`
/// modifier fires before the `ContentView` hierarchy is fully attached,
/// and the activity is silently dropped — every pilot user's first
/// encounter with the reset flow lands them on the Sign In screen with
/// no way to actually enter a new password. Confirmed on Faical's
/// 2026-06-06 ~22:11 EDT smoke test.
///
/// `application(_:continue:restorationHandler:)` runs even before the
/// SwiftUI hierarchy exists, so we capture the activity here and write
/// the token straight onto the shared `ResetLinkPayload.shared`
/// instance that `AurionApp.init` aliases the `@StateObject` to. The
/// SwiftUI view picks it up the moment its `.fullScreenCover(item:)`
/// modifier becomes active.
///
/// Defensive note: the delegate is the SOLE entry point for cold
/// launches. The warm-path `.onContinueUserActivity` handler in
/// `AurionApp.body` covers the background→foreground case where the
/// app is already alive and SwiftUI is ready.
final class AurionAppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        continue userActivity: NSUserActivity,
        restorationHandler: @escaping ([UIUserActivityRestoring]?) -> Void
    ) -> Bool {
        guard
            userActivity.activityType == NSUserActivityTypeBrowsingWeb,
            let url = userActivity.webpageURL
        else { return false }
        // Same extractor the warm path uses — single source of truth.
        guard let token = MainActor.assumeIsolated({ ResetLinkExtractor.token(from: url) }) else {
            return false
        }
        MainActor.assumeIsolated {
            ResetLinkPayload.shared.token = token
        }
        return true
    }
}

@main
struct AurionApp: App {
    @UIApplicationDelegateAdaptor(AurionAppDelegate.self) private var appDelegate
    @StateObject private var appState = AppState()
    @StateObject private var remoteConfig = RemoteConfig.shared
    @StateObject private var appLock = AppLockManager()
    /// AUTH-UNIVERSAL-LINKS — bus for an inbound reset-password token
    /// extracted from a Universal Link. Written by EITHER the cold-
    /// launch ``AurionAppDelegate`` (the only path that fires when
    /// Aurion isn't already running — every pilot user's first reset
    /// tap) OR the warm-path ``.onContinueUserActivity`` handler in
    /// `body` below. Both write to the same singleton-aliased instance
    /// so ``ContentView``'s reset-cover binding always observes the
    /// token regardless of which path delivered it.
    @StateObject private var resetLinkPayload: ResetLinkPayload = ResetLinkPayload.shared
    @Environment(\.scenePhase) private var scenePhase

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(appState)
                .environmentObject(remoteConfig)
                .environmentObject(appLock)
                .environmentObject(resetLinkPayload)
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
                        // Keep config fresh while signed in (30s poll) so a
                        // mid-shift AppConfig push — e.g. enabling clip
                        // cadence / a clips-or-hybrid visual-evidence mode —
                        // reaches the device without a re-login. Idempotent.
                        remoteConfig.startPolling()
                        // Eager-load the physician profile on sign-in / cold
                        // launch. Without this, `physicianProfile` stays nil
                        // until the Profile tab is opened, so the dashboard
                        // Quick Start falls back to GENERAL defaults and the
                        // Siri/widget deep-link starts a "general"-template
                        // session for the wrong specialty (#278). `try?` —
                        // a failed fetch leaves nil, which now renders the
                        // skeleton state rather than misleading defaults.
                        if appState.physicianProfile == nil {
                            appState.physicianProfile = try? await APIClient.shared.getProfile()
                        }
                        // #418 — adopt the physician's chosen accent so the
                        // chrome matches their portal choice cross-device.
                        // The Theme gold tokens read this on the next render.
                        if let accent = appState.physicianProfile?.accentColor {
                            appState.accentColor = accent
                        }
                        // Drain any encounters captured offline in a prior
                        // session and arm reconnect-driven sync. Gated on auth
                        // because the upload needs a bearer token.
                        OfflineUploadQueue.shared.start()
                    } else {
                        // Signed out — stop the background config poll.
                        remoteConfig.stopPolling()
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
                // AUTH-UNIVERSAL-LINKS — Universal Link tap.
                // iOS hands us the original `https://portal.aurionclinical.com/...`
                // URL on a `NSUserActivityTypeBrowsingWeb` activity when
                // the user taps a Universal-Link-matched URL (e.g. the
                // reset-password email link) and the AASA file claims it.
                //
                // We defensively validate host + path + a non-empty
                // `token` query param before extracting — random Safari
                // URLs that happen to land here (e.g. a stale activity
                // restored on cold launch) get rejected without
                // surfacing UI. The single source of truth is the
                // shared `resetLinkPayload`; `ContentView` watches it
                // and presents the reset full-screen cover.
                .onContinueUserActivity(NSUserActivityTypeBrowsingWeb) { activity in
                    // Warm-path Universal Link tap (Aurion already alive).
                    // Cold-launch path goes through AurionAppDelegate.
                    // Both call ResetLinkExtractor so validation rules
                    // stay in lockstep across the two entry points.
                    guard
                        let url = activity.webpageURL,
                        let token = ResetLinkExtractor.token(from: url)
                    else { return }
                    // Set on the shared payload bus — never logged.
                    resetLinkPayload.token = token
                }
                // Deep-link entry points (custom scheme):
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
                // Re-pull AppConfig on every foreground so a config change
                // pushed while the app was backgrounded is live before the
                // next record-start (the cadence/visual-evidence mode is
                // read at that moment). Cheap GET; no-op fields on failure.
                if appState.isAuthenticated {
                    Task { @MainActor in await remoteConfig.refresh() }
                }
            }
            // Arm/clear the biometric lock based on background-idle time.
            appLock.handleScenePhase(newPhase)
        }
    }
}
