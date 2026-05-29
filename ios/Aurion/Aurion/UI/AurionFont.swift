import SwiftUI

/// Dynamic-Type-aware system font that **preserves the exact point size at the
/// default text setting** and scales from there, relative to a chosen text
/// style. The design system is built on precise `.system(size:)` values; this
/// keeps those pixel-tuned defaults while letting them grow for users who
/// raise their text size.
///
/// Use via the `.aurionFont(_:weight:relativeTo:)` modifier instead of
/// `.font(.system(size:weight:))`. `relativeTo` controls how aggressively the
/// size scales — pick the text style nearest the role of the text:
///
/// | point size | suggested `relativeTo` |
/// |------------|------------------------|
/// | ≤ 12       | `.caption2` / `.caption` |
/// | 13–15      | `.footnote` / `.subheadline` |
/// | 16–17      | `.body` / `.callout` |
/// | 18–22      | `.title3` / `.title2` |
/// | 24+        | `.title` / `.largeTitle` |
///
/// Not for views captured into a PDF (`ImageRenderer`) — those must keep fixed
/// point sizes so exports render identically regardless of the reader's
/// setting. Guard those paths with a literal instead.
struct AurionScaledFont: ViewModifier {
    @ScaledMetric private var size: CGFloat
    private let weight: Font.Weight

    init(size: CGFloat, weight: Font.Weight, relativeTo: Font.TextStyle) {
        _size = ScaledMetric(wrappedValue: size, relativeTo: relativeTo)
        self.weight = weight
    }

    func body(content: Content) -> some View {
        content.font(.system(size: size, weight: weight))
    }
}

extension View {
    /// A `.system(size:weight:)` font that scales with Dynamic Type while
    /// preserving the given size at the default setting.
    func aurionFont(
        _ size: CGFloat,
        weight: Font.Weight = .regular,
        relativeTo: Font.TextStyle = .body
    ) -> some View {
        modifier(AurionScaledFont(size: size, weight: weight, relativeTo: relativeTo))
    }
}
