import SwiftUI

/// Animated shimmer placeholder for premium loading states. Compose several
/// into a content-shaped skeleton (a session row, a note document) so the
/// layout appears to "form" instead of showing a bare spinner.
///
/// A faint base block with a soft highlight sweeping left→right on a loop;
/// adapts to light/dark. Honors Reduce Motion by falling back to a gentle
/// opacity pulse, and is hidden from VoiceOver (it conveys no information).
struct AurionSkeleton: View {
    var cornerRadius: CGFloat = AurionRadius.sm

    @Environment(\.colorScheme) private var scheme
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var animate = false

    var body: some View {
        let base = scheme == .dark
            ? Color.white.opacity(0.10)
            : Color.aurionNavy.opacity(0.07)
        let highlight = scheme == .dark
            ? Color.white.opacity(0.18)
            : Color.white.opacity(0.6)
        let shape = RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)

        shape
            .fill(base)
            .overlay {
                if !reduceMotion {
                    GeometryReader { geo in
                        let w = geo.size.width
                        LinearGradient(
                            colors: [.clear, highlight, .clear],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                        .frame(width: w * 0.7)
                        // Sweeps from fully off the left edge to off the right.
                        .offset(x: animate ? w : -w * 0.7)
                    }
                }
            }
            .clipShape(shape)
            // Reduce Motion: no sweep — a slow opacity pulse instead.
            .opacity(reduceMotion && animate ? 0.5 : 1.0)
            .onAppear {
                guard !animate else { return }
                let motion = reduceMotion
                    ? Animation.easeInOut(duration: 0.9).repeatForever(autoreverses: true)
                    : Animation.linear(duration: 1.15).repeatForever(autoreverses: false)
                withAnimation(motion) { animate = true }
            }
            .accessibilityHidden(true)
    }
}
