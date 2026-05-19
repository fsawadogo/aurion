import SwiftUI

/// Type-safe identity for the four main app tabs. ``RawValue`` strings
/// match the prior string-based selection so user-visible @AppStorage
/// or @SceneStorage of the prior identifier still resolves.
enum MainTab: String, Hashable, CaseIterable, Identifiable {
    case home, sessions, profile, devices

    var id: String { rawValue }

    var label: String {
        switch self {
        case .home:     return L("tabs.home")
        case .sessions: return L("tabs.sessions")
        case .profile:  return L("tabs.profile")
        case .devices:  return L("tabs.devices")
        }
    }

    /// SF Symbol for the inactive state. iOS renders the filled
    /// variant automatically for the active tab; we don't manage
    /// outlined/filled pairs by hand any more.
    var systemImage: String {
        switch self {
        case .home:     return "house"
        case .sessions: return "list.bullet.rectangle"
        case .profile:  return "person"
        case .devices:  return "iphone"
        }
    }
}

/// Main tab bar — shown after login + onboarding.
///
/// Uses Apple's native ``TabView`` with the iOS 18 ``Tab`` API and
/// ``.tabViewStyle(.sidebarAdaptable)`` so the same code yields:
///
/// - iPhone / iPad compact: translucent bottom tab bar (iOS 26
///   Liquid Glass on the deployment target).
/// - iPad regular: native sidebar in landscape, bottom bar in
///   portrait — no per-size-class code required.
///
/// Brand colour applied via ``.tint(.aurionGold)`` so the active tab
/// reads gold. Inactive uses system secondary.
struct MainTabView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var sessionManager: SessionManager
    /// Persisted across launches via @SceneStorage so quitting on the
    /// Profile tab and reopening lands you back there.
    @SceneStorage("MainTabView.selection") private var selection: MainTab = .home

    var body: some View {
        TabView(selection: $selection) {
            Tab(MainTab.home.label, systemImage: MainTab.home.systemImage, value: MainTab.home) {
                DashboardView()
            }
            Tab(MainTab.sessions.label, systemImage: MainTab.sessions.systemImage, value: MainTab.sessions) {
                SessionsInboxView()
            }
            Tab(MainTab.profile.label, systemImage: MainTab.profile.systemImage, value: MainTab.profile) {
                ProfileView()
            }
            Tab(MainTab.devices.label, systemImage: MainTab.devices.systemImage, value: MainTab.devices) {
                DeviceHubView()
            }
        }
        .tabViewStyle(.sidebarAdaptable)
        .tint(.aurionGold)
    }
}
