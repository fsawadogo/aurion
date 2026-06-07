import SwiftUI

/// The 8 built-in note templates a context can pin to (#315, I1).
///
/// Mirrors the keys returned by the backend `list_available_templates()`
/// (`backend/app/modules/note_gen/service.py`) and the membership gate in
/// `VisitTypeContext._validate` (`backend/app/api/v1/profile.py`). Kept here
/// as the single client-side source of truth so the picker and the parity
/// test (`CustomVisitTypeTests`) agree with the server.
enum BuiltInTemplate {
    static let keys: [String] = [
        "general",
        "emergency_medicine",
        "family_medicine",
        "internal_medicine",
        "musculoskeletal",
        "orthopedic_surgery",
        "pediatrics",
        "plastic_surgery",
    ]
}

/// Localized display name for a built-in template key. Template keys ARE
/// specialty keys, so this delegates to ``localizedSpecialty`` — which resolves
/// `specialty.<key>` (all 8 keys carry EN+FR strings) and falls back to a
/// humanized form for any post-pilot key without a translation.
func localizedTemplate(_ key: String) -> String {
    localizedSpecialty(key)
}

/// Level-2 editor nested under a visit-type chip (#315, I1).
///
/// Renders the contexts hanging under one visit type as Add/Delete chips —
/// the SAME pattern as the custom-visit-type editor in
/// ``PhysicianProfileSetupView`` and ``TeamMemberEditorView`` — and gives each
/// context a built-in template picker. The label gate is shared with
/// ``PhysicianProfileSetupView/validateCustomVisitType(_:existing:)`` so the
/// 60-char cap, SSN/email/proper-noun-pair rejection, and `reject_full_name`
/// OFF behaviour stay identical to custom visit-type labels.
///
/// Binds directly to the parent's per-visit-type context array so edits flow
/// back into the profile save payload. Server assigns `id` for new contexts
/// (sent as `serverID == ""`); existing ids round-trip untouched.
struct VisitTypeContextEditor: View {
    /// The visit-type key these contexts hang under — also the payload key.
    let visitTypeKey: String
    /// Localized visit-type label, used only in accessibility strings.
    let visitTypeLabel: String
    @Binding var contexts: [VisitTypeContext]

    /// Per-visit-type soft cap. MUST equal `_MAX_CONTEXTS_PER_VISIT_TYPE`
    /// (30) in `backend/app/api/v1/profile.py` so a client can't add past
    /// the cap and then eat a 422 on save. Pinned by `CustomVisitTypeTests`.
    static let maxContexts = 30

    @State private var isAdding = false
    @State private var draft = ""
    @State private var draftError: String?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach($contexts) { $ctx in
                contextRow($ctx)
            }

            if isAdding {
                addInline
            } else if contexts.count >= Self.maxContexts {
                Text(L("setup.context.limit"))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionTextSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 14)
            } else {
                addButton
            }
        }
        .padding(.leading, 14)
        .padding(.bottom, 4)
    }

    // MARK: - Context row (label + template picker + delete)

    private func contextRow(_ ctx: Binding<VisitTypeContext>) -> some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 6) {
                Text(ctx.wrappedValue.label)
                    .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                templateMenu(ctx)
            }
            Spacer(minLength: 8)
            Button {
                AurionHaptics.selection()
                withAnimation(.aurionIOS) {
                    contexts.removeAll { $0.id == ctx.wrappedValue.id }
                }
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundColor(.aurionTextSecondary)
                    .frame(minWidth: 44, minHeight: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(L("setup.context.delete", ctx.wrappedValue.label))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color.aurionBackground)
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.sm)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
    }

    /// "Use my specialty default" (→ nil) + the 8 built-in templates by
    /// localized display name. A leading checkmark marks the active choice.
    private func templateMenu(_ ctx: Binding<VisitTypeContext>) -> some View {
        Menu {
            Button {
                AurionHaptics.selection()
                ctx.wrappedValue.templateKey = nil
            } label: {
                if ctx.wrappedValue.templateKey == nil {
                    Label(L("setup.context.template.default"), systemImage: "checkmark")
                } else {
                    Text(L("setup.context.template.default"))
                }
            }
            Divider()
            ForEach(BuiltInTemplate.keys, id: \.self) { key in
                Button {
                    AurionHaptics.selection()
                    ctx.wrappedValue.templateKey = key
                } label: {
                    if ctx.wrappedValue.templateKey == key {
                        Label(localizedTemplate(key), systemImage: "checkmark")
                    } else {
                        Text(localizedTemplate(key))
                    }
                }
            }
        } label: {
            HStack(spacing: 6) {
                Image(systemName: "doc.text")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(.aurionGoldDark)
                Text(templateLabel(ctx.wrappedValue.templateKey))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionTextSecondary)
                    .lineLimit(1)
                Image(systemName: "chevron.up.chevron.down")
                    .font(.system(size: 9, weight: .semibold))
                    .foregroundColor(.aurionTextSecondary)
            }
            .padding(.vertical, 2)
            .contentShape(Rectangle())
        }
        .accessibilityLabel(
            L("setup.context.template.a11y", templateLabel(ctx.wrappedValue.templateKey))
        )
    }

    private func templateLabel(_ key: String?) -> String {
        guard let key else { return L("setup.context.template.default") }
        return localizedTemplate(key)
    }

    // MARK: - Add affordance

    private var addButton: some View {
        Button {
            AurionHaptics.selection()
            draft = ""
            draftError = nil
            withAnimation(.aurionIOS) { isAdding = true }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "plus.circle")
                    .font(.system(size: 16))
                    .foregroundColor(.aurionGold)
                Text(L("setup.context.add"))
                    .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                    .foregroundColor(.aurionTextPrimary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .frame(minHeight: 44, alignment: .leading)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }

    private var addInline: some View {
        VStack(alignment: .leading, spacing: 8) {
            TextField(L("setup.context.placeholder"), text: $draft)
                .aurionFont(15, relativeTo: .subheadline)
                .autocorrectionDisabled()
                .submitLabel(.done)
                .onChange(of: draft) { _, newValue in
                    draftError = PhysicianProfileSetupView.validateCustomVisitType(
                        newValue,
                        existing: contexts.map { $0.label }
                    )
                }
                .onSubmit { commit() }

            if let err = draftError, !draft.isEmpty {
                Text(err)
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(.aurionRed)
            }

            HStack(spacing: 12) {
                Spacer()
                // Explicit `.borderless` so each button keeps its own hit
                // target — mirrors the TeamMemberEditorView fix (#274).
                Button(L("setup.context.cancel")) {
                    withAnimation(.aurionIOS) {
                        isAdding = false
                        draft = ""
                        draftError = nil
                    }
                }
                .buttonStyle(.borderless)
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)

                Button(L("setup.context.commit")) { commit() }
                    .buttonStyle(.borderless)
                    .disabled(!canCommit)
                    .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                    .foregroundColor(canCommit ? .aurionGold : .aurionMutedGray)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(Color.aurionBackground)
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.sm)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
    }

    private var canCommit: Bool {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty
            && draftError == nil
            && contexts.count < Self.maxContexts
    }

    private func commit() {
        let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              PhysicianProfileSetupView.validateCustomVisitType(
                  trimmed, existing: contexts.map { $0.label }
              ) == nil,
              contexts.count < Self.maxContexts
        else { return }
        withAnimation(.aurionIOS) {
            // serverID "" tells the backend "new" — it mints a stable
            // ctx_<hex> id we then preserve on subsequent saves.
            contexts.append(VisitTypeContext(serverID: "", label: trimmed))
            draft = ""
            draftError = nil
            isAdding = false
        }
        AurionHaptics.notification(.success)
    }
}
