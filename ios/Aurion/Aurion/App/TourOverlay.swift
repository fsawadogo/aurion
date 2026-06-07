import SwiftUI

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
    /// or centered when there's no spotlight. Spacer-based so we don't need to
    /// know the card's height in advance.
    @ViewBuilder
    private var tooltipLayout: some View {
        VStack(spacing: 0) {
            if let rect = spotlight {
                if rect.midY < containerSize.height / 2 {
                    Spacer().frame(height: rect.maxY + 18)
                    card
                    Spacer(minLength: 0)
                } else {
                    Spacer(minLength: 0)
                    card
                    Spacer().frame(height: max(0, containerSize.height - rect.minY + 18))
                }
            } else {
                Spacer()
                card
                Spacer()
            }
        }
        .frame(width: containerSize.width, height: containerSize.height)
        .transition(.opacity)
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
