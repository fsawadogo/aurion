import SwiftUI

/// Post-encounter settings — resolved template + language before generation.
///
/// TE-4e parity (Uzziel handoff, docs/handoffs/template-engine-ios-faical.md):
/// the screen used to list the 8 built-in specialties with the profile
/// specialty pre-checked, while the note underneath already generated on the
/// visit-context-mapped template — and tapping any row silently overrode that
/// mapping with a built-in. It now mirrors the web upload form: a "Template"
/// card shows what the mapping actually RESOLVED (context pin → custom or
/// built-in → specialty default), and changing it is an explicit "Change"
/// action offering the clinician's custom templates + the built-ins. An
/// untouched card sends nothing, so the mapping always wins by default.
struct PostEncounterView: View {
    @EnvironmentObject var sessionManager: SessionManager
    @EnvironmentObject var appState: AppState
    @State private var selectedLanguage: String
    /// The session row's resolved template pin, fetched on load. nil until
    /// the fetch lands (the card shows a placeholder), then drives the
    /// resolved-name line.
    @State private var sessionRow: SessionResponse?
    /// The clinician's custom templates (own + shared) — resolves a custom
    /// pin's display name and populates the Change picker.
    @State private var customTemplates: [CustomTemplateSummary] = []
    /// Explicit override picked via Change. nil = untouched = mapping wins,
    /// nothing is sent. Applied to the session (pin replacement) on Generate.
    @State private var overridePick: TemplateOverride?
    @State private var showChangePicker = false
    @State private var isConfirming = false
    /// `true` when the session-row fetch threw; the card falls back to the
    /// specialty default with a Retry, and Generate stays available.
    @State private var resolveFailed = false
    /// Patient identifier (#61). Seeded from the session row on
    /// load; the editor binding writes back here. Stays nil when
    /// the physician doesn't set one — the backend accepts that.
    @State private var patientIdentifier: String?

    private let currentSpecialty: String

    enum TemplateOverride: Equatable {
        case builtIn(key: String)
        case custom(id: String, name: String)
    }

    private let languages = [
        ("en", "English", "\u{1F1FA}\u{1F1F8}"),
        ("fr", "Fran\u{00E7}ais", "\u{1F1EB}\u{1F1F7}"),
    ]

    init(currentSpecialty: String, profileLanguage: String = "en") {
        self.currentSpecialty = currentSpecialty
        _selectedLanguage = State(initialValue: profileLanguage)
    }

    var body: some View {
        VStack(spacing: 0) {
            AurionNavBar(title: L("postEncounter.generate")) {
                AurionTextButton(label: L("setup.back")) {
                    sessionManager.dismissPostEncounter()
                }
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    // Template section — the RESOLVED template, not a picker.
                    SectionHeader(title: L("postEncounter.template"))
                    templateCard

                    if resolveFailed {
                        ErrorBanner(
                            L("postEncounter.templatesLoadFailed"),
                            onRetry: { Task { await loadResolvedTemplate() } }
                        )
                    }

                    // Patient identifier section (#61). Optional —
                    // physician can skip it and the note still
                    // generates normally.
                    if let session = sessionManager.session {
                        SectionHeader(title: L("patientId.section"))
                        PatientIdentifierEditor(
                            sessionId: session.id,
                            identifier: $patientIdentifier
                        )
                    }

                    // Language section
                    SectionHeader(title: L("postEncounter.outputLanguage"))
                    languageCard
                }
                .padding(.horizontal, 20)
                .padding(.bottom, 20)
            }

            // Bottom bar
            VStack(spacing: 0) {
                Rectangle().fill(Color.aurionBorder).frame(height: 1)
                AurionGoldButton(label: isConfirming ? L("postEncounter.generating") : L("postEncounter.generate"), full: true, disabled: isConfirming) {
                    Task { await confirmAndProcess() }
                }
                .aurionScreenEdge()
                .padding(.vertical, 12)
            }
            .background(Color.aurionCardBackground)
        }
        .background(Color.aurionBackground)
        .task {
            await loadResolvedTemplate()
            patientIdentifier = sessionManager.session?.externalReferenceId
        }
        // Change-template picker: the clinician's custom templates lead, the
        // 8 built-ins follow — explicit action only, mirroring the note
        // screen's Options picker.
        .confirmationDialog(
            L("postEncounter.changeTemplateTitle"),
            isPresented: $showChangePicker,
            titleVisibility: .visible
        ) {
            ForEach(customTemplates) { tmpl in
                Button(tmpl.displayName) {
                    overridePick = .custom(id: tmpl.id, name: tmpl.displayName)
                }
            }
            ForEach(BuiltInTemplate.keys, id: \.self) { key in
                Button(localizedSpecialty(key)) {
                    overridePick = .builtIn(key: key)
                }
            }
            if overridePick != nil {
                Button(L("postEncounter.useMappedTemplate"), role: .destructive) {
                    overridePick = nil
                }
            }
        }
        .onChange(of: patientIdentifier) { newValue in
            sessionManager.session?.externalReferenceId = newValue
        }
    }

    // MARK: - Template card

    /// "Template: {resolved name}" + provenance line, with a Change action.
    private var templateCard: some View {
        AurionCard(padding: 16) {
            HStack(alignment: .center, spacing: 12) {
                Image(systemName: "doc.text")
                    .font(.system(size: 20))
                    .foregroundColor(.aurionGold)
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 3) {
                    Text(resolvedTemplateName)
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                        .fixedSize(horizontal: false, vertical: true)
                    Text(templateProvenance)
                        .aurionFont(12, relativeTo: .caption)
                        .foregroundColor(.aurionTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer()
                Button {
                    AurionHaptics.selection()
                    showChangePicker = true
                } label: {
                    Text(L("postEncounter.changeTemplate"))
                        .aurionFont(14, weight: .medium, relativeTo: .footnote)
                        .foregroundColor(.aurionGoldDark)
                        .frame(minHeight: 44)
                }
                .buttonStyle(.plain)
            }
        }
    }

    /// Display name for what Stage 1 will generate with, in precedence order:
    /// explicit override → session custom pin → session built-in pin →
    /// specialty default.
    private var resolvedTemplateName: String {
        switch overridePick {
        case .builtIn(let key): return localizedSpecialty(key)
        case .custom(_, let name): return name
        case nil: break
        }
        guard let row = sessionRow else {
            // Fetch pending/failed — the specialty default is the honest floor.
            return localizedSpecialty(currentSpecialty)
        }
        if let customID = row.customTemplateId {
            if let match = customTemplates.first(where: { $0.id == customID }) {
                return match.displayName
            }
            // Pin exists but the name lookup hasn't resolved (shared template
            // list still loading, or fetch failed): say so honestly rather
            // than showing the wrong built-in name.
            return L("postEncounter.customTemplate")
        }
        if let key = row.templateKey {
            return localizedSpecialty(key)
        }
        return localizedSpecialty(row.specialty)
    }

    /// One-line provenance under the name, so "my template applied" and "the
    /// default applied" are visually distinct (Uzziel: silent-fallback gap).
    private var templateProvenance: String {
        if overridePick != nil { return L("postEncounter.templateOverridden") }
        guard let row = sessionRow else { return L("postEncounter.templateResolving") }
        if row.customTemplateId != nil || row.templateKey != nil {
            return L("postEncounter.templateFromMapping")
        }
        return L("postEncounter.templateSpecialtyDefault")
    }

    private var languageCard: some View {
        AurionCard(padding: 0) {
            VStack(spacing: 0) {
                ForEach(Array(languages.enumerated()), id: \.element.0) { index, lang in
                    let (key, name, flag) = lang
                    let isSelected = selectedLanguage == key
                    Button {
                        AurionHaptics.selection()
                        selectedLanguage = key
                    } label: {
                        HStack(spacing: 12) {
                            Text(flag).aurionFont(22, relativeTo: .title2)
                            Text(name)
                                .aurionFont(15, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextPrimary)
                            Spacer()
                            if isSelected {
                                Image(systemName: "checkmark")
                                    .font(.system(size: 16, weight: .medium))
                                    .foregroundColor(.aurionGold)
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 14)
                        .background(isSelected ? Color.aurionGold.opacity(0.08) : Color.clear)
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(isSelected ? .isSelected : [])

                    if index < languages.count - 1 {
                        Divider().padding(.leading, 16)
                    }
                }
            }
        }
    }

    // MARK: - Data

    /// Fetch the session row (for its resolved pin) + the custom-template
    /// list (for a custom pin's display name and the Change picker).
    private func loadResolvedTemplate() async {
        resolveFailed = false
        guard let session = sessionManager.session else { return }
        async let rowTask = APIClient.shared.getSession(sessionId: session.id)
        async let templatesTask = APIClient.shared.getCustomTemplates()
        do {
            sessionRow = try await rowTask
        } catch {
            resolveFailed = true
        }
        // Custom-template fetch failing alone shouldn't banner the screen —
        // it only affects a custom pin's display name and the picker's
        // custom section, both of which degrade gracefully.
        customTemplates = (try? await templatesTask) ?? []
    }

    private func confirmAndProcess() async {
        isConfirming = true
        // Only an EXPLICIT pick sends anything — an untouched card means the
        // server-side mapping stays authoritative (the old screen PATCHed the
        // specialty whenever the checked row differed, silently clobbering
        // the visit-context pin).
        if let session = sessionManager.session, let pick = overridePick {
            switch pick {
            case .builtIn(let key):
                _ = try? await APIClient.shared.overrideSessionTemplate(
                    sessionId: session.id, templateKey: key
                )
            case .custom(let id, _):
                _ = try? await APIClient.shared.overrideSessionTemplate(
                    sessionId: session.id, customTemplateId: id
                )
            }
        }
        await sessionManager.submitProcessing()
        isConfirming = false
    }
}
