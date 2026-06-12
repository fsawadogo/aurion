import SwiftUI

/// Entry point for the in-encounter measurement instrument (#63).
///
/// Flow: pick what to measure → AR capture (full-screen) → physician confirm →
/// POST. On confirm the backend persists the measurement and injects it into
/// the note as a claim. Present this from a surface where the camera is free
/// (it runs its own ARSession) — e.g. the post-encounter note screen; gate the
/// launch on `RemoteConfig.shared.featureFlags.measurementEnabled`.
struct MeasurementInstrumentView: View {
    let sessionId: String
    /// Called after a measurement is accepted by the backend (e.g. to refresh
    /// the note so the new claim appears).
    var onSubmitted: ((MeasurementResponse) -> Void)?
    let onClose: () -> Void

    @State private var selectedKind: MeasurementKind?
    @State private var captured: MeasurementResult?
    @State private var isSubmitting = false
    @State private var errorMessage: String?
    @State private var savedCount = 0

    private let columns = [GridItem(.flexible()), GridItem(.flexible())]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: AurionSpacing.lg) {
                    disclaimerBanner
                    Text(L("measurement.pick.title"))
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextSecondary)
                    LazyVGrid(columns: columns, spacing: AurionSpacing.md) {
                        ForEach(MeasurementKind.allCases) { kind in
                            kindTile(kind)
                        }
                    }
                    if savedCount > 0 {
                        Text(L("measurement.savedCount", savedCount))
                            .aurionFont(13, relativeTo: .footnote)
                            .foregroundColor(.aurionGreen)
                    }
                }
                .padding(AurionSpacing.lg)
            }
            .background(Color.aurionBackground.ignoresSafeArea())
            .navigationTitle(L("measurement.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("common.done")) { onClose() }
                }
            }
        }
        .fullScreenCover(item: $selectedKind) { kind in
            MeasurementCaptureView(
                kind: kind,
                onCapture: { result in
                    selectedKind = nil
                    captured = result
                },
                onCancel: { selectedKind = nil }
            )
        }
        .sheet(item: $captured) { result in
            confirmSheet(result)
        }
        .alert(
            L("measurement.error.title"),
            isPresented: Binding(
                get: { errorMessage != nil },
                set: { if !$0 { errorMessage = nil } }
            )
        ) {
            Button(L("common.ok"), role: .cancel) { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
    }

    // MARK: - Pieces

    private var disclaimerBanner: some View {
        HStack(alignment: .top, spacing: AurionSpacing.xs) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 14))
                .foregroundColor(.aurionAmber)
            Text(L("measurement.disclaimer"))
                .aurionFont(13, weight: .medium, relativeTo: .footnote)
                .foregroundColor(.aurionTextPrimary)
        }
        .padding(AurionSpacing.sm)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .fill(Color.aurionAmberBg)
        )
    }

    private func kindTile(_ kind: MeasurementKind) -> some View {
        Button(action: { AurionHaptics.selection(); selectedKind = kind }) {
            VStack(spacing: AurionSpacing.xs) {
                Image(systemName: kind.systemImage)
                    .font(.system(size: 26, weight: .regular))
                    .foregroundColor(.aurionGold)
                Text(L(kind.titleKey))
                    .aurionFont(15, weight: .semibold, relativeTo: .callout)
                    .foregroundColor(.aurionTextPrimary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, AurionSpacing.lg)
            .background(
                RoundedRectangle(cornerRadius: AurionRadius.lg)
                    .fill(Color.aurionCardBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: AurionRadius.lg)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
        }
    }

    @ViewBuilder
    private func confirmSheet(_ result: MeasurementResult) -> some View {
        VStack(spacing: AurionSpacing.md) {
            Capsule()
                .fill(Color.aurionBorder)
                .frame(width: 36, height: 5)
                .padding(.top, AurionSpacing.sm)
            if isSubmitting {
                ProgressView(L("measurement.submitting"))
                    .padding(AurionSpacing.xl)
            } else {
                MeasurementConfirmCard(
                    initial: result,
                    onConfirm: { confirmed in submit(confirmed) },
                    onDiscard: { captured = nil }
                )
            }
            Spacer(minLength: 0)
        }
        .presentationDetents([.medium])
        .background(Color.aurionBackground.ignoresSafeArea())
    }

    // MARK: - Submit

    private func submit(_ result: MeasurementResult) {
        isSubmitting = true
        let payload = MeasurementCitationPayload(
            sessionId: sessionId, result: result, physicianConfirmed: true
        )
        Task {
            do {
                let saved = try await APIClient.shared.submitMeasurement(
                    sessionId: sessionId, payload
                )
                await MainActor.run {
                    isSubmitting = false
                    captured = nil
                    savedCount += 1
                    onSubmitted?(saved)
                }
            } catch {
                await MainActor.run {
                    isSubmitting = false
                    captured = nil
                    errorMessage = friendlyError(error)
                }
            }
        }
    }

    private func friendlyError(_ error: Error) -> String {
        if let apiError = error as? APIError {
            switch apiError {
            case .forbidden: return L("measurement.error.disabled")
            case .offline: return L("measurement.error.offline")
            default: return apiError.localizedDescription
            }
        }
        return error.localizedDescription
    }
}
