import SwiftUI

/// Main tab bar — shown after login + onboarding.
/// Custom AurionTabBar matching the design system: frosted glass, gold accent,
/// 24pt icons that swap to filled variants on active, 10pt labels.
/// Order per design: Home → Sessions → Profile → Devices.
struct MainTabView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var sessionManager: SessionManager
    @State private var selection: String = "home"

    private var tabs: [AurionTabItem] {
        [
            AurionTabItem(id: "home",     label: L("tabs.home"),     iconOutline: "house",                       iconFilled: "house.fill"),
            AurionTabItem(id: "sessions", label: L("tabs.sessions"), iconOutline: "list.bullet.rectangle",       iconFilled: "list.bullet.rectangle.fill"),
            AurionTabItem(id: "profile",  label: L("tabs.profile"),  iconOutline: "person",                      iconFilled: "person.fill"),
            AurionTabItem(id: "devices",  label: L("tabs.devices"),  iconOutline: "iphone",                      iconFilled: "iphone.gen3"),
        ]
    }

    var body: some View {
        VStack(spacing: 0) {
            ZStack {
                switch selection {
                case "home":     DashboardView()
                case "sessions": SessionsInboxView()
                case "profile":  ProfileView()
                case "devices":  DeviceHubView()
                default:         DashboardView()
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            AurionTabBar(selection: $selection, items: tabs)
        }
        .background(Color.aurionBackground.ignoresSafeArea())
        .ignoresSafeArea(.keyboard)
    }
}
