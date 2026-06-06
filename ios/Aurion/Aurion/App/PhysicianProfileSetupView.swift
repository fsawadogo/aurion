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
    // GH-259 — clinician-authored consultation types, e.g. Marie's
    // "LL new pt" / "LL fu" or Perry's "breast visit". Stored in
    // insertion order so the UI shows the most-recent at the bottom
    // of the list (matches the "add to end" mental model). On save
    // they're merged with `consultationTypes` and shipped to the
    // backend as a single list[str] (the column has always accepted
    // arbitrary strings; the validation widens server-side).
    @State private var customConsultationTypes: [String] = []
    @State private var customTypeDraft: String = ""
    @State private var customTypeDraftError: String?
    @State private var isAddingCustomType = false
    @State private var preferredTemplates: Set<String> = []
    @State private var outputLanguage = "en"
    // Step 5 — recording preferences. Stored locally (UserDefaults) since
    // the backend doesn't yet have these fields. `RecordingPreferences.load()`
    // populates from UserDefaults so re-running profile setup keeps prior
    // choices.
    @State private var recordingPrefs: RecordingPreferences = .load()
    @State private var isSaving = false
    @State private var error: String?

    private let totalSteps = 6

    // Practice-type rows: id + icon are static; the label and subtitle are
    // resolved through localized helpers at render time (see practiceStep).
    private let practiceTypes_options: [(id: String, subKey: String, icon: String)] = [
        ("clinic", "setup.practice.clinic.sub", "building.2"),
        ("surgical_center", "setup.practice.surgical.sub", "cross.case"),
        ("hospital", "setup.practice.hospital.sub", "building.columns"),
    ]

    private let specialties: [String] = [
        "orthopedic_surgery",
        "plastic_surgery",
        "musculoskeletal",
        "emergency_medicine",
        "general",
    ]

    private let visitTypes: [String] = [
        "new_patient",
        "follow_up",
        "pre_op",
        "post_op",
    ]
    /// Canonical default visit-type keys — mirrors
    /// ``_DEFAULT_CONSULTATION_TYPES`` in ``backend/app/api/v1/profile.py``.
    /// Used to partition the wire-format ``consultation_types`` list
    /// into "checkbox" defaults and clinician-authored customs on
    /// re-entry into the setup flow (Profile → Edit Practice).
    /// `internal` visibility so the AurionTests target can assert
    /// parity with the backend.
    static let defaultVisitTypeKeys: Set<String> = [
        "new_patient",
        "follow_up",
        "pre_op",
        "post_op",
    ]

    /// Soft cap on custom consultation types — mirrors
    /// ``_MAX_CUSTOM_CONSULTATION_TYPES`` (20) in
    /// ``backend/app/api/v1/profile.py``.
    static let maxCustomTypes = 20

    /// Cheap PHI-shape gate that mirrors the backend ``validate_user_text``
    /// helper used by ``_validate_consultation_type``. Returns ``nil`` when
    /// the candidate passes, otherwise a localized error string. `internal`
    /// so ``CustomVisitTypeTests`` can exercise the same gate the UI uses.
    static func validateCustomVisitType(
        _ raw: String,
        existing: [String]
    ) -> String? {
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        if trimmed.isEmpty {
            // Empty draft is a "not yet typed" state — the caller (the
            // Add button's disabled binding) handles it. Returning nil
            // keeps the visual error chrome quiet until the user has
            // actually typed something invalid.
            return nil
        }
        if trimmed.count > 60 {
            return L("setup.visit.custom.error.tooLong")
        }
        if (try? Self.ssnRawRE.wholeMatch(in: trimmed)) != nil
            || (try? Self.ssnDashedRE.wholeMatch(in: trimmed)) != nil
        {
            return L("setup.visit.custom.error.ssn")
        }
        if trimmed.contains("@") {
            return L("setup.visit.custom.error.email")
        }
        // Two-token proper-noun shape — catches "Jane Doe" / "Marie
        // Gdalevitch" without rejecting legitimate clinician shorthand
        // like "LL fu" / "Breast visit". Mirrors the backend
        // `_looks_like_proper_noun_pair` heuristic exactly.
        let tokens = trimmed.split(whereSeparator: \.isWhitespace)
        if tokens.count >= 2,
           tokens.allSatisfy({ tok in
               guard let first = tok.first, first.isUppercase else {
                   return false
               }
               return tok.allSatisfy { c in
                   c.isLetter || c == "'" || c == "-" || c == "\u{2019}"
               }
           })
        {
            return L("setup.visit.custom.error.name")
        }
        // De-dup against existing customs + defaults.
        if existing.contains(trimmed)
            || Self.defaultVisitTypeKeys.contains(trimmed)
        {
            return L("setup.visit.custom.error.duplicate")
        }
        return nil
    }

    static let ssnRawRE = /^\d{9}$/
    static let ssnDashedRE = /^\d{3}-\d{2}-\d{4}$/

    private let languages: [(id: String, label: String, sub: String, flag: String)] = [
        ("en", "English", "United States", "🇺🇸"),
        ("fr", "Français", "France", "🇫🇷"),
    ]

    private var stepTitle: String {
        switch step {
        case 0: return L("setup.practiceTitle")
        case 1: return L("setup.specialtyTitle")
        case 2: return L("setup.visitTitle")
        case 3: return L("setup.templateTitle")
        case 4: return L("setup.languageTitle")
        case 5: return L("setup.recordingTitle")
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
                .aurionScreenEdge()
                .padding(.top, 4)
                .padding(.bottom, 20)
            }
            footer
        }
        .background(Color.aurionBackground)
        .onAppear(perform: seedFromExistingProfile)
    }

    /// Populate the multi-select sets / custom-types list from
    /// `appState.physicianProfile` so re-entering the setup flow from
    /// Profile → "Edit Practice" carries the clinician's current
    /// choices instead of resetting to defaults. Idempotent — guarded
    /// by `didSeedFromProfile`.
    @State private var didSeedFromProfile = false
    private func seedFromExistingProfile() {
        guard !didSeedFromProfile, let p = appState.physicianProfile else { return }
        didSeedFromProfile = true
        if let pt = p.practiceType, !pt.isEmpty {
            let parts = pt.split(separator: ",").map {
                $0.trimmingCharacters(in: .whitespaces)
            }
            if !parts.isEmpty {
                practiceTypes = Set(parts)
            }
        }
        primarySpecialty = p.primarySpecialty
        let allTypes = p.consultationTypes
        let defaults = Set(allTypes.filter { Self.defaultVisitTypeKeys.contains($0) })
        let customs = allTypes.filter { !Self.defaultVisitTypeKeys.contains($0) }
        if !defaults.isEmpty || !customs.isEmpty {
            consultationTypes = defaults
            customConsultationTypes = customs
        }
        preferredTemplates = Set(p.preferredTemplates)
        outputLanguage = p.outputLanguage
    }

    // MARK: - Header

    private var header: some View {
        VStack(spacing: 8) {
            HStack {
                // Marie (2026-06-06): users needed a way to revise earlier
                // choices without losing onboarding progress (Specialty
                // tapped wrong, want to change templates, etc.). Back
                // button hidden on Step 1 — no prior step to return to.
                // Tap decrements `step` with the existing setup transition
                // animation so the back/forward feel is symmetric.
                if step > 0 {
                    Button {
                        AurionHaptics.selection()
                        withAnimation(.aurionIOS) { step -= 1 }
                    } label: {
                        HStack(spacing: 4) {
                            Image(systemName: "chevron.left")
                                .font(.system(size: 12, weight: .semibold))
                            Text(L("setup.back"))
                                .aurionFont(12, relativeTo: .caption)
                        }
                        .foregroundColor(.aurionTextSecondary)
                    }
                    .accessibilityLabel(L("setup.back"))
                }
                Text(L("setup.step", step + 1, totalSteps))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionTextSecondary)
                Spacer()
                Button(L("setup.skip")) {
                    appState.hasCompletedProfileSetup = true
                }
                .aurionFont(12, relativeTo: .caption)
                .foregroundColor(.aurionTextSecondary)
            }
            AurionProgressBar(value: Double(step + 1) / Double(totalSteps))
        }
        .aurionScreenEdge()
        .padding(.top, 12)
        .padding(.bottom, AurionSpacing.md)
    }

    // MARK: - Footer (Continue)

    private var footer: some View {
        VStack(spacing: 0) {
            Rectangle().fill(Color.aurionBorder).frame(height: 1)
            AurionGoldButton(
                label: step == totalSteps - 1
                    ? (isSaving ? L("setup.saving") : L("setup.getStarted"))
                    : L("setup.continue"),
                full: true,
                disabled: isSaving
            ) {
                advance()
            }
            .aurionScreenEdge()
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
        case 5: recordingPrefsStep
        default: EmptyView()
        }
    }

    private var practiceStep: some View {
        VStack(spacing: 12) {
            ForEach(self.practiceTypes_options, id: \.id) { o in
                AurionSelectableCard(
                    icon: o.icon,
                    title: localizedPracticeType(o.id),
                    subtitle: L(o.subKey),
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
            ForEach(specialties, id: \.self) { id in
                radioRow(label: localizedSpecialty(id), selected: primarySpecialty == id) {
                    primarySpecialty = id
                }
            }
        }
    }

    private var visitTypesStep: some View {
        VStack(spacing: 8) {
            // ── Defaults ──────────────────────────────────────────────
            ForEach(visitTypes, id: \.self) { id in
                checkboxRow(label: localizedConsultationType(id), on: consultationTypes.contains(id)) {
                    if consultationTypes.contains(id) {
                        consultationTypes.remove(id)
                    } else {
                        consultationTypes.insert(id)
                    }
                }
            }

            // ── Custom types ──────────────────────────────────────────
            // Each row mirrors the checkbox visual (checked, since custom
            // types are inherently selected when present) with a trash
            // affordance for delete. Matches the inline-add pattern
            // (HIG: avoid modal sheets for short list additions).
            ForEach(customConsultationTypes, id: \.self) { name in
                customTypeRow(name)
            }

            // ── Add affordance ────────────────────────────────────────
            if isAddingCustomType {
                customTypeAddInline
            } else if customConsultationTypes.count >= Self.maxCustomTypes {
                Text(L("setup.visit.custom.limit"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(.horizontal, 16)
                    .padding(.top, 4)
            } else {
                addCustomTypeButton
            }
        }
    }

    private func customTypeRow(_ name: String) -> some View {
        HStack(spacing: 12) {
            ZStack {
                RoundedRectangle(cornerRadius: AurionRadius.xs)
                    .fill(Color.aurionGold)
                    .frame(width: 22, height: 22)
                    .overlay(
                        RoundedRectangle(cornerRadius: AurionRadius.xs)
                            .stroke(Color.aurionGold, lineWidth: 2)
                    )
                Image(systemName: "checkmark")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(.aurionTextPrimary)
            }
            Text(name)
                .aurionFont(16, relativeTo: .body)
                .foregroundColor(.aurionTextPrimary)
            Spacer(minLength: 0)
            Button {
                AurionHaptics.selection()
                customConsultationTypes.removeAll { $0 == name }
            } label: {
                Image(systemName: "trash")
                    .font(.system(size: 16, weight: .medium))
                    .foregroundColor(.aurionTextSecondary)
                    .padding(8)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(L("setup.visit.custom.delete", name))
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 14)
        .background(Color.aurionCardBackground)
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .stroke(Color.aurionGold, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
    }

    private var addCustomTypeButton: some View {
        Button {
            AurionHaptics.selection()
            customTypeDraft = ""
            customTypeDraftError = nil
            withAnimation(.aurionIOS) { isAddingCustomType = true }
        } label: {
            HStack(spacing: 10) {
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: 20))
                    .foregroundColor(.aurionGold)
                Text(L("setup.visit.custom.add"))
                    .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextPrimary)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 14)
            .background(Color.aurionCardBackground)
            .overlay(
                RoundedRectangle(cornerRadius: AurionRadius.md)
                    .stroke(Color.aurionBorder, lineWidth: 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
        }
        .buttonStyle(.plain)
    }

    private var customTypeAddInline: some View {
        VStack(alignment: .leading, spacing: 10) {
            TextField(
                L("setup.visit.custom.placeholder"),
                text: $customTypeDraft
            )
            .aurionFont(16, relativeTo: .body)
            .autocorrectionDisabled()
            .submitLabel(.done)
            .onChange(of: customTypeDraft) { _, newValue in
                customTypeDraftError = Self.validateCustomVisitType(
                    newValue,
                    existing: customConsultationTypes
                )
            }
            .onSubmit { commitCustomType() }

            if let err = customTypeDraftError, !customTypeDraft.isEmpty {
                Text(err)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionRed)
            }

            HStack(spacing: 12) {
                Spacer()
                Button(L("setup.visit.custom.cancel")) {
                    withAnimation(.aurionIOS) {
                        isAddingCustomType = false
                        customTypeDraft = ""
                        customTypeDraftError = nil
                    }
                }
                .aurionFont(15, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)

                Button(L("setup.visit.custom.commit")) {
                    commitCustomType()
                }
                .disabled(!canCommitCustomType)
                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(canCommitCustomType ? .aurionGold : .aurionTextSecondary)
            }
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(Color.aurionCardBackground)
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
    }

    private var canCommitCustomType: Bool {
        let trimmed = customTypeDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        return !trimmed.isEmpty && customTypeDraftError == nil
    }

    private func commitCustomType() {
        let trimmed = customTypeDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty,
              Self.validateCustomVisitType(trimmed, existing: customConsultationTypes) == nil
        else {
            return
        }
        withAnimation(.aurionIOS) {
            customConsultationTypes.append(trimmed)
            customTypeDraft = ""
            customTypeDraftError = nil
            isAddingCustomType = false
        }
        AurionHaptics.notification(.success)
    }

    private var templatesStep: some View {
        VStack(spacing: 8) {
            ForEach(specialties, id: \.self) { id in
                checkboxRow(label: localizedSpecialty(id), on: preferredTemplates.contains(id), fontSize: 15) {
                    if preferredTemplates.contains(id) {
                        preferredTemplates.remove(id)
                    } else {
                        preferredTemplates.insert(id)
                    }
                }
            }
        }
    }

    private var recordingPrefsStep: some View {
        VStack(spacing: 16) {
            // Auto-upload toggle — controls whether the audio + frames are
            // pushed to the backend immediately on Stop or wait for the
            // physician to confirm in PostEncounterView.
            prefsToggleRow(
                icon: "icloud.and.arrow.up",
                title: L("setup.autoUpload.title"),
                subtitle: L("setup.autoUpload.sub"),
                on: $recordingPrefs.autoUpload
            )

            // Retention window — how long Aurion holds the structured note
            // on this device before purging. Matches CLAUDE.md's audit-log
            // expectation that purge is confirmed every session.
            prefsStepperRow(
                icon: "clock.arrow.circlepath",
                title: L("setup.localRetention.title"),
                subtitle: L("setup.localRetention.sub"),
                value: $recordingPrefs.retentionDays,
                range: 1...30,
                unit: L("setup.days")
            )

            // Consent re-prompt cadence — how often the consent overlay
            // re-fires for returning patients.
            prefsPickerRow(
                icon: "checkmark.shield",
                title: L("setup.consentReprompt.title"),
                subtitle: L("setup.consentReprompt.sub"),
                selection: $recordingPrefs.consentReprompt
            )
        }
    }

    private func prefsToggleRow(icon: String, title: String, subtitle: String, on: Binding<Bool>) -> some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.system(size: 18, weight: .medium))
                .foregroundColor(.aurionGoldDark)
                .frame(width: 28)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .aurionFont(16, weight: .semibold, relativeTo: .body)
                    .foregroundColor(.aurionTextPrimary)
                // .fixedSize(vertical) lets the subtitle wrap to as many
                // lines as it needs instead of collapsing to a 1-char
                // column when the toggle's intrinsic width grows under
                // Dynamic Type. Matches the prefsStepperRow fix.
                Text(subtitle)
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 8)
            Toggle("", isOn: on)
                .labelsHidden()
                .tint(.aurionGold)
        }
        .padding(16)
        .background(Color.aurionCardBackground)
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
    }

    /// Stepper row — VStack so the control gets its own line below
    /// the title/subtitle (same shape as ``prefsPickerRow``). Earlier
    /// versions inlined the SwiftUI ``Stepper`` next to a `Spacer` in
    /// the HStack with ``.fixedSize()``; under Dynamic Type at larger
    /// sizes (`.aurionFont` is Dynamic-Type-aware) the stepper grew
    /// horizontally, squeezed the subtitle's frame to a near-zero
    /// column, and the text wrapped one character per line — Marie
    /// reported it on the Step 6/6 onboarding screen on 2026-06-05.
    /// Two-row layout makes the subtitle responsive to whatever
    /// width remains after the icon, with no horizontal competition
    /// against the stepper control.
    private func prefsStepperRow(icon: String, title: String, subtitle: String, value: Binding<Int>, range: ClosedRange<Int>, unit: String) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 14) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundColor(.aurionGoldDark)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .aurionFont(16, weight: .semibold, relativeTo: .body)
                        .foregroundColor(.aurionTextPrimary)
                    Text(subtitle)
                        .aurionFont(13, relativeTo: .footnote)
                        .foregroundColor(.aurionTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
            HStack {
                Text("\(value.wrappedValue) \(unit)")
                    .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextPrimary)
                    .monospacedDigit()
                Spacer()
                Stepper(value: value, in: range) {
                    Text("\(value.wrappedValue) \(unit)")
                        .aurionFont(15, weight: .medium, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                        .monospacedDigit()
                }
                .labelsHidden()
            }
        }
        .padding(16)
        .background(Color.aurionCardBackground)
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
    }

    private func prefsPickerRow(icon: String, title: String, subtitle: String, selection: Binding<ConsentRepromptCadence>) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 14) {
                Image(systemName: icon)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundColor(.aurionGoldDark)
                    .frame(width: 28)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .aurionFont(16, weight: .semibold, relativeTo: .body)
                        .foregroundColor(.aurionTextPrimary)
                    Text(subtitle)
                        .aurionFont(13, relativeTo: .footnote)
                        .foregroundColor(.aurionTextSecondary)
                }
                Spacer(minLength: 0)
            }
            Picker("Consent re-prompt", selection: selection) {
                ForEach(ConsentRepromptCadence.allCases) { cadence in
                    Text(cadence.label).tag(cadence)
                }
            }
            .pickerStyle(.segmented)
        }
        .padding(16)
        .background(Color.aurionCardBackground)
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
    }

    private var languageStep: some View {
        VStack(spacing: 12) {
            ForEach(languages, id: \.id) { o in
                Button {
                    AurionHaptics.selection()
                    outputLanguage = o.id
                } label: {
                    HStack(spacing: 14) {
                        Text(o.flag).aurionFont(32, relativeTo: .title)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(o.label)
                                .aurionFont(17, weight: .semibold, relativeTo: .headline)
                                .foregroundColor(.aurionTextPrimary)
                            Text(o.sub)
                                .aurionFont(13, relativeTo: .footnote)
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
                        .stroke(selected ? Color.aurionGold : Color.aurionInputBorder, lineWidth: 2)
                        .frame(width: 20, height: 20)
                    if selected {
                        Circle().fill(Color.aurionGold).frame(width: 10, height: 10)
                    }
                }
                Text(label)
                    .aurionFont(16, relativeTo: .body)
                    .foregroundColor(.aurionTextPrimary)
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
                                .stroke(on ? Color.aurionGold : Color.aurionInputBorder, lineWidth: 2)
                        )
                    if on {
                        Image(systemName: "checkmark")
                            .font(.system(size: 12, weight: .bold))
                            .foregroundColor(.aurionTextPrimary)
                    }
                }
                Text(label)
                    .font(.system(size: fontSize))
                    .foregroundColor(.aurionTextPrimary)
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
            // GH-259 — defaults (sorted for stable wire form) + customs
            // in insertion order. Backend de-dups and validates each
            // custom entry; the iOS side has already run the same
            // gates client-side so the user got immediate feedback.
            let defaultsSorted = Array(consultationTypes).sorted()
            let mergedConsultationTypes = defaultsSorted + customConsultationTypes
            let updates: [String: Any] = [
                "practice_type": practiceTypes.sorted().joined(separator: ","),
                "primary_specialty": primarySpecialty,
                "preferred_templates": Array(preferredTemplates),
                "consultation_types": mergedConsultationTypes,
                "output_language": outputLanguage,
                "auto_upload": recordingPrefs.autoUpload,
                "retention_days": recordingPrefs.retentionDays,
                "consent_reprompt": recordingPrefs.consentReprompt.rawValue,
            ]
            let profile = try await APIClient.shared.updateProfile(updates)
            // Mirror to UserDefaults so screens that haven't been refactored
            // to read from `appState.physicianProfile` still see the prefs.
            recordingPrefs.persist()
            appState.physicianProfile = profile
            appState.hasCompletedProfileSetup = true
            AurionHaptics.notification(.success)
        } catch {
            self.error = "Failed to save: \(error.localizedDescription)"
            AurionHaptics.notification(.error)
        }
    }
}

// MARK: - Recording Preferences

/// How often Aurion re-confirms patient consent on the capture screen.
/// Stored locally — purely a UX gate; the backend's consent audit event
/// fires on every session regardless.
enum ConsentRepromptCadence: String, CaseIterable, Identifiable, Codable {
    case everySession = "every_session"
    case daily
    case weekly

    var id: String { rawValue }

    var label: String {
        switch self {
        case .everySession: return L("setup.freq.everySession")
        case .daily: return L("setup.freq.daily")
        case .weekly: return L("setup.freq.weekly")
        }
    }
}

/// Per-physician recording preferences set during profile setup. Stored in
/// `UserDefaults` for now — when/if the backend grows fields for these, the
/// `persist()` site sends them up too.
struct RecordingPreferences: Codable {
    var autoUpload: Bool = true
    var retentionDays: Int = 7
    var consentReprompt: ConsentRepromptCadence = .everySession

    private static let key = "aurion.recording_preferences"

    static func load() -> RecordingPreferences {
        guard let data = UserDefaults.standard.data(forKey: key),
              let prefs = try? JSONDecoder().decode(RecordingPreferences.self, from: data) else {
            return RecordingPreferences()
        }
        return prefs
    }

    func persist() {
        guard let data = try? JSONEncoder().encode(self) else { return }
        UserDefaults.standard.set(data, forKey: Self.key)
    }
}
