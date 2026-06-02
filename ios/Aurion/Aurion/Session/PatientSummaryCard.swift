import SwiftUI

/// Patient-facing after-visit summary card (#59).
///
/// Lives on the `SessionNoteView` for sessions that have reached an
/// approved state (`REVIEW_COMPLETE`, `EXPORTED`, `PURGED`). The
/// physician taps Generate once — the LLM produces a Grade-8
/// plain-language handout — then can Copy, Share, Edit, or Regenerate.
///
/// Mirrors the portal's `<PatientSummaryCard />` (PR #166) so a
/// session opened on web vs iPad sees the same surfaces.
///
/// ## Approval gate
///
/// The server's POST endpoint refuses with 409 when the note isn't
/// approved yet — patient-facing output must come from a
/// physician-signed source. We hide the actions entirely in that
/// state rather than showing a button that always 409s.
///
/// ## PHI handling
///
/// The summary body IS PHI — the LLM produced it from the approved
/// note's claims. We never log it; the regenerate path discards the
/// old version (it stays in the audit log via the new-version event
/// already emitted by the backend in #166); the Copy action uses
/// `UIPasteboard.general.string` which the system clears on logout
/// via the existing app-level pasteboard hooks.
struct PatientSummaryCard: View {
    let sessionId: String
    let sessionState: String

    @State private var summary: PatientSummaryResponse?
    @State private var isLoading = true
    @State private var isGenerating = false
    @State private var isSaving = false
    @State private var errorMessage: String?
    /// `true` when the initial GET errored. Suppresses the Generate
    /// CTA in favor of a Retry — Generate would 403 the same way.
    @State private var loadFailed = false

    // Edit mode is a local toggle — the textfield's draft survives a
    // cancel without writing back.
    @State private var isEditing = false
    @State private var draftBody: String = ""

    // Share + copy feedback.
    @State private var showShareSheet = false
    @State private var copiedFlash = false

    // Backend cap matches the portal — see web/types/index.ts:
    // PatientSummaryEditRequest.body has min_length=1, max_length=4000.
    private let maxChars = 4000

    /// Session states that have crossed the approval line. We gate on
    /// these instead of fetching `export_metadata.is_approved` to keep
    /// the iOS surface aligned with the existing SessionNoteView state
    /// machine (which navigates on these same strings).
    private static let approvedStates: Set<String> = [
        "REVIEW_COMPLETE", "EXPORTED", "PURGED",
    ]

    private var isApproved: Bool {
        Self.approvedStates.contains(sessionState)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header

            if !isApproved {
                gateNotice
            } else if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            } else if let s = summary {
                if isEditing {
                    editor(s)
                } else {
                    populated(s)
                }
            } else if loadFailed {
                retryState
            } else {
                emptyState
            }

            if let msg = errorMessage {
                Text(msg)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.red)
            }
        }
        .padding(16)
        .background(Color.aurionCardBackground)
        .cornerRadius(16)
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .task { await loadIfNeeded() }
        .onChange(of: sessionState) { newValue in
            // Session may transition from PROCESSING to REVIEW_COMPLETE
            // while this view is visible. Re-fetch when the state
            // crosses into an approved bucket.
            if Self.approvedStates.contains(newValue) {
                Task { await loadIfNeeded() }
            }
        }
        .sheet(isPresented: $showShareSheet) {
            if let body = summary?.body {
                ActivityViewController(activityItems: [body])
            }
        }
    }

    // MARK: Subviews

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "doc.text.image")
                .font(.system(size: 16))
                .foregroundColor(.aurionGold)
            Text(L("summary.title"))
                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.aurionTextPrimary)
            Spacer()
            if let s = summary, s.physicianEdited {
                Text(L("summary.editedTag"))
                    .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color.aurionSurfaceAlt)
                    .clipShape(Capsule())
            }
        }
    }

    private var gateNotice: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lock.fill")
                .font(.system(size: 12))
                .foregroundColor(.aurionTextSecondary)
            Text(L("summary.gateMessage"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
                .multilineTextAlignment(.leading)
            Spacer()
        }
    }

    /// Sticky failure state: load GET errored. Distinct from the
    /// empty CTA because tapping Generate would 403 the same way —
    /// Retry re-runs loadIfNeeded so an intermittent failure
    /// self-heals.
    private var retryState: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 13))
                    .foregroundColor(.aurionAmber)
                Text(L("summary.loadFailed"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
            }
            Button {
                Task { await loadIfNeeded() }
            } label: {
                HStack(spacing: 4) {
                    if isLoading {
                        ProgressView().tint(.aurionTextPrimary)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 11, weight: .semibold))
                    }
                    Text(L("summary.retry"))
                        .aurionFont(12, weight: .semibold, relativeTo: .caption)
                }
                .foregroundColor(.aurionTextPrimary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(Color.aurionSurfaceAlt)
                .clipShape(Capsule())
            }
            .disabled(isLoading)
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(L("summary.subtitle"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
            Button {
                Task { await generate() }
            } label: {
                HStack(spacing: 6) {
                    if isGenerating {
                        ProgressView().tint(.aurionNavy)
                    } else {
                        Image(systemName: "sparkles")
                            .font(.system(size: 14, weight: .semibold))
                    }
                    Text(isGenerating
                         ? L("summary.generating")
                         : L("summary.generate"))
                        .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionNavy)
                }
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(Color.aurionGold)
                .clipShape(Capsule())
            }
            .disabled(isGenerating)
        }
    }

    private func populated(_ s: PatientSummaryResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            // Body — Grade-8 plain text. Render as a flowing block,
            // not monospaced. The Read More expansion is the user's
            // job via System scroll within the parent.
            Text(s.body)
                .aurionFont(14, relativeTo: .body)
                .foregroundColor(.aurionTextPrimary)
                .multilineTextAlignment(.leading)
                .fixedSize(horizontal: false, vertical: true)

            metaRow(s)

            HStack(spacing: 8) {
                actionButton(
                    label: copiedFlash ? L("summary.copied") : L("summary.copy"),
                    icon: copiedFlash ? "checkmark" : "doc.on.doc"
                ) { copy(s.body) }
                actionButton(label: L("summary.share"), icon: "square.and.arrow.up") {
                    showShareSheet = true
                }
                actionButton(label: L("summary.edit"), icon: "pencil") {
                    draftBody = s.body
                    isEditing = true
                }
                actionButton(
                    label: isGenerating ? L("summary.generating") : L("summary.regenerate"),
                    icon: "arrow.clockwise",
                    disabled: isGenerating
                ) { Task { await generate() } }
            }
        }
    }

    private func editor(_ s: PatientSummaryResponse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            // SwiftUI TextEditor inherits the system font; bump to the
            // body size + match the on-card padding so the editing
            // surface reads as a direct in-place swap of the populated
            // text block.
            TextEditor(text: $draftBody)
                .aurionFont(14, relativeTo: .body)
                .foregroundColor(.aurionTextPrimary)
                .frame(minHeight: 120)
                .padding(8)
                .background(Color.aurionSurfaceAlt)
                .cornerRadius(12)
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.aurionBorder, lineWidth: 1)
                )
                .disabled(isSaving)

            HStack {
                Text(L("summary.charLimit", draftBody.count, maxChars))
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(draftBody.count > maxChars
                                     ? .red : .aurionTextSecondary)
                Spacer()
                Button(L("summary.cancel")) {
                    isEditing = false
                    draftBody = ""
                }
                .disabled(isSaving)
                .aurionFont(13, weight: .medium, relativeTo: .footnote)

                Button {
                    Task { await saveEdit(originalVersion: s.version) }
                } label: {
                    HStack(spacing: 4) {
                        if isSaving {
                            ProgressView().tint(.aurionNavy)
                        }
                        Text(L("summary.save"))
                            .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                            .foregroundColor(.aurionNavy)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color.aurionGold)
                    .clipShape(Capsule())
                }
                .disabled(isSaving
                          || draftBody.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                          || draftBody.count > maxChars)
            }
        }
    }

    private func metaRow(_ s: PatientSummaryResponse) -> some View {
        HStack(spacing: 8) {
            Text(L("summary.versionLabel", s.version))
            Text("·").foregroundColor(.aurionTextSecondary.opacity(0.4))
            Text(L("summary.providerLabel", s.generatedByProvider))
        }
        .aurionFont(11, relativeTo: .caption2)
        .foregroundColor(.aurionTextSecondary)
    }

    private func actionButton(
        label: String,
        icon: String,
        disabled: Bool = false,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 11, weight: .semibold))
                Text(label)
                    .aurionFont(11, weight: .semibold, relativeTo: .caption)
            }
            .foregroundColor(.aurionTextPrimary)
            .padding(.horizontal, 10)
            .padding(.vertical, 6)
            .background(Color.aurionSurfaceAlt)
            .clipShape(Capsule())
        }
        .disabled(disabled)
        .opacity(disabled ? 0.5 : 1.0)
    }

    // MARK: Actions

    private func loadIfNeeded() async {
        guard isApproved else { isLoading = false; return }
        isLoading = true
        do {
            summary = try await APIClient.shared.getPatientSummary(
                sessionId: sessionId
            )
            errorMessage = nil
            loadFailed = false
        } catch {
            // Polling-style 5xx / auth blip — leave the existing
            // summary alone if we had one (the populated state
            // stays valid); surface the retry block only when we
            // have nothing to show yet.
            if summary == nil {
                loadFailed = true
            }
            errorMessage = nil
        }
        isLoading = false
    }

    private func generate() async {
        isGenerating = true
        errorMessage = nil
        defer { isGenerating = false }
        do {
            summary = try await APIClient.shared.generatePatientSummary(
                sessionId: sessionId
            )
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("summary.generateFailed")
        }
    }

    private func saveEdit(originalVersion: Int) async {
        let trimmed = draftBody.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= maxChars else { return }
        isSaving = true
        errorMessage = nil
        defer { isSaving = false }
        do {
            summary = try await APIClient.shared.editPatientSummary(
                sessionId: sessionId,
                body: trimmed
            )
            AurionHaptics.notification(.success)
            isEditing = false
            draftBody = ""
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("summary.saveFailed")
        }
    }

    private func copy(_ body: String) {
        UIPasteboard.general.string = body
        AurionHaptics.notification(.success)
        copiedFlash = true
        Task {
            // 1.5s flash — long enough for the user to see "Copied"
            // but short enough that the chip returns to the normal
            // affordance before the next interaction.
            try? await Task.sleep(nanoseconds: 1_500_000_000)
            await MainActor.run { copiedFlash = false }
        }
    }
}

// MARK: - ActivityViewController (UIKit bridge)

/// UIActivityViewController wrapper so the summary can be Shared via
/// AirDrop / Messages / Mail / Print. UIPasteboard.copy is in-app;
/// this is the system-level share extension surface.
struct ActivityViewController: UIViewControllerRepresentable {
    let activityItems: [Any]
    let applicationActivities: [UIActivity]? = nil

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(
            activityItems: activityItems,
            applicationActivities: applicationActivities
        )
    }

    func updateUIViewController(
        _ uiViewController: UIActivityViewController,
        context: Context
    ) {}
}
