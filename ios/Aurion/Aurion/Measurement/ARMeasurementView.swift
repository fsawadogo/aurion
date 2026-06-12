import ARKit
import SwiftUI

/// Hosts the `ARSCNView` from an `ARMeasurementController` and forwards taps as
/// point placements. Pure plumbing — all geometry lives in the controller.
struct ARSceneContainer: UIViewRepresentable {
    let controller: ARMeasurementController

    func makeUIView(context: Context) -> ARSCNView {
        let view = controller.sceneView
        let tap = UITapGestureRecognizer(
            target: context.coordinator, action: #selector(Coordinator.handleTap(_:))
        )
        view.addGestureRecognizer(tap)
        return view
    }

    func updateUIView(_ uiView: ARSCNView, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(controller: controller) }

    @MainActor
    final class Coordinator: NSObject {
        let controller: ARMeasurementController
        init(controller: ARMeasurementController) { self.controller = controller }

        @objc func handleTap(_ gesture: UITapGestureRecognizer) {
            let point = gesture.location(in: controller.sceneView)
            controller.placePoint(at: point)
            AurionHaptics.selection()
        }
    }
}

/// The AR capture screen: live camera + measurement overlay, the place/reset
/// controls, and the always-on "approximate, not certified" disclaimer.
/// Calls `onCapture` with the completed result for the physician to confirm.
struct MeasurementCaptureView: View {
    @StateObject private var controller: ARMeasurementController
    let onCapture: (MeasurementResult) -> Void
    let onCancel: () -> Void

    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        kind: MeasurementKind,
        onCapture: @escaping (MeasurementResult) -> Void,
        onCancel: @escaping () -> Void
    ) {
        _controller = StateObject(wrappedValue: ARMeasurementController(kind: kind))
        self.onCapture = onCapture
        self.onCancel = onCancel
    }

    var body: some View {
        ZStack {
            ARSceneContainer(controller: controller)
                .ignoresSafeArea()

            // Center reticle to aim point placement.
            Image(systemName: "plus")
                .font(.system(size: 22, weight: .light))
                .foregroundColor(.white.opacity(0.85))
                .shadow(radius: 2)
                .accessibilityHidden(true)

            VStack(spacing: 0) {
                topBar
                Spacer()
                bottomPanel
            }
        }
        .onAppear { controller.start() }
        .onDisappear { controller.stop() }
    }

    // MARK: - Top bar

    private var topBar: some View {
        VStack(spacing: AurionSpacing.xs) {
            HStack {
                Button(action: { controller.stop(); onCancel() }) {
                    Image(systemName: "xmark")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(.white)
                        .padding(AurionSpacing.sm)
                        .background(Circle().fill(.black.opacity(0.4)))
                }
                .accessibilityLabel(L("common.cancel"))
                Spacer()
                Text(L(controller.kind.titleKey))
                    .aurionFont(16, weight: .semibold, relativeTo: .callout)
                    .foregroundColor(.white)
                    .padding(.horizontal, AurionSpacing.sm)
                    .padding(.vertical, AurionSpacing.xs)
                    .background(Capsule().fill(.black.opacity(0.4)))
                Spacer()
                // Balance the leading close button so the title stays centered.
                Color.clear.frame(width: 40, height: 40)
            }
            Text(instruction)
                .aurionFont(14, weight: .medium, relativeTo: .subheadline)
                .foregroundColor(.white)
                .multilineTextAlignment(.center)
                .padding(.horizontal, AurionSpacing.sm)
                .padding(.vertical, AurionSpacing.xs)
                .background(Capsule().fill(.black.opacity(0.4)))
        }
        .padding(.horizontal, AurionSpacing.lg)
        .padding(.top, AurionSpacing.sm)
    }

    private var instruction: String {
        if let hint = controller.trackingHint { return hint }
        let placed = controller.placedPointCount
        let needed = controller.kind.isAngle ? 3 : 2
        if placed >= needed { return L("measurement.instruction.ready") }
        if controller.kind.isAngle {
            return placed == 0 ? L("measurement.instruction.tapVertex")
                : L("measurement.instruction.tapRay")
        }
        return placed == 0 ? L("measurement.instruction.tapFirst")
            : L("measurement.instruction.tapSecond")
    }

    // MARK: - Bottom panel

    private var bottomPanel: some View {
        VStack(spacing: AurionSpacing.sm) {
            if let result = controller.liveResult {
                readout(result)
            }
            disclaimer
            controls
        }
        .padding(AurionSpacing.lg)
        .background(
            RoundedRectangle(cornerRadius: AurionRadius.xl)
                .fill(.black.opacity(0.55))
        )
        .padding(.horizontal, AurionSpacing.md)
        .padding(.bottom, AurionSpacing.sm)
    }

    private func readout(_ result: MeasurementResult) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: AurionSpacing.xs) {
            Text("≈ \(result.displayValue)")
                .aurionFont(34, weight: .bold, relativeTo: .largeTitle)
                .foregroundColor(.white)
            Text(result.displayUnit)
                .aurionFont(20, weight: .semibold, relativeTo: .title3)
                .foregroundColor(.white.opacity(0.85))
            Spacer()
            ConfidencePill(confidence: result.confidence)
        }
    }

    // Fixed, non-themeable safety surface (CLAUDE.md: compliance surfaces are
    // not accent-driven). The "not certified" wording is load-bearing.
    private var disclaimer: some View {
        HStack(spacing: AurionSpacing.xs) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundColor(.aurionAmber)
            Text(L("measurement.disclaimer"))
                .aurionFont(12, weight: .medium, relativeTo: .caption)
                .foregroundColor(.white.opacity(0.9))
            Spacer(minLength: 0)
        }
    }

    private var controls: some View {
        HStack(spacing: AurionSpacing.sm) {
            Button(action: { controller.reset(); AurionHaptics.selection() }) {
                Text(L("measurement.reset"))
                    .aurionFont(16, weight: .semibold, relativeTo: .body)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, AurionSpacing.sm)
                    .foregroundColor(.white)
                    .background(
                        RoundedRectangle(cornerRadius: AurionRadius.md)
                            .stroke(.white.opacity(0.6), lineWidth: 1)
                    )
            }
            .disabled(controller.placedPointCount == 0)
            .opacity(controller.placedPointCount == 0 ? 0.5 : 1)

            Button(action: {
                guard let result = controller.completedResult else { return }
                AurionHaptics.notification(.success)
                controller.stop()
                onCapture(result)
            }) {
                Text(L("measurement.capture"))
                    .aurionFont(16, weight: .bold, relativeTo: .body)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, AurionSpacing.sm)
                    .foregroundColor(.aurionNavy)
                    .background(
                        RoundedRectangle(cornerRadius: AurionRadius.md)
                            .fill(controller.completedResult == nil ? Color.gray : Color.aurionGold)
                    )
            }
            .disabled(controller.completedResult == nil)
        }
    }
}

/// Small confidence chip — fixed semantic colors (a confidence signal is a
/// compliance surface, not accent-driven).
struct ConfidencePill: View {
    let confidence: MeasurementConfidence

    private var color: Color {
        switch confidence {
        case .high: return .aurionGreen
        case .medium: return .aurionAmber
        case .low: return .aurionRed
        }
    }

    private var labelKey: String {
        switch confidence {
        case .high: return "measurement.confidence.high"
        case .medium: return "measurement.confidence.medium"
        case .low: return "measurement.confidence.low"
        }
    }

    var body: some View {
        Text(L(labelKey))
            .aurionFont(11, weight: .bold, relativeTo: .caption2)
            .tracking(0.4)
            .foregroundColor(.white)
            .padding(.horizontal, AurionSpacing.xs)
            .padding(.vertical, 3)
            .background(Capsule().fill(color))
            .accessibilityLabel(L(labelKey))
    }
}
