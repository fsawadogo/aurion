import SwiftUI

/// Set / clear the session's patient identifier (#61).
///
/// Rendered as a row in PostEncounterView. Tapping opens a sheet
/// with a text field; saving calls the existing PATCH
/// `/sessions/{id}/identifier` endpoint via APIClient.
///
/// ## Privacy
///
/// The identifier is PHI:
///   * the text field disables auto-correct + QuickType bar
///   * the on-screen value is never written to logs or analytics
///   * the row preview shows the value verbatim only when the user
///     has chosen to set it — empty state shows generic copy
///
/// ## Three states surfaced
///
/// 1. **Empty + add CTA** — gold "Add Patient Identifier" button
/// 2. **Set + mono chip** — the identifier renders in monospace
///    + gold tint so it stands out from surrounding text, with a
///    tap target to re-open the editor
/// 3. **Saving / clearing** — button shows a spinner; sheet stays
///    open until the network call completes (errors surface inline)
struct PatientIdentifierEditor: View {
    /// Session id this identifier is attached to. Owner-side auth
    /// happens server-side via the JWT; we trust it.
    let sessionId: String
    /// Initial identifier value from the session row (nil = unset).
    /// The sheet always reads from + writes back to the binding so
    /// the parent stays in sync.
    @Binding var identifier: String?

    @State private var showSheet = false

    var body: some View {
        Group {
            if let value = identifier, !value.isEmpty {
                setRow(value: value)
            } else {
                addButton
            }
        }
        .sheet(isPresented: $showSheet) {
            PatientIdentifierSheet(
                sessionId: sessionId,
                identifier: $identifier,
                isPresented: $showSheet
            )
        }
    }

    // MARK: Row variants

    private func setRow(value: String) -> some View {
        Button {
            AurionHaptics.selection()
            showSheet = true
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "person.text.rectangle.fill")
                    .font(.system(size: 16))
                    .foregroundColor(.aurionGold)
                Text(value)
                    // Scale with Dynamic Type but keep the monospaced design
                    // so look-alike codes (1/l, 0/O) stay disambiguated; shrink
                    // a touch before truncating (#271 DT).
                    .monospaced()
                    .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                    .minimumScaleFactor(0.8)
                    .foregroundColor(.aurionTextPrimary)
                    .lineLimit(1)
                Spacer()
                Image(systemName: "pencil")
                    .font(.system(size: 14))
                    .foregroundColor(.aurionTextSecondary)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(Color.aurionCardBackground)
            .cornerRadius(16)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.aurionGold.opacity(0.4), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }

    private var addButton: some View {
        Button {
            AurionHaptics.selection()
            showSheet = true
        } label: {
            HStack(spacing: 12) {
                Image(systemName: "plus.circle")
                    .font(.system(size: 16))
                    .foregroundColor(.aurionTextSecondary)
                Text(L("patientId.add"))
                    .aurionFont(15, weight: .medium, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextPrimary)
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(Color.aurionCardBackground)
            .cornerRadius(16)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Edit sheet

/// Bottom sheet for entering / clearing the identifier.
///
/// Closed by:
///   * Save → server roundtrip → updates the binding + dismisses
///   * Clear → server roundtrip → sets binding to nil + dismisses
///   * Cancel → dismisses without touching state or server
///
/// While the network is in flight, all three buttons disable to
/// avoid a double-submit + the form text field locks. Errors
/// surface inline below the field; the user can retry by tapping
/// Save again. We deliberately don't auto-clear the field on
/// error — the typed value should survive a network failure.
struct PatientIdentifierSheet: View {
    let sessionId: String
    @Binding var identifier: String?
    @Binding var isPresented: Bool

    @State private var draft: String = ""
    @State private var inFlight: InFlightAction?
    @State private var errorMessage: String?

    /// Which network action is currently in flight, so the spinner
    /// renders on the tapped button only (#13) — Save and Clear share
    /// the same roundtrip but must not both show a spinner.
    private enum InFlightAction { case save, clear }

    /// Any action in flight disables every control to block a
    /// double-submit.
    private var isWorking: Bool { inFlight != nil }

    var body: some View {
        NavigationStack {
            // Scrollable form + a pinned action bar. At larger Dynamic
            // Type (or with the keyboard raised) the subtitle, field,
            // error, and privacy hint can grow past the medium detent;
            // scrolling the form while keeping Save/Clear docked at the
            // bottom keeps the actions reachable (#271).
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 16) {
                        Text(L("patientId.subtitle"))
                            .aurionFont(13, relativeTo: .footnote)
                            .foregroundColor(.aurionTextSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, 4)

                        // Text field — disables QuickType, auto-correct,
                        // auto-cap. We don't want the identifier surfacing
                        // in the predictive bar or being autocorrected to
                        // a similar-looking word.
                        TextField(L("patientId.placeholder"), text: $draft)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled(true)
                            .keyboardType(.asciiCapable)
                            .font(.system(size: 16, weight: .regular, design: .monospaced))
                            .padding(.horizontal, 12)
                            .padding(.vertical, 12)
                            .background(Color.aurionSurfaceAlt)
                            .cornerRadius(12)
                            .overlay(
                                RoundedRectangle(cornerRadius: 12)
                                    .stroke(Color.aurionBorder, lineWidth: 1)
                            )
                            .disabled(isWorking)

                        if let msg = errorMessage {
                            Text(msg)
                                .aurionFont(12, relativeTo: .caption)
                                .foregroundColor(.aurionRed)
                                .fixedSize(horizontal: false, vertical: true)
                                .padding(.horizontal, 4)
                        }

                        Text(L("patientId.privacyHint"))
                            .aurionFont(11, relativeTo: .caption2)
                            .foregroundColor(.aurionTextSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.horizontal, 4)
                            .padding(.top, 4)
                    }
                    .padding(20)
                }

                HStack(spacing: 12) {
                    if identifier != nil {
                        Button(role: .destructive) {
                            Task { await clear() }
                        } label: {
                            HStack {
                                if inFlight == .clear {
                                    ProgressView().tint(.aurionRed)
                                }
                                Text(L("patientId.clear"))
                                    .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                            }
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 14)
                        }
                        .buttonStyle(.bordered)
                        .disabled(isWorking)
                    }

                    AurionGoldButton(
                        label: inFlight == .save ? L("patientId.saving") : L("patientId.save"),
                        full: true,
                        disabled: isWorking || draft.trimmingCharacters(in: .whitespaces).isEmpty
                    ) {
                        Task { await save() }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 4)
                .padding(.bottom, 20)
            }
            .navigationTitle(L("patientId.editTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("patientId.cancel")) {
                        isPresented = false
                    }
                    .disabled(isWorking)
                }
            }
        }
        .onAppear {
            // Seed the field with the existing identifier so the
            // user can edit-in-place vs retyping from scratch.
            draft = identifier ?? ""
        }
        .presentationDetents([.medium, .large])
    }

    private func save() async {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        await runCall(.save, setting: trimmed)
    }

    private func clear() async {
        await runCall(.clear, setting: nil)
    }

    private func runCall(_ action: InFlightAction, setting value: String?) async {
        inFlight = action
        errorMessage = nil
        defer { inFlight = nil }
        do {
            _ = try await APIClient.shared.setSessionIdentifier(
                sessionId: sessionId,
                identifier: value
            )
            identifier = value
            AurionHaptics.notification(.success)
            isPresented = false
        } catch {
            AurionHaptics.notification(.error)
            // Sanitized: the underlying error may contain a server
            // message we don't want surfaced verbatim. The generic
            // copy plus the inline state is enough for the user
            // to know "try again."
            errorMessage = L("patientId.saveFailed")
        }
    }
}
