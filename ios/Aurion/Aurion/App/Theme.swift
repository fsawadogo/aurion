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

// MARK: - Aurion Brand Colors (from Design/colors_and_type.css tokens)

extension Color {
    // Navy ramp
    // Brand navy retuned to match the Aurion logo PNG's background exactly
    // (sampled from `Logo.png` corner pixels: RGB(12, 27, 55) = #0C1B37).
    // Any surface using `aurionNavy` will now blend seamlessly with the
    // lockup — no visible "logo box" sitting on top.
    static let aurionNavy = Color(red: 12/255, green: 27/255, blue: 55/255)       // #0C1B37 (brand — matches Logo.png)
    static let aurionNavyLight = Color(red: 22/255, green: 40/255, blue: 78/255)  // #16284E (lighter shade, kept for accents)
    static let aurionNavyDark = Color(red: 8/255, green: 18/255, blue: 38/255)    // #081226 (deeper, for gradient base)

    // Gold ramp
    static let aurionGold = Color(red: 201/255, green: 168/255, blue: 76/255)      // #C9A84C (brand)
    static let aurionGoldLight = Color(red: 229/255, green: 208/255, blue: 130/255) // #E5D082
    static let aurionGoldDark = Color(red: 181/255, green: 149/255, blue: 61/255)  // #B5953D
    static let aurionGoldBg = Color(red: 251/255, green: 246/255, blue: 230/255)   // #FBF6E6

    // Semantic — foreground
    static let aurionAmber = Color(red: 217/255, green: 148/255, blue: 31/255)     // #D9941F
    static let aurionGreen = Color(red: 46/255, green: 158/255, blue: 106/255)     // #2E9E6A
    static let aurionRed = Color(red: 217/255, green: 53/255, blue: 43/255)        // #D9352B
    static let aurionBlue = Color(red: 45/255, green: 108/255, blue: 223/255)      // #2D6CDF

    // Semantic — soft backgrounds (used by status pills, conflict cards, etc.)
    static let aurionAmberBg = Color(red: 251/255, green: 241/255, blue: 220/255)  // #FBF1DC
    static let aurionGreenBg = Color(red: 230/255, green: 245/255, blue: 238/255)  // #E6F5EE
    static let aurionRedBg = Color(red: 251/255, green: 231/255, blue: 229/255)    // #FBE7E5
    static let aurionBlueBg = Color(red: 230/255, green: 238/255, blue: 250/255)   // #E6EEFA

    // Status text (matches AURION.* in components.jsx)
    static let aurionStatusDone = Color(red: 31/255, green: 122/255, blue: 79/255)     // #1F7A4F
    static let aurionStatusPending = Color(red: 142/255, green: 115/255, blue: 48/255) // #8E7330
    static let aurionStatusConflict = Color(red: 154/255, green: 110/255, blue: 20/255) // #9A6E14
    static let aurionStatusExported = Color(red: 33/255, green: 78/255, blue: 156/255)  // #214E9C
    static let aurionStatusArchived = Color(red: 74/255, green: 81/255, blue: 96/255)   // #4A5160

    // Field surface (slightly warmer than canvas)
    static let aurionSurfaceAlt = Color(red: 238/255, green: 240/255, blue: 243/255)  // #EEF0F3

    // Note section accents (left-border tints in note review)
    static let aurionSectionInfo = Color(red: 45/255, green: 108/255, blue: 223/255)   // blue-500
    static let aurionSectionExam = Color(red: 46/255, green: 158/255, blue: 106/255)   // green-500
    static let aurionSectionAssessment = Color(red: 217/255, green: 148/255, blue: 31/255) // amber-500
    static let aurionSectionPlan = Color(red: 13/255, green: 27/255, blue: 62/255)     // navy-500
}

// MARK: - Adaptive Colors (Light/Dark)

extension Color {
    // Canvas — #F8F9FA light, #0A1530 dark
    static let aurionBackground = Color(
        light: Color(red: 248/255, green: 249/255, blue: 250/255),
        dark: Color(red: 10/255, green: 21/255, blue: 48/255)
    )
    // Surface — white light, #152348 dark
    static let aurionCardBackground = Color(
        light: .white,
        dark: Color(red: 21/255, green: 35/255, blue: 72/255)
    )
    // Primary text — navy light, white dark
    static let aurionTextPrimary = Color(
        light: Color(red: 13/255, green: 27/255, blue: 62/255),
        dark: .white
    )
    // Secondary text — #6B7280 light, #B7C0D6 dark
    static let aurionTextSecondary = Color(
        light: Color(red: 107/255, green: 114/255, blue: 128/255),
        dark: Color(red: 183/255, green: 192/255, blue: 214/255)
    )
    // Field background — #EEF0F3 light, #1B2C56 dark
    static let aurionFieldBackground = Color(
        light: Color(red: 238/255, green: 240/255, blue: 243/255),
        dark: Color(red: 27/255, green: 44/255, blue: 86/255)
    )
    // Hairline border
    static let aurionBorder = Color(
        light: Color(red: 13/255, green: 27/255, blue: 62/255).opacity(0.06),
        dark: Color.white.opacity(0.06)
    )
}

// MARK: - Gradients

enum AurionGradients {
    // Login + capture: radial navy gradient (design system spec)
    static let navyBackground = LinearGradient(
        colors: [Color.aurionNavyLight, Color.aurionNavy],
        startPoint: .top,
        endPoint: .bottom
    )

    // Gold accent gradient for avatars — radial with off-center highlight
    // matches design: radial-gradient(circle at 30% 30%, #E5C97A, #B5953D)
    static let goldAvatar = RadialGradient(
        colors: [Color.aurionGoldLight, Color.aurionGoldDark],
        center: UnitPoint(x: 0.3, y: 0.3),
        startRadius: 2,
        endRadius: 30
    )

    // Linear gold for progress bars and other surfaces
    static let goldShimmer = LinearGradient(
        colors: [Color.aurionGold, Color.aurionGoldLight],
        startPoint: .leading,
        endPoint: .trailing
    )

    /// Capture-screen radial: ellipse-at-top from navy-light → navy → navy-dark.
    /// SwiftUI radials are circular not elliptical, but the visual effect matches.
    /// Source: `radial-gradient(ellipse at top, #1A2E5C 0%, #0D1B3E 70%, #0A1530 100%)`
    static let captureBackground = RadialGradient(
        gradient: Gradient(stops: [
            .init(color: .aurionNavyLight, location: 0),
            .init(color: .aurionNavy, location: 0.7),
            .init(color: .aurionNavyDark, location: 1.0),
        ]),
        center: UnitPoint(x: 0.5, y: 0),
        startRadius: 0,
        endRadius: 700
    )
}

// MARK: - Card Modifiers

struct AurionCardModifier: ViewModifier {
    @Environment(\.colorScheme) var colorScheme

    func body(content: Content) -> some View {
        content
            .padding(20)
            .background(Color.aurionCardBackground)
            .cornerRadius(16)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
            .shadow(
                color: colorScheme == .dark ? .clear : Color(red: 13/255, green: 27/255, blue: 62/255).opacity(0.04),
                radius: 8, x: 0, y: 2
            )
            .shadow(
                color: colorScheme == .dark ? .clear : Color(red: 13/255, green: 27/255, blue: 62/255).opacity(0.06),
                radius: 16, x: 0, y: 4
            )
    }
}

struct AurionElevatedCardModifier: ViewModifier {
    @Environment(\.colorScheme) var colorScheme

    func body(content: Content) -> some View {
        content
            .padding(20)
            .background(Color.aurionCardBackground)
            .cornerRadius(16)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.aurionGold.opacity(0.15), lineWidth: 1.5)
            )
            .shadow(
                color: colorScheme == .dark ? .clear : Color(red: 13/255, green: 27/255, blue: 62/255).opacity(0.06),
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

    /// Standard 2-layer card shadow per design system:
    /// `0 1px 2px rgba(13,27,62,0.04), 0 4px 16px rgba(13,27,62,0.06)`
    func aurionCardShadow() -> some View {
        self
            .shadow(
                color: Color(red: 13/255, green: 27/255, blue: 62/255).opacity(0.04),
                radius: 1, x: 0, y: 1
            )
            .shadow(
                color: Color(red: 13/255, green: 27/255, blue: 62/255).opacity(0.06),
                radius: 8, x: 0, y: 4
            )
    }
}

// MARK: - Text Style Extensions

extension View {
    func aurionClaimText() -> some View {
        self
            .font(.body)
            .foregroundColor(.aurionTextPrimary)
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
            .font(.system(size: 16, weight: .semibold))
            .foregroundColor(.aurionNavy)
            .padding(.horizontal, 22)
            .padding(.vertical, 14)
            .background(Color.aurionGold)
            .cornerRadius(12)
            .shadow(
                color: Color(red: 201/255, green: 168/255, blue: 76/255).opacity(0.24),
                radius: 8, x: 0, y: 4
            )
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
    }
}

struct AurionSecondaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.system(size: 16, weight: .semibold))
            .foregroundColor(.aurionNavy)
            .padding(.horizontal, 22)
            .padding(.vertical, 14)
            .background(Color.aurionCardBackground)
            .cornerRadius(12)
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
            .scaleEffect(configuration.isPressed ? 0.97 : 1.0)
            .animation(.easeOut(duration: 0.12), value: configuration.isPressed)
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
    static let micro = Animation.easeOut(duration: AurionDuration.micro)
    /// iOS-standard cubic-bezier(0.32, 0.72, 0, 1) — the "smooth" easing
    /// the design system specifies for sheet entries and content swaps.
    static let smooth = Animation.timingCurve(0.32, 0.72, 0, 1, duration: AurionDuration.medium)
    static let spring = Animation.spring(response: 0.32, dampingFraction: 0.82)
    static let slow = Animation.timingCurve(0.32, 0.72, 0, 1, duration: AurionDuration.long)
    static let pulse = Animation.easeInOut(duration: 1.6).repeatForever(autoreverses: true)
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

// MARK: - Spacing Tokens

enum AurionSpacing {
    static let xxs: CGFloat = 4    // --s-1
    static let xs: CGFloat = 8     // --s-2
    static let sm: CGFloat = 12    // --s-3
    static let md: CGFloat = 16    // --s-4
    static let lg: CGFloat = 20    // --s-5 (screen edge iPhone)
    static let xl: CGFloat = 24    // --s-6
    static let xxl: CGFloat = 32   // --s-8 (screen edge iPad)
    static let xxxl: CGFloat = 40  // --s-10
    static let huge: CGFloat = 56  // --s-14

    static let edgeIPhone: CGFloat = 20
    static let edgeIPad: CGFloat = 32
    static let hitMin: CGFloat = 44
    static let topBar: CGFloat = 44
    static let tabBar: CGFloat = 49
}

// MARK: - Radii

enum AurionRadius {
    static let xs: CGFloat = 6      // --r-xs
    static let sm: CGFloat = 10     // --r-sm
    static let md: CGFloat = 12     // --r-md  (buttons)
    static let lg: CGFloat = 16     // --r-lg  (cards)
    static let xl: CGFloat = 20     // --r-xl  (sheets)
    static let xxl: CGFloat = 28    // --r-2xl
}

// MARK: - Duration

enum AurionDuration {
    static let micro: Double = 0.12   // --d-micro
    static let short: Double = 0.20   // --d-short
    static let medium: Double = 0.32  // --d-medium
    static let long: Double = 0.50    // --d-long
}

/// iOS-standard "smooth" easing (cubic-bezier(0.32, 0.72, 0, 1)) used by
/// progress bars, sheet entries, and content swaps in the design system.
extension Animation {
    static let aurionIOS: Animation = .timingCurve(0.32, 0.72, 0, 1, duration: AurionDuration.medium)
    static let aurionState: Animation = .timingCurve(0.4, 0, 0.2, 1, duration: AurionDuration.short)
}

// MARK: - Clinical Status Colors

extension Color {
    static let clinicalNormal = Color.aurionGreen
    static let clinicalWarning = Color.aurionAmber
    static let clinicalAlert = Color.aurionRed
    static let clinicalInfo = Color.aurionBlue
    static let clinicalNeutral = Color.aurionTextSecondary
}

// MARK: - Typography Scale

extension View {
    // 34pt bold, tight tracking (--t-large-title)
    func aurionLargeTitle() -> some View {
        self
            .font(.system(size: 34, weight: .bold))
            .tracking(-0.68)
            .foregroundColor(.aurionTextPrimary)
    }

    // 28pt bold, tight tracking (--t-title-1)
    func aurionDisplay() -> some View {
        self
            .font(.system(size: 28, weight: .bold))
            .tracking(-0.5)
            .foregroundColor(.aurionTextPrimary)
    }

    // 20pt semibold (--t-title-3)
    func aurionTitle3() -> some View {
        self
            .font(.system(size: 20, weight: .semibold))
            .tracking(-0.2)
            .foregroundColor(.aurionTextPrimary)
    }

    // 22pt semibold (--t-title-2)
    func aurionTitle() -> some View {
        self
            .font(.system(size: 22, weight: .semibold))
            .tracking(-0.3)
            .foregroundColor(.aurionTextPrimary)
    }

    // 17pt semibold (--t-headline)
    func aurionHeadline() -> some View {
        self
            .font(.system(size: 17, weight: .semibold))
            .foregroundColor(.aurionTextPrimary)
    }

    // 17pt regular (--t-body)
    func aurionBody() -> some View {
        self
            .font(.system(size: 17, weight: .regular))
            .foregroundColor(.aurionTextPrimary)
    }

    // 15pt medium (--t-subheadline)
    func aurionCallout() -> some View {
        self
            .font(.system(size: 15, weight: .medium))
            .foregroundColor(.aurionTextSecondary)
    }

    // 13pt regular (--t-footnote)
    func aurionCaption() -> some View {
        self
            .font(.system(size: 13, weight: .regular))
            .foregroundColor(.aurionTextSecondary)
    }

    // 11pt semibold uppercase (--t-caption-2)
    func aurionMicro() -> some View {
        self
            .font(.system(size: 11, weight: .semibold))
            .tracking(0.8)
            .textCase(.uppercase)
            .foregroundColor(.aurionTextSecondary)
    }
}

// MARK: - Aurion Tab Bar

/// Frosted-glass bottom tab bar matching the design system AurionTabBar:
/// rgba(255,255,255,0.92) background, 1px hairline top border, 24pt icons,
/// 10pt labels (600 active / 500 inactive), gold/fg3 colors, filled icon variants on active.
struct AurionTabItem: Identifiable, Hashable {
    let id: String
    let label: String
    let iconOutline: String
    let iconFilled: String
}

struct AurionTabBar: View {
    @Binding var selection: String
    let items: [AurionTabItem]

    var body: some View {
        VStack(spacing: 0) {
            Rectangle()
                .fill(Color.aurionBorder)
                .frame(height: 1)

            HStack(spacing: 0) {
                ForEach(items) { item in
                    let on = selection == item.id
                    Button {
                        AurionHaptics.selection()
                        selection = item.id
                    } label: {
                        VStack(spacing: 2) {
                            Image(systemName: on ? item.iconFilled : item.iconOutline)
                                .font(.system(size: 22, weight: on ? .semibold : .regular))
                                .foregroundColor(on ? .aurionGold : .aurionTabInactive)
                                .frame(height: 26)

                            Text(item.label)
                                .font(.system(size: 10, weight: on ? .semibold : .medium))
                                .foregroundColor(on ? .aurionGold : .aurionTabInactive)
                        }
                        .frame(maxWidth: .infinity, minHeight: 44)
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.top, 8)
            .padding(.bottom, 4)
        }
        .background(.ultraThinMaterial)
    }
}

extension Color {
    /// Inactive tab tint — matches design fg3 #9AA0AC
    static let aurionTabInactive = Color(
        light: Color(red: 154/255, green: 160/255, blue: 172/255),
        dark: Color(red: 154/255, green: 160/255, blue: 172/255)
    )
}

// MARK: - Status Badge

struct StatusBadge: View {
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 5) {
            Circle()
                .fill(color)
                .frame(width: 6, height: 6)
            Text(text)
                .font(.system(size: 11, weight: .semibold))
                .tracking(0.4)
        }
        .foregroundColor(color)
        .padding(.horizontal, 10)
        .padding(.vertical, 5)
        .background(color.opacity(0.12))
        .clipShape(Capsule())
    }
}

// MARK: - Empty State View

struct EmptyStateView: View {
    let icon: String
    let title: String
    let subtitle: String

    var body: some View {
        VStack(spacing: AurionSpacing.md) {
            Image(systemName: icon)
                .font(.system(size: 48))
                .foregroundColor(.secondary.opacity(0.4))

            Text(title)
                .font(.headline)
                .foregroundColor(.aurionTextPrimary)

            Text(subtitle)
                .font(.subheadline)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
        }
        .padding(AurionSpacing.xxl)
    }
}

// MARK: - Metric Card

struct MetricCard: View {
    let title: String
    let value: String
    let icon: String
    var trend: String? = nil

    var body: some View {
        VStack(alignment: .leading, spacing: AurionSpacing.xs) {
            HStack {
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.aurionGold)
                Spacer()
                if let trend = trend {
                    Text(trend)
                        .font(.system(size: 11, weight: .bold))
                        .foregroundColor(trend.hasPrefix("-") ? .clinicalAlert : .clinicalNormal)
                }
            }

            Text(value)
                .font(.system(size: 26, weight: .bold, design: .rounded))
                .foregroundColor(.aurionTextPrimary)

            Text(title)
                .font(.system(size: 12, weight: .medium))
                .foregroundColor(.secondary)
        }
        .aurionCard()
    }
}

// MARK: - Section Header

/// Matches design SectionTitle: 11pt 600, letter-spacing 0.10em (≈1.1pt), uppercase, fg-secondary.
/// Optional trailing slot (e.g. "See all" gold link) appears flush right.
struct SectionHeader<Trailing: View>: View {
    let title: String
    let count: Int?
    let trailing: Trailing

    init(title: String, count: Int? = nil, @ViewBuilder trailing: () -> Trailing) {
        self.title = title
        self.count = count
        self.trailing = trailing()
    }

    var body: some View {
        HStack(spacing: AurionSpacing.xs) {
            Text(title.uppercased())
                .font(.system(size: 11, weight: .semibold))
                .tracking(1.1)
                .foregroundColor(.aurionTextSecondary)

            if let count = count {
                Text("\(count)")
                    .font(.system(size: 10, weight: .bold))
                    .foregroundColor(.white)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.aurionGold)
                    .clipShape(Capsule())
            }

            Spacer()

            trailing
        }
    }
}

extension SectionHeader where Trailing == EmptyView {
    init(title: String, count: Int? = nil) {
        self.init(title: title, count: count, trailing: { EmptyView() })
    }
}

// MARK: - Aurion Logo (Hex Mark)

/// The Aurion hexagon logo with stylized "A" — matches assets/logo-mark.svg
struct AurionHexLogo: View {
    var size: CGFloat = 48
    var darkBackground = false

    private var scale: CGFloat { size / 64 }

    var body: some View {
        Canvas { context, canvasSize in
            let s = scale

            // Outer hexagon stroke
            var outerPath = Path()
            outerPath.move(to: CGPoint(x: 32 * s, y: 4 * s))
            outerPath.addLine(to: CGPoint(x: 56 * s, y: 18 * s))
            outerPath.addLine(to: CGPoint(x: 56 * s, y: 46 * s))
            outerPath.addLine(to: CGPoint(x: 32 * s, y: 60 * s))
            outerPath.addLine(to: CGPoint(x: 8 * s, y: 46 * s))
            outerPath.addLine(to: CGPoint(x: 8 * s, y: 18 * s))
            outerPath.closeSubpath()
            context.stroke(outerPath, with: .color(.aurionGold), lineWidth: 2.5 * s)

            // Inner hexagon stroke (subtle)
            var innerPath = Path()
            innerPath.move(to: CGPoint(x: 32 * s, y: 10 * s))
            innerPath.addLine(to: CGPoint(x: 51 * s, y: 21 * s))
            innerPath.addLine(to: CGPoint(x: 51 * s, y: 43 * s))
            innerPath.addLine(to: CGPoint(x: 32 * s, y: 54 * s))
            innerPath.addLine(to: CGPoint(x: 13 * s, y: 43 * s))
            innerPath.addLine(to: CGPoint(x: 13 * s, y: 21 * s))
            innerPath.closeSubpath()
            context.stroke(innerPath, with: .color(.aurionGold.opacity(0.5)), lineWidth: 1 * s)

            // "A" letterform
            let letterColor: Color = darkBackground ? .white : .aurionNavy
            var aPath = Path()
            aPath.move(to: CGPoint(x: 22 * s, y: 42 * s))
            aPath.addLine(to: CGPoint(x: 32 * s, y: 20 * s))
            aPath.addLine(to: CGPoint(x: 42 * s, y: 42 * s))
            context.stroke(aPath, with: .color(letterColor), style: StrokeStyle(lineWidth: 2.5 * s, lineCap: .round, lineJoin: .round))

            // "A" crossbar
            var crossbar = Path()
            crossbar.move(to: CGPoint(x: 26 * s, y: 35 * s))
            crossbar.addLine(to: CGPoint(x: 38 * s, y: 35 * s))
            context.stroke(crossbar, with: .color(letterColor), style: StrokeStyle(lineWidth: 2.5 * s, lineCap: .round))
        }
        .frame(width: size, height: size)
    }
}

/// Full Aurion brand lockup — golden A with comet/star mark, "Aurion"
/// wordmark, and "The gold standard in clinical AI" tagline, all baked
/// into a single PNG asset (`AurionLogoFull` in Assets.xcassets).
///
/// `size` scales the rendered height; the asset's intrinsic aspect ratio
/// is preserved. The `dark` parameter exists for API compatibility with
/// the previous hex-mark lockup but is no-op because the lockup image
/// already ships with its own navy backdrop. On light surfaces, fall
/// back to `AurionHexLogo` paired with text if a transparent variant is
/// needed in future.
struct AurionLogoLockup: View {
    var size: CGFloat = 1.0
    var dark = false

    var body: some View {
        Image("AurionLogoFull")
            .resizable()
            .scaledToFit()
            // 200pt base height tuned to the previous hex+wordmark footprint
            // at size=1.0 — login screens that passed size=1.2 now land at
            // 240pt, matching what they expected visually.
            .frame(height: 200 * size)
            .accessibilityLabel("Aurion — the gold standard in clinical AI")
    }
}

// MARK: - Shared Utilities

extension String {
    /// Converts snake_case keys like "orthopedic_surgery" to display form "Orthopedic Surgery".
    var displayFormatted: String {
        replacingOccurrences(of: "_", with: " ").capitalized
    }
}

/// Canonical session state → badge mapping. Used by DashboardView, SessionsInboxView, ProfileView.
/// Maps session state to (label, dot/text color, background color)
func sessionStateBadge(_ state: String) -> (text: String, color: Color) {
    switch state {
    case "EXPORTED": return (L("badge.exported"), Color.aurionBlue)
    case "REVIEW_COMPLETE": return (L("badge.ready"), Color.aurionGreen)
    case "PURGED": return (L("badge.archived"), Color(red: 74/255, green: 81/255, blue: 96/255))
    case "PROCESSING_STAGE1": return (L("badge.processing"), Color.aurionAmber)
    case "PROCESSING_STAGE2": return (L("badge.enriching"), Color.aurionAmber)
    case "AWAITING_REVIEW": return (L("badge.review"), Color.aurionGold)
    case "RECORDING": return (L("badge.recording"), Color.aurionRed)
    case "PAUSED": return (L("badge.paused"), Color.aurionAmber)
    case "CONSENT_PENDING": return (L("badge.consent"), Color(red: 74/255, green: 81/255, blue: 96/255))
    default: return (state, Color(red: 74/255, green: 81/255, blue: 96/255))
    }
}

/// Shared ISO date formatting with cached formatters.
func formatISODate(_ iso: String) -> String {
    guard let date = _isoFormatter.date(from: iso) else { return iso }
    return _displayFormatter.string(from: date)
}

/// Relative time like "11 min ago", "2 hr ago", "Yesterday". Falls back to absolute date for older entries.
func formatRelativeTime(_ iso: String) -> String {
    guard let date = _isoFormatter.date(from: iso) else { return iso }
    let elapsed = Date().timeIntervalSince(date)
    if elapsed < 60 { return "Just now" }
    if elapsed < 3600 { return "\(Int(elapsed / 60)) min ago" }
    if elapsed < 86_400 { return "\(Int(elapsed / 3600)) hr ago" }
    if elapsed < 172_800 { return "Yesterday" }
    return _displayFormatter.string(from: date)
}

private let _isoFormatter = ISO8601DateFormatter()
private let _displayFormatter: DateFormatter = {
    let f = DateFormatter()
    f.dateStyle = .medium
    f.timeStyle = .short
    return f
}()
