import SwiftUI
import UIKit

/// Full-screen coach-mark overlay: a dimmed scrim with a spotlight cut-out
/// around the current step's target, a pulsing gold ring, and a tooltip card.
///
/// Hosted by `ContentView` inside a full-screen `GeometryReader` so every
/// coordinate — resolved anchor frames and the computed tab-bar strip — shares
/// one space. The scrim swallows taps (tapping the dim advances), so the real
/// UI underneath can't be triggered mid-tour.
struct TourOverlay: View {
    @ObservedObject var tour: TourCoordinator
    let frames: [TourAnchor: CGRect]
    let containerSize: CGSize

    @State private var ringPulse = false
    /// Measured height of the tooltip card. Drives the safe-area clamp so the
    /// whole card (incl. the Skip/Next row) stays on-screen at any Dynamic Type
    /// size; 0 until the first layout pass measures it.
    @State private var cardHeight: CGFloat = 0

    private var step: TourStep { tour.currentStep }

    /// Region to spotlight for the current step, in container coordinates.
    /// `nil` → no cut-out (centered intro card over a full scrim).
    private var spotlight: CGRect? {
        if step.highlightsTabBar {
            let height: CGFloat = 84
            return CGRect(
                x: 10,
                y: containerSize.height - height - 6,
                width: containerSize.width - 20,
                height: height
            )
        }
        guard let anchor = step.anchor, let frame = frames[anchor] else { return nil }
        return frame.insetBy(dx: -10, dy: -10)
    }

    var body: some View {
        ZStack(alignment: .topLeading) {
            // Dimmed scrim with the spotlight punched out. Tapping the dim
            // advances; the cut-out animates as the step changes.
            Color.black.opacity(0.72)
                .reverseMask { cutout }
                .contentShape(Rectangle())
                .onTapGesture { tour.next() }
                .animation(AurionAnimation.spring, value: tour.stepIndex)
                .accessibilityHidden(true)

            if let rect = spotlight {
                RoundedRectangle(cornerRadius: 18, style: .continuous)
                    .stroke(Color.aurionGold, lineWidth: 2)
                    .frame(width: rect.width, height: rect.height)
                    .position(x: rect.midX, y: rect.midY)
                    .opacity(ringPulse ? 0.3 : 0.95)
                    .scaleEffect(ringPulse ? 1.035 : 1.0)
                    .animation(AurionAnimation.pulse, value: ringPulse)
                    .animation(AurionAnimation.spring, value: tour.stepIndex)
                    .allowsHitTesting(false)
            }

            tooltipLayout
        }
        .frame(width: containerSize.width, height: containerSize.height)
        .onAppear { ringPulse = true }
    }

    @ViewBuilder
    private var cutout: some View {
        if let rect = spotlight {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .frame(width: rect.width, height: rect.height)
                .position(x: rect.midX, y: rect.midY)
        }
    }

    /// Positions the card below a top-half spotlight, above a bottom-half one,
    /// or centered when there's no spotlight — then CLAMPS it so the entire
    /// card (incl. the Skip/Next row) always stays inside the safe area, for
    /// any spotlight position and any Dynamic Type size (#352). A low/large
    /// spotlight (e.g. the Quick Start grid at AX sizes) used to push Skip/Next
    /// off the bottom; the clamp now pins the card so its bottom never crosses
    /// `safeAreaInsets.bottom`, and if the card is taller than the safe band it
    /// becomes scrollable so both buttons stay tappable.
    @ViewBuilder
    private var tooltipLayout: some View {
        let insets = windowSafeAreaInsets
        let topInset = insets.top + 16
        let bottomInset = insets.bottom + 16
        let available = max(0, containerSize.height - topInset - bottomInset)
        let clampedTop = Self.clampedCardTop(
            spotlight: spotlight,
            cardHeight: cardHeight,
            containerHeight: containerSize.height,
            safeTop: insets.top,
            safeBottom: insets.bottom
        )

        ZStack(alignment: .topLeading) {
            if cardHeight > available, available > 0 {
                // Card taller than the safe band (extreme Dynamic Type on a
                // small device): make it scrollable so Skip + Next stay reachable
                // instead of overflowing off-screen.
                ScrollView(showsIndicators: false) {
                    measuredCard
                }
                .frame(width: containerSize.width, height: available)
                .position(x: containerSize.width / 2, y: topInset + available / 2)
            } else {
                measuredCard
                    .position(x: containerSize.width / 2, y: clampedTop + cardHeight / 2)
            }
        }
        .frame(width: containerSize.width, height: containerSize.height, alignment: .topLeading)
        .onPreferenceChange(TourCardHeightKey.self) { cardHeight = $0 }
        .transition(.opacity)
    }

    /// The card with a transparent height probe behind it. The probe reports
    /// the card's rendered height up through `TourCardHeightKey` so the layout
    /// can clamp the card's position to the safe area.
    private var measuredCard: some View {
        card.background(
            GeometryReader { geo in
                Color.clear.preference(key: TourCardHeightKey.self, value: geo.size.height)
            }
        )
    }

    /// Safe-area insets of the active window. The host `GeometryReader` in
    /// `ContentView` ignores the safe area (so its proxy reports zero insets),
    /// so we read the key window directly to keep the card clear of the notch /
    /// Dynamic Island and the home indicator.
    private var windowSafeAreaInsets: EdgeInsets {
        let insets = UIApplication.shared.connectedScenes
            .compactMap { $0 as? UIWindowScene }
            .flatMap { $0.windows }
            .first { $0.isKeyWindow }?
            .safeAreaInsets ?? .zero
        return EdgeInsets(
            top: insets.top, leading: insets.left,
            bottom: insets.bottom, trailing: insets.right
        )
    }

    /// Pure placement math for the tooltip card's top edge — extracted so the
    /// "never clipped" guarantee is unit-testable without a live view. Returns
    /// the card's top Y in container coordinates, clamped so the whole card
    /// stays within the safe band `[safeTop + margin, containerHeight -
    /// safeBottom - margin]`.
    static func clampedCardTop(
        spotlight: CGRect?,
        cardHeight: CGFloat,
        containerHeight: CGFloat,
        safeTop: CGFloat,
        safeBottom: CGFloat,
        margin: CGFloat = 16,
        gap: CGFloat = 18
    ) -> CGFloat {
        let topInset = safeTop + margin
        let bottomInset = safeBottom + margin
        let available = max(0, containerHeight - topInset - bottomInset)

        let desiredTop: CGFloat
        if let rect = spotlight {
            if rect.midY < containerHeight / 2 {
                desiredTop = rect.maxY + gap            // below a top-half spotlight
            } else {
                desiredTop = rect.minY - gap - cardHeight  // above a bottom-half spotlight
            }
        } else {
            desiredTop = topInset + max(0, (available - cardHeight) / 2)  // centered
        }

        // Lower bound: never above the top safe band. Upper bound: card bottom
        // never crosses the bottom safe band (falls back to topInset when the
        // card is taller than the band — the scroll path then takes over).
        let maxTop = max(topInset, containerHeight - bottomInset - cardHeight)
        return min(max(desiredTop, topInset), maxTop)
    }

    /// Whether the card is taller than the safe band and therefore needs to
    /// scroll for Skip/Next to stay reachable. Mirrors the runtime branch in
    /// `tooltipLayout`; exposed for unit tests.
    static func cardNeedsScroll(
        cardHeight: CGFloat,
        containerHeight: CGFloat,
        safeTop: CGFloat,
        safeBottom: CGFloat,
        margin: CGFloat = 16
    ) -> Bool {
        let available = max(0, containerHeight - (safeTop + margin) - (safeBottom + margin))
        return cardHeight > available && available > 0
    }

    private var card: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L(step.titleKey))
                .aurionFont(18, weight: .bold, relativeTo: .title3)
                .foregroundColor(.aurionTextPrimary)
            Text(L(step.messageKey))
                .aurionFont(14, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)
                .fixedSize(horizontal: false, vertical: true)

            HStack(spacing: 6) {
                ForEach(0..<tour.steps.count, id: \.self) { i in
                    Circle()
                        .fill(i == tour.stepIndex ? Color.aurionGold : Color.aurionBorder)
                        .frame(width: 6, height: 6)
                }
                Spacer()
                Button { tour.dontShowAgain.toggle() } label: {
                    HStack(spacing: 6) {
                        Image(systemName: tour.dontShowAgain ? "checkmark.square.fill" : "square")
                            .foregroundColor(tour.dontShowAgain ? .aurionGold : .aurionTextSecondary)
                            .accessibilityHidden(true)
                        Text(L("tour.dontShowAgain"))
                            .aurionFont(12, relativeTo: .caption)
                            .foregroundColor(.aurionTextSecondary)
                    }
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(L("tour.dontShowAgain"))
                .accessibilityAddTraits(tour.dontShowAgain ? .isSelected : [])
            }
            .padding(.top, 2)

            HStack {
                Button(L("common.skip")) { tour.skip() }
                    .aurionFont(15, weight: .medium, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                Spacer()
                Button { tour.next() } label: {
                    Text(tour.isLastStep ? L("common.done") : L("tour.next"))
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionNavy)
                        .padding(.horizontal, 22)
                        .padding(.vertical, 10)
                        .background(Color.aurionGold)
                        .clipShape(Capsule())
                }
                .buttonStyle(.plain)
            }
            .padding(.top, 4)
        }
        .padding(20)
        .frame(maxWidth: 360)
        .background(Color.aurionCardBackground)
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.lg, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.lg, style: .continuous)
                .stroke(Color.aurionGold.opacity(0.25), lineWidth: 1)
        )
        .shadow(color: .black.opacity(0.28), radius: 22, y: 10)
        .padding(.horizontal, 24)
        .frame(maxWidth: .infinity)
        .id(tour.stepIndex)
        .transition(.opacity.combined(with: .scale(scale: 0.96)))
        .accessibilityElement(children: .contain)
        .accessibilityAddTraits(.isModal)
    }
}

/// Carries the measured tooltip-card height up the view tree so `tooltipLayout`
/// can clamp the card's position to the safe area.
private struct TourCardHeightKey: PreferenceKey {
    static var defaultValue: CGFloat = 0
    static func reduce(value: inout CGFloat, nextValue: () -> CGFloat) {
        value = max(value, nextValue())
    }
}

private extension View {
    /// Punch the given shape out of `self` (the dimmed scrim) so the real UI
    /// shows through the spotlight hole.
    func reverseMask<M: View>(@ViewBuilder _ mask: () -> M) -> some View {
        self.mask {
            Rectangle()
                .overlay(mask().blendMode(.destinationOut))
        }
    }
}
