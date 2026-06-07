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

    /// The caller's custom note templates (#319 I3), fetched once by the
    /// parent and threaded down so every context picker shares one list.
    /// Empty when the clinician has no custom templates (the picker then
    /// shows only the default + the 8 built-ins). Display names are
    /// clinician-authored → potentially PHI; never log them.
    var customTemplates: [CustomTemplateSummary] = []
    /// Whether ``customTemplates`` reflects a COMPLETED fetch. Gates the
    /// "template unavailable" affordance so an in-flight (or failed) load
    /// doesn't misreport a still-valid `template_ref` as deleted.
    var customTemplatesLoaded: Bool = false

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

    /// "Use my specialty default" (→ both nil) + the 8 built-in templates +,
    /// when the clinician has any, a "Custom templates" section listing their
    /// `/me/custom-templates` rows by display name. A leading checkmark marks
    /// the active choice.
    ///
    /// `template_key` (built-in) and `template_ref` (custom UUID) are mutually
    /// exclusive: picking a built-in clears the custom ref and vice-versa;
    /// "specialty default" clears both. The backend re-validates this.
    private func templateMenu(_ ctx: Binding<VisitTypeContext>) -> some View {
        let value = ctx.wrappedValue
        let isDefault = value.templateKey == nil && value.templateRef == nil
        return Menu {
            // ── Specialty default (both nil) ──────────────────────────
            Button {
                AurionHaptics.selection()
                ctx.wrappedValue.templateKey = nil
                ctx.wrappedValue.templateRef = nil
            } label: {
                if isDefault {
                    Label(L("setup.context.template.default"), systemImage: "checkmark")
                } else {
                    Text(L("setup.context.template.default"))
                }
            }
            Divider()
            // ── 8 built-ins (set template_key, clear template_ref) ────
            ForEach(BuiltInTemplate.keys, id: \.self) { key in
                Button {
                    AurionHaptics.selection()
                    ctx.wrappedValue.templateKey = key
                    ctx.wrappedValue.templateRef = nil
                } label: {
                    if value.templateRef == nil && value.templateKey == key {
                        Label(localizedTemplate(key), systemImage: "checkmark")
                    } else {
                        Text(localizedTemplate(key))
                    }
                }
            }
            // ── Custom templates (set template_ref, clear template_key) ─
            // Section omitted entirely when the library is empty so the
            // picker degrades to default + built-ins (AC: empty library).
            if !customTemplates.isEmpty {
                Section(L("setup.context.template.customSection")) {
                    ForEach(customTemplates) { tmpl in
                        Button {
                            AurionHaptics.selection()
                            ctx.wrappedValue.templateRef = tmpl.id
                            ctx.wrappedValue.templateKey = nil
                        } label: {
                            if value.templateRef == tmpl.id {
                                Label(tmpl.displayName, systemImage: "checkmark")
                            } else {
                                Text(tmpl.displayName)
                            }
                        }
                    }
                }
            }
        } label: {
            let resolved = resolvedTemplate(value)
            HStack(spacing: 6) {
                Image(systemName: resolved.unavailable ? "exclamationmark.triangle" : "doc.text")
                    .font(.system(size: 11, weight: .medium))
                    .foregroundColor(resolved.unavailable ? .aurionTextSecondary : .aurionGoldDark)
                Text(resolved.text)
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
            L("setup.context.template.a11y", resolvedTemplate(value).text)
        )
    }

    /// The label shown on the picker trigger for a context's current binding,
    /// plus whether it's the stale-ref state.
    ///
    /// A `template_ref` is resolved against the fetched ``customTemplates``.
    /// If it isn't found we only call it "unavailable" once the list has
    /// actually loaded (``customTemplatesLoaded``) — while a fetch is in
    /// flight (or has failed) an empty list would otherwise misreport every
    /// ref as deleted, so we show a neutral placeholder instead.
    private func resolvedTemplate(_ ctx: VisitTypeContext) -> (text: String, unavailable: Bool) {
        if let ref = ctx.templateRef {
            if let match = customTemplates.first(where: { $0.id == ref }) {
                return (match.displayName, false)
            }
            if customTemplatesLoaded {
                return (L("setup.context.template.unavailable"), true)
            }
            return (L("setup.context.template.customPlaceholder"), false)
        }
        if let key = ctx.templateKey {
            return (localizedTemplate(key), false)
        }
        return (L("setup.context.template.default"), false)
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
