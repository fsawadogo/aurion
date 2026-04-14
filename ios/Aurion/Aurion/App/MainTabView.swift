import SwiftUI

/// Main tab bar — shown after login + onboarding.
/// Dashboard | Sessions | Profile
struct MainTabView: View {
    @EnvironmentObject var appState: AppState
    @EnvironmentObject var sessionManager: SessionManager
    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            DashboardView()
                .tabItem {
                    Label("Dashboard", systemImage: "house.fill")
                }
                .tag(0)

            SessionsInboxView()
                .tabItem {
                    Label("Sessions", systemImage: "list.clipboard")
                }
                .tag(1)

            ProfileView()
                .tabItem {
                    Label("Profile", systemImage: "person.circle")
                }
                .tag(2)
        }
        .tint(Color.aurionGold)
    }
}
