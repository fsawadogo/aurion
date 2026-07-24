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
            AurionBrandScreenBackground()

            // Soft halo behind the lockup in the logo's circuit purple —
            // breathes so the splash has motion before the lockup itself
            // arrives. Sits *behind* the lockup image so it reads as glow,
            // not as a circle on top.
            ZStack {
                Circle()
                    .fill(
                        Color(red: 166/255, green: 149/255, blue: 214/255) // #A695D6
                            .opacity(glow ? 0.30 : 0.12)
                    )
                    .frame(width: 300, height: 300)
                    .blur(radius: 56)

                AurionLogoLockup(size: 1.05)
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
