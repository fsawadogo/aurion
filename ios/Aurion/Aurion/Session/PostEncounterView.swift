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
    @State private var isConfirming = false

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
            AurionNavBar(title: "Generate Note") {
                AurionTextButton(label: "Back") {
                    sessionManager.showingPostEncounter = false
                }
            }

            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    // Template section
                    SectionHeader(title: "Template")

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
                                        Text(template.displayName)
                                            .font(.system(size: 15))
                                            .foregroundColor(.aurionNavy)
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

                    // Language section
                    SectionHeader(title: "Output Language")

                    VStack(spacing: 0) {
                        ForEach(Array(languages.enumerated()), id: \.element.0) { index, lang in
                            let (key, name, flag) = lang
                            Button {
                                AurionHaptics.selection()
                                selectedLanguage = key
                            } label: {
                                HStack(spacing: 12) {
                                    Text(flag).font(.system(size: 22))
                                    Text(name)
                                        .font(.system(size: 15))
                                        .foregroundColor(.aurionNavy)
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
                AurionGoldButton(label: isConfirming ? "Generating…" : "Generate Note", full: true, disabled: isConfirming) {
                    Task { await confirmAndProcess() }
                }
                .padding(.horizontal, AurionSpacing.edgeIPhone)
                .padding(.vertical, 12)
            }
            .background(Color.aurionCardBackground)
        }
        .background(Color.aurionBackground)
        .task { await loadTemplates() }
    }

    private func loadTemplates() async {
        isLoadingTemplates = true
        do {
            preferredTemplates = try await APIClient.shared.getPreferredTemplates()
        } catch {
            preferredTemplates = [
                TemplateResponse(key: selectedTemplate, displayName: selectedTemplate.displayFormatted, sections: [])
            ]
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
