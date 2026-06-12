import SwiftUI

/// Physician review + confirm for a captured measurement (#63, design §4).
///
/// A measurement does **not** enter the note until the physician confirms it
/// here. They may fine-tune the value first (surgeons will want to nudge), then
/// **Confirm** (→ POST with `physician_confirmed = true`, which the backend
/// injects into the note as a claim) or **Discard**. The card repeats the
/// "approximate, not certified" disclaimer — a fixed, non-themeable safety
/// surface.
struct MeasurementConfirmCard: View {
    let initial: MeasurementResult
    let onConfirm: (MeasurementResult) -> Void
    let onDiscard: () -> Void

    @State private var value: Double
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    /// Nudge step per kind: 1 mm for wounds, 1° for ROM, 0.1 cm² for area.
    private var step: Double {
        switch initial.kind {
        case .woundArea: return 0.1
        default: return 1.0
        }
    }

    init(
        initial: MeasurementResult,
        onConfirm: @escaping (MeasurementResult) -> Void,
        onDiscard: @escaping () -> Void
    ) {
        self.initial = initial
        self.onConfirm = onConfirm
        self.onDiscard = onDiscard
        _value = State(initialValue: initial.value)
    }

    private var edited: MeasurementResult {
        var r = initial
        r.value = max(0, value)
        return r
    }

    var body: some View {
        VStack(alignment: .leading, spacing: AurionSpacing.md) {
            header
            valueEditor
            provenance
            disclaimer
            actions
        }
        .padding(AurionSpacing.lg)
        .background(
            RoundedRectangle(cornerRadius: AurionRadius.lg)
                .fill(Color.aurionCardBackground)
        )
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.lg)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .padding(.horizontal, AurionSpacing.md)
    }

    private var header: some View {
        HStack(spacing: AurionSpacing.xs) {
            Image(systemName: initial.kind.systemImage)
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(.aurionGold)
            Text(L(initial.kind.titleKey))
                .aurionFont(18, weight: .semibold, relativeTo: .title3)
                .foregroundColor(.aurionTextPrimary)
            Spacer()
            ConfidencePill(confidence: initial.confidence)
        }
    }

    private var valueEditor: some View {
        HStack(spacing: AurionSpacing.md) {
            Button(action: { value = max(0, value - step); AurionHaptics.selection() }) {
                stepperGlyph("minus")
            }
            .accessibilityLabel(L("measurement.decrease"))

            VStack(spacing: 0) {
                Text("≈ \(edited.displayValue) \(edited.displayUnit)")
                    .aurionFont(30, weight: .bold, relativeTo: .largeTitle)
                    .foregroundColor(.aurionTextPrimary)
                    .minimumScaleFactor(0.6)
                    .lineLimit(1)
            }
            .frame(maxWidth: .infinity)

            Button(action: { value += step; AurionHaptics.selection() }) {
                stepperGlyph("plus")
            }
            .accessibilityLabel(L("measurement.increase"))
        }
    }

    private func stepperGlyph(_ name: String) -> some View {
        Image(systemName: name)
            .font(.system(size: 18, weight: .bold))
            .foregroundColor(.aurionGold)
            .frame(width: 44, height: 44)
            .background(
                RoundedRectangle(cornerRadius: AurionRadius.md)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
    }

    private var provenance: some View {
        Text(L("measurement.provenance", L(methodLabelKey)))
            .aurionFont(13, relativeTo: .footnote)
            .foregroundColor(.aurionTextSecondary)
    }

    private var methodLabelKey: String {
        switch initial.method {
        case .arkitLidar: return "measurement.method.lidar"
        case .arkitWorld: return "measurement.method.world"
        case .arGoniometer: return "measurement.method.goniometer"
        }
    }

    // Fixed safety surface — not accent-driven.
    private var disclaimer: some View {
        HStack(alignment: .top, spacing: AurionSpacing.xs) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundColor(.aurionAmber)
            Text(L("measurement.disclaimer"))
                .aurionFont(12, weight: .medium, relativeTo: .caption)
                .foregroundColor(.aurionTextSecondary)
        }
        .padding(AurionSpacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: AurionRadius.sm)
                .fill(Color.aurionAmberBg)
        )
    }

    private var actions: some View {
        // ViewThatFits keeps the two actions side-by-side normally and stacks
        // them full-width at large Dynamic Type (AX), per the responsive bar.
        ViewThatFits(in: .horizontal) {
            HStack(spacing: AurionSpacing.sm) { discardButton; confirmButton }
            VStack(spacing: AurionSpacing.sm) { confirmButton; discardButton }
        }
    }

    private var discardButton: some View {
        Button(action: { AurionHaptics.selection(); onDiscard() }) {
            Text(L("measurement.discard"))
                .aurionFont(16, weight: .semibold, relativeTo: .body)
                .frame(maxWidth: .infinity)
                .padding(.vertical, AurionSpacing.sm)
                .foregroundColor(.aurionTextPrimary)
                .background(
                    RoundedRectangle(cornerRadius: AurionRadius.md)
                        .stroke(Color.aurionBorder, lineWidth: 1)
                )
        }
    }

    private var confirmButton: some View {
        Button(action: { AurionHaptics.notification(.success); onConfirm(edited) }) {
            Text(L("measurement.confirm"))
                .aurionFont(16, weight: .bold, relativeTo: .body)
                .frame(maxWidth: .infinity)
                .padding(.vertical, AurionSpacing.sm)
                .foregroundColor(.aurionNavy)
                .background(
                    RoundedRectangle(cornerRadius: AurionRadius.md)
                        .fill(Color.aurionGold)
                )
        }
    }
}
