import SwiftUI
import UIKit

// MARK: - Adaptive Color Helper

extension Color {
    /// Create a color that adapts to light/dark mode
    init(light: Color, dark: Color) {
        self.init(uiColor: UIColor { traits in
            traits.userInterfaceStyle == .dark
                ? UIColor(dark)
                : UIColor(light)
        })
    }
}

// MARK: - Aurion Brand Colors (Fixed — same in both modes)

extension Color {
    /// Aurion Navy — primary brand color #0D1B3E
    static let aurionNavy = Color(red: 13/255, green: 27/255, blue: 62/255)
    /// Aurion Navy Light — for gradient endpoints
    static let aurionNavyLight = Color(red: 20/255, green: 35/255, blue: 80/255)
    /// Aurion Navy Dark — deeper navy for depth
    static let aurionNavyDark = Color(red: 6/255, green: 12/255, blue: 35/255)
    /// Aurion Gold — accent color #C9A84C
    static let aurionGold = Color(red: 201/255, green: 168/255, blue: 76/255)
    /// Aurion Gold Light — shimmer endpoint
    static let aurionGoldLight = Color(red: 218/255, green: 195/255, blue: 120/255)
    /// Conflict amber
    static let aurionAmber = Color(red: 255/255, green: 179/255, blue: 0/255)
}

// MARK: - Adaptive Colors (Light/Dark)

extension Color {
    /// Background — adapts to dark mode
    static let aurionBackground = Color(
        light: Color(red: 245/255, green: 245/255, blue: 247/255),
        dark: Color(red: 28/255, green: 28/255, blue: 30/255)
    )
    /// Card surface — white in light, dark gray in dark
    static let aurionCardBackground = Color(
        light: .white,
        dark: Color(red: 44/255, green: 44/255, blue: 46/255)
    )
    /// Primary text — navy in light, white in dark
    static let aurionTextPrimary = Color(
        light: Color(red: 13/255, green: 27/255, blue: 62/255),
        dark: .white
    )
    /// Input field background
    static let aurionFieldBackground = Color(
        light: Color(red: 245/255, green: 245/255, blue: 247/255),
        dark: Color(red: 58/255, green: 58/255, blue: 60/255)
    )
    /// Card shadow color
    static let aurionShadow = Color(
        light: Color.black.opacity(0.06),
        dark: Color.black.opacity(0.3)
    )
}

// MARK: - Gradients

enum AurionGradients {
    /// Navy gradient for login, capture backgrounds — same in both modes
    static let navyBackground = LinearGradient(
        colors: [Color.aurionNavyDark, Color.aurionNavy, Color.aurionNavyLight.opacity(0.8)],
        startPoint: .topLeading,
        endPoint: .bottomTrailing
    )

    /// Gold shimmer for progress rings and accent bars
    static let goldShimmer = LinearGradient(
        colors: [Color.aurionGold, Color.aurionGoldLight],
        startPoint: .leading,
        endPoint: .trailing
    )

    /// Subtle radial glow for stat cards
    static let cardGlow = RadialGradient(
        colors: [Color.aurionGold.opacity(0.08), Color.clear],
        center: .topLeading,
        startRadius: 0,
        endRadius: 150
    )
}

// MARK: - Card Modifiers

struct AurionCardModifier: ViewModifier {
    @Environment(\.colorScheme) var colorScheme

    func body(content: Content) -> some View {
        content
            .padding(16)
            .background(Color.aurionCardBackground)
            .cornerRadius(16)
            .shadow(
                color: colorScheme == .dark ? .clear : .black.opacity(0.06),
                radius: 12, x: 0, y: 4
            )
    }
}

struct AurionElevatedCardModifier: ViewModifier {
    @Environment(\.colorScheme) var colorScheme

    func body(content: Content) -> some View {
        content
            .padding(16)
            .background(Color.aurionCardBackground)
            .cornerRadius(16)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.aurionGold.opacity(0.12), lineWidth: 1)
            )
            .shadow(
                color: colorScheme == .dark ? .clear : .black.opacity(0.10),
                radius: 16, x: 0, y: 6
            )
    }
}

extension View {
    func aurionCard() -> some View {
        modifier(AurionCardModifier())
    }

    func aurionElevatedCard() -> some View {
        modifier(AurionElevatedCardModifier())
    }
}

// MARK: - Text Style Extensions

extension View {
    func aurionSectionHeader() -> some View {
        self
            .font(.subheadline)
            .fontWeight(.semibold)
            .foregroundColor(.secondary)
            .textCase(.uppercase)
            .tracking(0.5)
    }

    func aurionHeadline() -> some View {
        self
            .font(.title2)
            .fontWeight(.bold)
            .foregroundColor(.aurionTextPrimary)
    }

    func aurionClaimText() -> some View {
        self
            .font(.body)
            .foregroundColor(.aurionTextPrimary)
    }

    func aurionMetadataLabel() -> some View {
        self
            .font(.caption2)
            .foregroundColor(.secondary)
    }
}

// MARK: - Navigation Bar Modifier

struct AurionNavBarModifier: ViewModifier {
    func body(content: Content) -> some View {
        content
            .toolbarBackground(Color.aurionNavy, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
    }
}

extension View {
    func aurionNavBar() -> some View {
        modifier(AurionNavBarModifier())
    }
}

// MARK: - Button Styles

struct AurionPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.headline)
            .foregroundColor(.white)
            .padding(.horizontal, 32)
            .padding(.vertical, 14)
            .background(Color.aurionGold)
            .cornerRadius(12)
            .shadow(color: Color.aurionGold.opacity(0.3), radius: 8, y: 4)
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0)
            .opacity(configuration.isPressed ? 0.9 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

struct AurionSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline)
            .foregroundColor(.aurionTextPrimary)
            .padding(.horizontal, 24)
            .padding(.vertical, 12)
            .background(Color.aurionFieldBackground)
            .cornerRadius(10)
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0)
            .opacity(configuration.isPressed ? 0.7 : 1.0)
            .animation(.easeInOut(duration: 0.15), value: configuration.isPressed)
    }
}

// MARK: - Haptic Feedback

enum AurionHaptics {
    static func impact(_ style: UIImpactFeedbackGenerator.FeedbackStyle = .medium) {
        UIImpactFeedbackGenerator(style: style).impactOccurred()
    }

    static func notification(_ type: UINotificationFeedbackGenerator.FeedbackType) {
        UINotificationFeedbackGenerator().notificationOccurred(type)
    }

    static func selection() {
        UISelectionFeedbackGenerator().selectionChanged()
    }
}

// MARK: - Animation Presets

enum AurionAnimation {
    static let smooth = Animation.easeInOut(duration: 0.35)
    static let spring = Animation.spring(response: 0.4, dampingFraction: 0.75)
    static let slow = Animation.easeInOut(duration: 0.6)
    static let pulse = Animation.easeInOut(duration: 1.0).repeatForever(autoreverses: true)
}

// MARK: - Transition Presets

enum AurionTransition {
    static let fadeSlide = AnyTransition.asymmetric(
        insertion: .move(edge: .trailing).combined(with: .opacity),
        removal: .move(edge: .leading).combined(with: .opacity)
    )
    static let scaleIn = AnyTransition.scale(scale: 0.9).combined(with: .opacity)
    static let fadeUp = AnyTransition.move(edge: .bottom).combined(with: .opacity)
}

// MARK: - Circular Progress Ring

struct CircularProgressRing: View {
    let progress: Double
    let color: Color
    var lineWidth: CGFloat = 5
    var size: CGFloat = 52

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.aurionNavy.opacity(0.1), lineWidth: lineWidth)
                .frame(width: size, height: size)
            Circle()
                .trim(from: 0, to: progress)
                .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
                .frame(width: size, height: size)
                .rotationEffect(.degrees(-90))
                .animation(AurionAnimation.smooth, value: progress)
        }
    }
}
