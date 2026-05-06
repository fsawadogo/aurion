import SwiftUI

/// Profile setup — pixel-perfect port of `ui_kits/ios/screens.jsx → ProfileSetupScreen`.
/// Five steps, in the order the design specifies: practice → specialty → visits →
/// templates → language. Step indicator + 4pt gold progress bar at top, paired
/// Back / Continue bar at bottom.
struct PhysicianProfileSetupView: View {
    @EnvironmentObject var appState: AppState

    @State private var step = 0
    // Practice types are multi-select — a clinician may run a clinic AND a
    // surgical center. Wire format is a comma-joined string in `practice_type`
    // for backward compat with the existing backend column.
    @State private var practiceTypes: Set<String> = ["clinic"]
    @State private var primarySpecialty = "orthopedic_surgery"
    @State private var consultationTypes: Set<String> = ["new_patient", "follow_up"]
    @State private var preferredTemplates: Set<String> = []
    @State private var outputLanguage = "en"
    @State private var isSaving = false
    @State private var error: String?

    private let totalSteps = 5

    private let practiceTypes_options: [(id: String, label: String, sub: String, icon: String)] = [
        ("clinic", "Clinic", "Outpatient practice", "building.2"),
        ("surgical_center", "Surgical Center", "Procedural facility", "cross.case"),
        ("hospital", "Hospital", "Inpatient setting", "building.columns"),
    ]

    private let specialties: [(id: String, label: String)] = [
        ("orthopedic_surgery", "Orthopedic Surgery"),
        ("plastic_surgery", "Plastic Surgery"),
        ("musculoskeletal", "Musculoskeletal"),
        ("emergency_medicine", "Emergency Medicine"),
        ("general", "General"),
    ]

    private let visitTypes: [(id: String, label: String)] = [
        ("new_patient", "New Patient"),
        ("follow_up", "Follow-up"),
        ("pre_op", "Pre-Op"),
        ("post_op", "Post-Op"),
    ]

    private let languages: [(id: String, label: String, sub: String, flag: String)] = [
        ("en", "English", "United States", "🇺🇸"),
        ("fr", "Français", "France", "🇫🇷"),
    ]

    private var stepTitle: String {
        switch step {
        case 0: return "What type of practice?"
        case 1: return "Primary specialty?"
        case 2: return "Common visit types?"
        case 3: return "Preferred templates?"
        case 4: return "Output language?"
        default: return ""
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            header
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    Text(stepTitle).aurionDisplay()
                    stepContent
                }
                .padding(.horizontal, AurionSpacing.edgeIPhone)
                .padding(.top, 4)
                .padding(.bottom, 20)
            }
            footer
        }
        .background(Color.aurionBackground)
    }

    // MARK: - Header

    private var header: some View {
        VStack(spacing: 8) {
            HStack {
                Text("Step \(step + 1) of \(totalSteps)")
                    .font(.system(size: 12))
                    .foregroundColor(.aurionTextSecondary)
                Spacer()
                Button("Skip") {
                    appState.hasCompletedProfileSetup = true
                }
                .font(.system(size: 12))
                .foregroundColor(.aurionTextSecondary)
            }
            AurionProgressBar(value: Double(step + 1) / Double(totalSteps))
        }
        .padding(.horizontal, AurionSpacing.edgeIPhone)
        .padding(.top, 12)
        .padding(.bottom, AurionSpacing.md)
    }

    // MARK: - Footer (Back + Continue)

    private var footer: some View {
        VStack(spacing: 0) {
            Rectangle().fill(Color.aurionBorder).frame(height: 1)
            HStack(spacing: 12) {
                if step > 0 {
                    AurionGhostButton(label: "Back", full: true) {
                        withAnimation(.aurionIOS) { step -= 1 }
                    }
                    .frame(maxWidth: .infinity)
                }
                AurionGoldButton(
                    label: step == totalSteps - 1
                        ? (isSaving ? "Saving…" : "Get Started")
                        : "Continue",
                    full: true,
                    disabled: isSaving
                ) {
                    advance()
                }
                .frame(maxWidth: .infinity)
                .layoutPriority(2)
            }
            .padding(.horizontal, AurionSpacing.edgeIPhone)
            .padding(.vertical, 12)
            .padding(.bottom, 8)
        }
        .background(Color.aurionCardBackground)
    }

    private func advance() {
        if step < totalSteps - 1 {
            withAnimation(.aurionIOS) {
                if step == 1 && preferredTemplates.isEmpty {
                    preferredTemplates = [primarySpecialty]
                }
                step += 1
            }
        } else {
            Task { await saveProfile() }
        }
    }

    // MARK: - Step content

    @ViewBuilder
    private var stepContent: some View {
        switch step {
        case 0: practiceStep
        case 1: specialtyStep
        case 2: visitTypesStep
        case 3: templatesStep
        case 4: languageStep
        default: EmptyView()
        }
    }

    private var practiceStep: some View {
        VStack(spacing: 12) {
            ForEach(self.practiceTypes_options, id: \.id) { o in
                AurionSelectableCard(
                    icon: o.icon,
                    title: o.label,
                    subtitle: o.sub,
                    selected: practiceTypes.contains(o.id)
                ) {
                    if practiceTypes.contains(o.id) {
                        // Don't allow deselecting the last option — the
                        // clinician needs at least one practice type set.
                        if practiceTypes.count > 1 {
                            practiceTypes.remove(o.id)
                        }
                    } else {
                        practiceTypes.insert(o.id)
                    }
                }
            }
        }
    }

    private var specialtyStep: some View {
        VStack(spacing: 8) {
            ForEach(specialties, id: \.id) { o in
                radioRow(label: o.label, selected: primarySpecialty == o.id) {
                    primarySpecialty = o.id
                }
            }
        }
    }

    private var visitTypesStep: some View {
        VStack(spacing: 8) {
            ForEach(visitTypes, id: \.id) { o in
                checkboxRow(label: o.label, on: consultationTypes.contains(o.id)) {
                    if consultationTypes.contains(o.id) {
                        consultationTypes.remove(o.id)
                    } else {
                        consultationTypes.insert(o.id)
                    }
                }
            }
        }
    }

    private var templatesStep: some View {
        VStack(spacing: 8) {
            ForEach(specialties, id: \.id) { o in
                checkboxRow(label: o.label, on: preferredTemplates.contains(o.id), fontSize: 15) {
                    if preferredTemplates.contains(o.id) {
                        preferredTemplates.remove(o.id)
                    } else {
                        preferredTemplates.insert(o.id)
                    }
                }
            }
        }
    }

    private var languageStep: some View {
        VStack(spacing: 12) {
            ForEach(languages, id: \.id) { o in
                Button {
                    AurionHaptics.selection()
                    outputLanguage = o.id
                } label: {
                    HStack(spacing: 14) {
                        Text(o.flag).font(.system(size: 32))
                        VStack(alignment: .leading, spacing: 2) {
                            Text(o.label)
                                .font(.system(size: 17, weight: .semibold))
                                .foregroundColor(.aurionNavy)
                            Text(o.sub)
                                .font(.system(size: 13))
                                .foregroundColor(.aurionTextSecondary)
                        }
                        Spacer(minLength: 0)
                        if outputLanguage == o.id {
                            Image(systemName: "checkmark.circle.fill")
                                .font(.system(size: 22))
                                .foregroundColor(.aurionGold)
                        }
                    }
                    .padding(18)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .background(Color.aurionCardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: AurionRadius.lg)
                            .stroke(outputLanguage == o.id ? Color.aurionGold : Color.aurionBorder,
                                    lineWidth: outputLanguage == o.id ? 2 : 1)
                    )
                    .clipShape(RoundedRectangle(cornerRadius: AurionRadius.lg))
                }
                .buttonStyle(.plain)
            }
        }
    }

    // MARK: - Row primitives

    private func radioRow(label: String, selected: Bool, action: @escaping () -> Void) -> some View {
        Button {
            AurionHaptics.selection()
            action()
        } label: {
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .stroke(selected ? Color.aurionGold : Color(red: 198/255, green: 202/255, blue: 210/255), lineWidth: 2)
                        .frame(width: 20, height: 20)
                    if selected {
                        Circle().fill(Color.aurionGold).frame(width: 10, height: 10)
                    }
                }
                Text(label)
                    .font(.system(size: 16))
                    .foregroundColor(.aurionNavy)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(Color.aurionCardBackground)
            .overlay(
                RoundedRectangle(cornerRadius: AurionRadius.md)
                    .stroke(selected ? Color.aurionGold : Color.aurionBorder, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
        }
        .buttonStyle(.plain)
    }

    private func checkboxRow(label: String, on: Bool, fontSize: CGFloat = 16, action: @escaping () -> Void) -> some View {
        Button {
            AurionHaptics.selection()
            action()
        } label: {
            HStack(spacing: 12) {
                ZStack {
                    RoundedRectangle(cornerRadius: AurionRadius.xs)
                        .fill(on ? Color.aurionGold : Color.clear)
                        .frame(width: 22, height: 22)
                        .overlay(
                            RoundedRectangle(cornerRadius: AurionRadius.xs)
                                .stroke(on ? Color.aurionGold : Color(red: 198/255, green: 202/255, blue: 210/255), lineWidth: 2)
                        )
                    if on {
                        Image(systemName: "checkmark")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundColor(.aurionNavy)
                    }
                }
                Text(label)
                    .font(.system(size: fontSize))
                    .foregroundColor(.aurionNavy)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(Color.aurionCardBackground)
            .overlay(
                RoundedRectangle(cornerRadius: AurionRadius.md)
                    .stroke(on ? Color.aurionGold : Color.aurionBorder, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
        }
        .buttonStyle(.plain)
    }

    // MARK: - Save

    private func saveProfile() async {
        isSaving = true
        error = nil
        defer { isSaving = false }
        do {
            // Comma-joined values keep the wire shape (single string) compatible
            // with the existing backend column while supporting multi-select.
            let updates: [String: Any] = [
                "practice_type": practiceTypes.sorted().joined(separator: ","),
                "primary_specialty": primarySpecialty,
                "preferred_templates": Array(preferredTemplates),
                "consultation_types": Array(consultationTypes),
                "output_language": outputLanguage,
            ]
            let profile = try await APIClient.shared.updateProfile(updates)
            appState.physicianProfile = profile
            appState.hasCompletedProfileSetup = true
            AurionHaptics.notification(.success)
        } catch {
            self.error = "Failed to save: \(error.localizedDescription)"
            AurionHaptics.notification(.error)
        }
    }
}
