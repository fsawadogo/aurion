import SwiftUI

/// Branded launch screen — shown for ~1.4 s on cold app start before
/// `ContentView` hands off to auth / onboarding / dashboard. Used to open
/// the demo video so the audience reads "Aurion" before any UI flickers
/// past. Rendered inside `ContentView` (not the LaunchScreen storyboard)
/// so the gold-on-navy mark gets the proper aurionGold ramp instead of
/// the static system-color compromise the storyboard requires.
struct SplashView: View {
    /// Set to `false` after ~1.4 s so the parent can transition to the next
    /// route. Owned by the parent view so we don't duplicate timer state.
    @Binding var isVisible: Bool

    @State private var glow = false

    var body: some View {
        ZStack {
            AurionGradients.captureBackground.ignoresSafeArea()

            VStack(spacing: 24) {
                ZStack {
                    Circle()
                        .fill(Color.aurionGold.opacity(glow ? 0.18 : 0.08))
                        .frame(width: 160, height: 160)
                        .blur(radius: 24)
                    Image(systemName: "waveform.badge.magnifyingglass")
                        .font(.system(size: 56, weight: .light))
                        .foregroundColor(.aurionGold)
                }

                VStack(spacing: 8) {
                    Text("Aurion")
                        .font(.system(size: 42, weight: .semibold))
                        .tracking(-1.2)
                        .foregroundColor(.white)
                    Text("Clinical intelligence \u{2014} captured")
                        .font(.system(size: 14, weight: .regular))
                        .tracking(0.6)
                        .foregroundColor(Color(red: 183/255, green: 192/255, blue: 214/255))
                }
            }
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 1.0).repeatForever(autoreverses: true)) {
                glow = true
            }
            Task {
                try? await Task.sleep(nanoseconds: 1_400_000_000)
                withAnimation(.easeInOut(duration: 0.4)) {
                    isVisible = false
                }
            }
        }
    }
}
