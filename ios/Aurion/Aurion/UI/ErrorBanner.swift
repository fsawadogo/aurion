import SwiftUI

/// Consistent, designed error surface — a red-tinted card with an icon, the
/// message, and optional Retry / Dismiss actions. Replaces the ad-hoc red
/// `Text` scattered across screens so a failure reads as *handled*, not as a
/// broken app.
struct ErrorBanner: View {
    let message: String
    var onRetry: (() -> Void)?
    var onDismiss: (() -> Void)?

    init(
        _ message: String,
        onRetry: (() -> Void)? = nil,
        onDismiss: (() -> Void)? = nil
    ) {
        self.message = message
        self.onRetry = onRetry
        self.onDismiss = onDismiss
    }

    private var hasActions: Bool { onRetry != nil || onDismiss != nil }

    var body: some View {
        if hasActions {
            // Leave the Retry / Dismiss buttons as individually focusable
            // elements — combining the whole banner would merge them away
            // and VoiceOver users could no longer operate them.
            bannerCard
        } else {
            // Pure message banner: flatten into a single spoken element.
            bannerCard
                .accessibilityElement(children: .combine)
                .accessibilityLabel(message)
        }
    }

    private var bannerCard: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(.aurionRed)
                .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: hasActions ? 10 : 0) {
                Text(message)
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)

                if hasActions {
                    // Retry / Dismiss sit side-by-side; at larger Dynamic Type
                    // the two labels can't share a row, so they stack
                    // vertically instead of being clipped (#271).
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 18) {
                            retryButton
                            dismissButton
                        }
                        VStack(alignment: .leading, spacing: 10) {
                            retryButton
                            dismissButton
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.aurionRedBg)
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md, style: .continuous))
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md, style: .continuous)
                .stroke(Color.aurionRed.opacity(0.3), lineWidth: 1)
        )
    }

    @ViewBuilder private var retryButton: some View {
        if let onRetry {
            Button(L("common.retry")) {
                AurionHaptics.impact(.light)
                onRetry()
            }
            .aurionFont(13, weight: .semibold, relativeTo: .footnote)
            .foregroundColor(.aurionGold)
        }
    }

    @ViewBuilder private var dismissButton: some View {
        if let onDismiss {
            Button(L("common.dismiss"), action: onDismiss)
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
        }
    }
}
