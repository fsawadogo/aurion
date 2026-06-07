import SwiftUI

/// Post-encounter settings — matches design PostEncounterScreen.
/// Template selection + language picker before note generation.
struct PostEncounterView: View {
    @EnvironmentObject var sessionManager: SessionManager
    @EnvironmentObject var appState: AppState
    @State private var selectedTemplate: String
    @State private var selectedLanguage: String
    @State private var preferredTemplates: [TemplateResponse] = []
    @State private var isLoadingTemplates = false
    /// `true` when the template fetch threw. We still fall back to the
    /// current specialty so the physician can proceed, but we surface an
    /// inline error + Retry rather than silently masking the failure as a
    /// one-item list.
    @State private var templatesLoadFailed = false
    @State private var isConfirming = false
    /// Patient identifier (#61). Seeded from the session row on
    /// load; the editor binding writes back here. Stays nil when
    /// the physician doesn't set one — the backend accepts that.
    @State private var patientIdentifier: String?

    private let languages = [
        ("en", "English", "\u{1F1FA}\u{1F1F8}"),
        ("fr", "Fran\u{00E7}ais", "\u{1F1EB}\u{1F1F7}"),
    ]

    init(currentSpecialty: String, profileLanguage: String = "en") {
        _selectedTemplate = State(initialValue: currentSpecialty)
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
                    // Template section
                    SectionHeader(title: L("postEncounter.template"))

                    // Templates in a single card with dividers
                    VStack(spacing: 0) {
                        if isLoadingTemplates {
                            HStack { Spacer(); ProgressView(); Spacer() }
                                .padding(16)
                        } else {
                            ForEach(Array(preferredTemplates.enumerated()), id: \.element.key) { index, template in
                                Button {
                                    AurionHaptics.selection()
                                    selectedTemplate = template.key
                                } label: {
                                    HStack {
                                        Text(localizedSpecialty(template.key))
                                            .aurionFont(15, relativeTo: .subheadline)
                                            .foregroundColor(.aurionTextPrimary)
                                        Spacer()
                                        if selectedTemplate == template.key {
                                            Image(systemName: "checkmark")
                                                .font(.system(size: 16, weight: .medium))
                                                .foregroundColor(.aurionGold)
                                        }
                                    }
                                    .padding(.horizontal, 16)
                                    .padding(.vertical, 14)
                                }
                                .buttonStyle(.plain)

                                if index < preferredTemplates.count - 1 {
                                    Divider().padding(.leading, 16)
                                }
                            }
                        }
                    }
                    .background(Color.aurionCardBackground)
                    .cornerRadius(16)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16)
                            .stroke(Color.aurionBorder, lineWidth: 1)
                    )

                    // Inline failure surface for the template fetch. The
                    // list above still shows the current-specialty fallback
                    // so the physician isn't blocked; this just makes the
                    // failure honest and offers a Retry.
                    if templatesLoadFailed {
                        ErrorBanner(
                            L("postEncounter.templatesLoadFailed"),
                            onRetry: { Task { await loadTemplates() } }
                        )
                    }

                    // Patient identifier section (#61). Optional —
                    // physician can skip it and the note still
                    // generates normally. When set, the backend
                    // attaches it to the FHIR DocumentReference
                    // (#57) and surfaces prior encounters for the
                    // same identifier in the inbox.
                    if let session = sessionManager.session {
                        SectionHeader(title: L("patientId.section"))
                        PatientIdentifierEditor(
                            sessionId: session.id,
                            identifier: $patientIdentifier
                        )
                    }

                    // Language section
                    SectionHeader(title: L("postEncounter.outputLanguage"))

                    VStack(spacing: 0) {
                        ForEach(Array(languages.enumerated()), id: \.element.0) { index, lang in
                            let (key, name, flag) = lang
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
                                    if selectedLanguage == key {
                                        Image(systemName: "checkmark")
                                            .font(.system(size: 16, weight: .medium))
                                            .foregroundColor(.aurionGold)
                                    }
                                }
                                .padding(.horizontal, 16)
                                .padding(.vertical, 14)
                            }
                            .buttonStyle(.plain)

                            if index < languages.count - 1 {
                                Divider().padding(.leading, 16)
                            }
                        }
                    }
                    .background(Color.aurionCardBackground)
                    .cornerRadius(16)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16)
                            .stroke(Color.aurionBorder, lineWidth: 1)
                    )
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
            await loadTemplates()
            // Seed the identifier from the session row. The
            // SessionResponse decoder reads `external_reference_id`
            // when the server returns it (owning clinician + admin
            // only); otherwise nil and the editor renders the
            // "Add" CTA.
            patientIdentifier = sessionManager.session?.externalReferenceId
        }
        // Propagate identifier changes from the editor back to the
        // CaptureSession so other views (capture screen, inbox,
        // export sheet) see the new value without an API round-trip.
        // The editor itself has already persisted to the backend
        // before this fires. Uses the iOS 16-compatible single-arg
        // onChange signature (we ship iOS 16+ per CLAUDE.md).
        .onChange(of: patientIdentifier) { newValue in
            sessionManager.session?.externalReferenceId = newValue
        }
    }

    private func loadTemplates() async {
        isLoadingTemplates = true
        do {
            preferredTemplates = try await APIClient.shared.getPreferredTemplates()
            templatesLoadFailed = false
        } catch {
            templatesLoadFailed = true
            // Keep a usable fallback (the current specialty) so Generate
            // still works, but only seed it if we have nothing yet — a
            // Retry that fails again shouldn't clobber a prior good list.
            if preferredTemplates.isEmpty {
                preferredTemplates = [
                    TemplateResponse(key: selectedTemplate, displayName: selectedTemplate.displayFormatted, sections: [])
                ]
            }
        }
        isLoadingTemplates = false
    }

    private func confirmAndProcess() async {
        isConfirming = true
        if let session = sessionManager.session, selectedTemplate != session.specialty {
            _ = try? await APIClient.shared.updateSessionTemplate(sessionId: session.id, specialty: selectedTemplate)
        }
        await sessionManager.submitProcessing()
        isConfirming = false
    }
}
