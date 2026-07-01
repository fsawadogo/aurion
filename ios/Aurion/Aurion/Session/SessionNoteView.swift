import SwiftUI
import UIKit

// MARK: - NoteDocumentBody — Apple-Notes-style flowing document
//
// Renders the entire note as a single continuous document: large title,
// muted meta row, then section headings + body paragraphs with inline
// superscript footnote markers. The same View is mounted in the on-screen
// scroll view and captured into PDF via ImageRenderer — `forPDF` swaps
// screen-only chrome (status pills, the EMR-coming-soon footer) for the
// print-clean variant so screen and document layout stay in sync.

struct NoteDocumentBody: View {
    let note: NoteResponse
    let specialtyTitle: String
    let dateString: String
    /// Clinician-entered at export time — Aurion captures no structured
    /// patient demographics, so this is optional. Blank renders as a neutral
    /// "Not documented" rather than fabricating an age/sex.
    let patientAgeSex: String
    /// Human-readable encounter type (e.g. "In-person consultation"),
    /// resolved from the session's `encounter_type` by the caller.
    let encounterType: String
    let forPDF: Bool

    // On-screen reading text scales with Dynamic Type so physicians can size
    // the note to their preference. The PDF path always uses the literal point
    // sizes below, so exported documents render identically regardless of the
    // reader's text-size setting.
    @ScaledMetric(relativeTo: .largeTitle) private var titleSize: CGFloat = 32
    @ScaledMetric(relativeTo: .subheadline) private var dateSize: CGFloat = 15
    @ScaledMetric(relativeTo: .title2) private var sectionHeadingSize: CGFloat = 20
    @ScaledMetric(relativeTo: .body) private var emptySectionSize: CGFloat = 16
    @ScaledMetric(relativeTo: .body) private var claimBodySize: CGFloat = 17
    @ScaledMetric(relativeTo: .title3) private var subHeadingSize: CGFloat = 17

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            // Masthead — gold eyebrow, specialty title, meta row, gold rule.
            VStack(alignment: .leading, spacing: 6) {
                Text("AURION CLINICAL AI")
                    .font(.system(size: forPDF ? 9 : 10, weight: .bold))
                    .tracking(2)
                    .foregroundColor(.aurionGold)
                Text(specialtyTitle)
                    .font(.system(size: forPDF ? 32 : titleSize, weight: .bold))
                    .foregroundColor(forPDF ? .aurionNavy : .aurionTextPrimary)
                // Encounter metadata strip — Date · Patient Age/Sex ·
                // Encounter Type. Mirrors the reference SOAP letterhead so
                // screen, PDF, and DOCX all carry the same header band.
                //
                // Internal metadata (completeness / version / provider) stays
                // deliberately OFF the note — it lives in the audit log +
                // pilot metrics. Patient age/sex is clinician-entered at
                // export (no structured demographics are captured); blank
                // shows "Not documented" rather than an invented value.
                metadataStrip
                    .padding(.top, 4)

                Rectangle()
                    .fill(Color.aurionGold)
                    .frame(height: 2)
                    .padding(.top, 10)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            // SOAP-grouped body — Subjective / Objective / Assessment / Plan
            // bands, each with its member sections beneath. Mirrors the
            // backend DOCX export so screen, PDF, and DOCX read identically.
            ForEach(soapGroups) { group in
                VStack(alignment: .leading, spacing: 14) {
                    groupHeader(letter: group.letter, label: group.label)
                    ForEach(group.sections, id: \.id) { section in
                        sectionView(section)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            if !forPDF {
                VStack(spacing: 6) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(.system(size: 22, weight: .light))
                        .foregroundColor(.aurionTextSecondary.opacity(0.5))
                    Text(L("noteDoc.emrComingSoon"))
                        .font(.system(size: 12))
                        .foregroundColor(.aurionTextSecondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.top, 24)
                .padding(.bottom, 8)
            }
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 28)
        // ImageRenderer captures whatever's behind the view — set an
        // explicit white page background for PDF, transparent for screen
        // so the scroll view's .aurionBackground shows through.
        .background(forPDF ? Color.white : Color.clear)
    }

    // SOAP grouping — buckets the note's sections into the four SOAP
    // headers (order-preserving), routing any unknown section id by
    // keyword and dropping empty groups. Matches the backend export.
    private struct SOAPGroup: Identifiable {
        let letter: String
        let label: String
        let sections: [NoteSectionResponse]
        var id: String { letter }
    }

    // MARK: - Encounter metadata strip

    /// Very light navy tint — reads as a document letterhead band on the
    /// white PDF page and as a subtle card on the on-screen note.
    private var metaStripFill: Color {
        forPDF
            ? Color(red: 0.925, green: 0.949, blue: 0.984)
            : Color.aurionNavy.opacity(0.06)
    }

    /// Three-column band: Date · Patient Age/Sex · Encounter Type.
    private var metadataStrip: some View {
        HStack(alignment: .top, spacing: 12) {
            metaCell(label: L("noteDoc.metaDate"), value: dateString)
            metaCell(
                label: L("noteDoc.metaPatient"),
                value: patientAgeSex.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    ? L("noteDoc.metaNotDocumented")
                    : patientAgeSex
            )
            metaCell(
                label: L("noteDoc.metaEncounter"),
                value: encounterType.isEmpty ? L("noteDoc.metaNotDocumented") : encounterType
            )
        }
        .padding(.horizontal, 14)
        .padding(.vertical, forPDF ? 10 : 12)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous).fill(metaStripFill)
        )
    }

    private func metaCell(label: String, value: String) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            Text(label.uppercased())
                .font(.system(size: forPDF ? 8.5 : 9, weight: .bold))
                .tracking(0.6)
                .foregroundColor(forPDF ? Color.black.opacity(0.45) : .aurionTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
            Text(value)
                .font(.system(size: forPDF ? 12.5 : 14, weight: .semibold))
                .foregroundColor(forPDF ? .aurionNavy : .aurionTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var soapGroups: [SOAPGroup] {
        let mapping: [(String, String, [String])] = [
            ("S", "SUBJECTIVE", ["chief_complaint", "hpi", "history",
                                 "past_medical_history", "past_surgical_history",
                                 "medications", "allergies"]),
            ("O", "OBJECTIVE", ["vital_signs", "physical_exam", "wound_assessment",
                                "functional_assessment", "imaging_review", "investigations"]),
            ("A", "ASSESSMENT", ["assessment"]),
            ("P", "PLAN", ["plan", "disposition"]),
        ]
        let byId = Dictionary(note.sections.map { ($0.id, $0) }, uniquingKeysWith: { first, _ in first })
        var used = Set<String>()
        var buckets: [[NoteSectionResponse]] = mapping.map { _ in [] }
        for (i, entry) in mapping.enumerated() {
            for sid in entry.2 {
                if let s = byId[sid] {
                    buckets[i].append(s)
                    used.insert(sid)
                }
            }
        }
        for s in note.sections where !used.contains(s.id) {
            let sid = s.id.lowercased()
            let idx: Int
            if sid.contains("assess") || sid.contains("impression") { idx = 2 }
            else if sid.contains("plan") || sid.contains("dispo") || sid.contains("follow") { idx = 3 }
            else if sid.contains("exam") || sid.contains("imag") || sid.contains("vital")
                        || sid.contains("investig") || sid.contains("objective") { idx = 1 }
            else { idx = 0 }
            buckets[idx].append(s)
        }
        var result: [SOAPGroup] = []
        for (i, entry) in mapping.enumerated() where !buckets[i].isEmpty {
            result.append(SOAPGroup(letter: entry.0, label: entry.1, sections: buckets[i]))
        }
        return result
    }

    @ViewBuilder
    private func groupHeader(letter: String, label: String) -> some View {
        HStack(spacing: 10) {
            Text(letter)
                .font(.system(size: forPDF ? 14 : 16, weight: .heavy))
                .foregroundColor(.white)
                .frame(width: forPDF ? 26 : 30, height: forPDF ? 26 : 30)
                .background(Color.aurionGold)
                .clipShape(RoundedRectangle(cornerRadius: 7, style: .continuous))
            Text(label)
                .font(.system(size: forPDF ? 18 : 21, weight: .bold))
                .foregroundColor(forPDF ? .aurionNavy : .aurionTextPrimary)
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder
    private func sectionView(_ section: NoteSectionResponse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            VStack(alignment: .leading, spacing: 3) {
                HStack(alignment: .firstTextBaseline, spacing: 8) {
                    Text(section.title)
                        .font(.system(size: forPDF ? 15 : subHeadingSize, weight: .semibold))
                        .foregroundColor(forPDF ? .aurionNavy : .aurionTextPrimary)
                    if !forPDF, section.status != "populated" {
                        Text(statusLabel(section.status))
                            .font(.system(size: 11, weight: .semibold))
                            .foregroundColor(.aurionTextSecondary)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(Color.aurionSurfaceAlt)
                            .clipShape(Capsule())
                    }
                }
                Rectangle()
                    .fill(Color.aurionGold.opacity(0.45))
                    .frame(height: 1)
            }

            if section.claims.isEmpty {
                Text(section.status == "pending_video"
                     ? L("noteDoc.awaitingVisual")
                     : L("noteDoc.noContent"))
                    .font(.system(size: forPDF ? 16 : emptySectionSize))
                    .foregroundColor(forPDF ? Color.black.opacity(0.55) : .aurionTextSecondary)
                    .italic()
            } else {
                claimsParagraph(section.claims)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    /// Single AttributedString of all claims as flowing prose with `¹ ² ³…`
    /// superscript markers. Apple-Notes style — no bullets, no chevrons,
    /// just typography.
    private func claimsParagraph(_ claims: [NoteClaimResponse]) -> some View {
        var attr = AttributedString()
        for (i, claim) in claims.enumerated() {
            var sentence = AttributedString(claim.text)
            sentence.font = .system(size: forPDF ? 17 : claimBodySize)
            sentence.foregroundColor = forPDF ? .black : .aurionTextPrimary
            attr.append(sentence)

            var marker = AttributedString(superscript(i + 1))
            marker.font = .system(size: 11, weight: .semibold)
            marker.foregroundColor = .aurionGold
            attr.append(marker)

            if i < claims.count - 1 {
                attr.append(AttributedString(" "))
            }
        }
        return Text(attr)
            .lineSpacing(4)
            .fixedSize(horizontal: false, vertical: true)
    }

    private func superscript(_ n: Int) -> String {
        let map: [Character: Character] = [
            "0": "⁰", "1": "¹", "2": "²", "3": "³", "4": "⁴",
            "5": "⁵", "6": "⁶", "7": "⁷", "8": "⁸", "9": "⁹",
        ]
        return String(String(n).compactMap { map[$0] })
    }

    private func statusLabel(_ status: String) -> String {
        switch status {
        case "pending_video": return L("noteDoc.status.pending")
        case "not_captured": return L("noteDoc.status.empty")
        case "processing_failed": return L("noteDoc.status.failed")
        default: return status.capitalized
        }
    }
}

/// Read-only note view for a completed session.
/// Displays formatted SOAP note with copy-to-clipboard and export.
struct SessionNoteView: View {
    let session: SessionResponse
    @State private var note: NoteResponse?
    @State private var isLoading = true
    @State private var showCopiedToast = false
    /// Cancellable auto-dismiss for the "Copied" toast. Replacing it on
    /// each copy prevents an earlier 2s timer from dismissing a toast the
    /// physician just re-triggered.
    @State private var toastDismissTask: Task<Void, Never>?
    @State private var error: String?
    // Live AppConfig snapshot — gates the four post-pilot cards below.
    // When a card's flag is `false` we don't render it AT ALL: no
    // placeholder, no spacer, no Retry button. Crucially the card's
    // own `.onAppear` fetch is also never triggered because the view
    // itself never enters the hierarchy. Defaults match the backend
    // schema (all four `false`) so the pre-fetch state is also safe.
    @EnvironmentObject private var remoteConfig: RemoteConfig
    // Share / export state. The format picker is a confirmation dialog
    // (HIG: "Action sheets present 2-4 short, related options"). The
    // bytes are rendered locally — see `Export/NotePDFRenderer.swift`
    // and `Export/NoteDocumentBuilder.swift` — and surfaced via the
    // system share sheet so the physician can save to Files, mail it,
    // or send via Messages without leaving the note.
    @State private var showExportPicker = false
    @State private var exportFileURL: URL?
    @State private var showShareSheet = false
    @State private var isPreparingExport = false
    /// Export-failure surface. Distinct from `error` (which only renders
    /// inside the note==nil EmptyStateView): an export fails while the
    /// note is loaded, so it needs its own alert that sits OVER the
    /// document rather than a subtitle that never shows.
    @State private var exportError: String?
    /// Clinician-entered patient age/sex for the document header. Aurion
    /// captures no structured demographics, so this is typed at export time
    /// (the age/sex prompt below) and remembered for the session. Blank
    /// renders as "Not documented" — never fabricated.
    @State private var patientAgeSex: String = ""
    /// The format the physician picked, held while the age/sex prompt is up
    /// so tapping "Export" resumes with the right renderer.
    @State private var pendingExportFormat: SharedExportFormat?
    /// Drives the age/sex capture alert shown between format pick and render.
    @State private var showAgeSexPrompt = false
    // ── Note "Options" (post-generation actions) — gated on
    // `note_options_enabled`. Phase 1: change template / output language and
    // regenerate from the stored transcript (no re-record).
    @State private var showTemplatePicker = false
    @State private var showLanguagePicker = false
    /// Phase 2: edit/add the encounter context (e.g. a breast-aug visit that
    /// also covered liposuction), then regenerate focused on it.
    @State private var showContextEditor = false
    @State private var contextDraft = ""
    @State private var isRegenerating = false
    @State private var regenerateError: String?
    /// Brief success toast after a regenerate lands the new note version.
    @State private var regenToast: String?
    /// Clamps the note's reading column to a comfortable measure on
    /// iPad. Without this the SOAP section paragraphs run edge-to-edge
    /// at ~1000pt — too wide for sustained reading per HIG.
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

    var body: some View {
        ZStack {
            if isLoading {
                skeletonDocument
            } else if let note {
                noteContent(note)
            } else {
                // Load failed (or returned nothing). EmptyStateView is
                // presentation-only, so the Retry affordance is appended
                // below it — mirrors PriorEncountersRail's retry block so
                // a transient note-fetch failure self-heals on tap.
                VStack(spacing: AurionSpacing.lg) {
                    EmptyStateView(
                        icon: "doc.questionmark",
                        title: L("sessionNote.noNote"),
                        subtitle: error ?? L("sessionNote.noNoteSub")
                    )
                    Button {
                        Task { await loadNote() }
                    } label: {
                        HStack(spacing: 6) {
                            Image(systemName: "arrow.clockwise")
                                .font(.system(size: 12, weight: .semibold))
                            Text(L("common.retry"))
                                .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                        }
                        .foregroundColor(.aurionTextPrimary)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 8)
                        .background(Color.aurionSurfaceAlt)
                        .clipShape(Capsule())
                    }
                    .disabled(isLoading)
                }
            }

            // Copied toast
            if showCopiedToast {
                VStack {
                    Spacer()
                    HStack(spacing: AurionSpacing.sm) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.clinicalNormal)
                            // Bounce on appear so the toast reads as a
                            // confirmation event, not just an overlay.
                            .symbolEffect(.bounce, value: showCopiedToast)
                        Text(L("sessionNote.copied"))
                            .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                    }
                    .foregroundColor(.aurionTextPrimary)
                    .padding(.horizontal, AurionSpacing.xl)
                    .padding(.vertical, AurionSpacing.sm)
                    // `.regularMaterial` is iOS's native confirmation-
                    // chip backdrop (Control Center, Now Playing). Reads
                    // as "from the system" rather than "from this app".
                    .background(.regularMaterial, in: Capsule())
                    .shadow(color: .black.opacity(0.18), radius: 14, y: 6)
                    .padding(.bottom, AurionSpacing.xxl)
                    .transition(AurionTransition.fadeUp)
                }
                .animation(AurionAnimation.spring, value: showCopiedToast)
            }

            // Regenerate success toast (mirrors the copied toast).
            if let regenToast {
                VStack {
                    Spacer()
                    HStack(spacing: AurionSpacing.sm) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.clinicalNormal)
                        Text(regenToast)
                            .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                    }
                    .foregroundColor(.aurionTextPrimary)
                    .padding(.horizontal, AurionSpacing.xl)
                    .padding(.vertical, AurionSpacing.sm)
                    .background(.regularMaterial, in: Capsule())
                    .shadow(color: .black.opacity(0.18), radius: 14, y: 6)
                    .padding(.bottom, AurionSpacing.xxl)
                    .transition(AurionTransition.fadeUp)
                }
                .animation(AurionAnimation.spring, value: regenToast)
            }

            // Regenerating veil — the note-gen re-run takes a few seconds.
            // Block interaction + show a spinner so a second tap can't queue a
            // duplicate regenerate.
            if isRegenerating {
                Color.black.opacity(0.06).ignoresSafeArea()
                VStack(spacing: AurionSpacing.md) {
                    ProgressView()
                    Text(L("noteOptions.regenerating"))
                        .aurionFont(14, weight: .medium, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextSecondary)
                }
                .padding(AurionSpacing.xl)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: AurionRadius.md))
                .shadow(color: .black.opacity(0.15), radius: 16, y: 8)
                .transition(.opacity)
            }
        }
        .navigationTitle(displaySpecialty)
        .aurionNavBar()
        // Donate a Spotlight-eligible activity so the physician can later
        // find this note via system search. We intentionally index only
        // specialty + relative date — never PHI. The session UUID is the
        // persistentIdentifier; AurionApp.onContinueUserActivity matches
        // on it and routes the user back here.
        .userActivity(AppNavigation.sessionActivityType, isActive: !isLoading) { activity in
            activity.title = "Aurion · \(displaySpecialty)"
            activity.userInfo = ["session_id": session.id]
            activity.persistentIdentifier = session.id
            activity.isEligibleForSearch = true
            activity.isEligibleForPrediction = false
            // Strictly device-local — disable Handoff so this never
            // surfaces on another device or syncs through iCloud.
            activity.isEligibleForHandoff = false
        }
        .toolbar {
            ToolbarItemGroup(placement: .navigationBarTrailing) {
                Button {
                    if let note { copyToClipboard(note) }
                } label: {
                    Image(systemName: "doc.on.doc")
                }
                .disabled(note == nil)
                .accessibilityLabel(L("sessionNote.a11yCopy"))
                .accessibilityHint(L("sessionNote.a11yCopyHint"))

                Button {
                    showExportPicker = true
                } label: {
                    if isPreparingExport {
                        ProgressView()
                    } else {
                        Image(systemName: "square.and.arrow.up")
                    }
                }
                .disabled(note == nil || isPreparingExport)
                .accessibilityLabel(L("sessionNote.a11yExport"))
                .accessibilityHint(L("sessionNote.a11yExportHint"))

                // Options menu — post-generation actions. Gated on the
                // note_options_enabled flag; ships hidden until an ADMIN flips
                // it. Phase 1: change template / output language + regenerate.
                if remoteConfig.featureFlags.noteOptionsEnabled {
                    Menu {
                        Button {
                            showTemplatePicker = true
                        } label: {
                            Label(L("noteOptions.changeTemplate"), systemImage: "doc.text.magnifyingglass")
                        }
                        Button {
                            showLanguagePicker = true
                        } label: {
                            Label(L("noteOptions.changeLanguage"), systemImage: "globe")
                        }
                        Button {
                            contextDraft = ""
                            showContextEditor = true
                        } label: {
                            Label(L("noteOptions.changeContext"), systemImage: "text.bubble")
                        }
                    } label: {
                        if isRegenerating {
                            ProgressView()
                        } else {
                            Image(systemName: "ellipsis.circle")
                        }
                    }
                    .disabled(note == nil || isRegenerating)
                    .accessibilityLabel(L("noteOptions.menu"))
                }
            }
        }
        .task { await loadNote() }
        // Confirmation dialog presents the two formats; the system
        // adds a localized Cancel via `.cancel` role automatically.
        .confirmationDialog(
            L("sessionNote.exportFormatTitle"),
            isPresented: $showExportPicker,
            titleVisibility: .visible
        ) {
            Button(L("sessionNote.exportPDF")) { promptAgeSexThenExport(.pdf) }
            Button(L("sessionNote.exportDOCX")) { promptAgeSexThenExport(.docx) }
        }
        // Optional patient age/sex capture — appears in the document header
        // strip. Aurion holds no structured demographics, so the physician
        // types it here; leaving it blank shows "Not documented". iOS 16's
        // `.alert` supports an inline TextField.
        .alert(
            L("sessionNote.ageSexTitle"),
            isPresented: $showAgeSexPrompt
        ) {
            TextField(L("sessionNote.ageSexPlaceholder"), text: $patientAgeSex)
                .textInputAutocapitalization(.none)
            Button(L("sessionNote.ageSexExport")) {
                if let format = pendingExportFormat { exportNote(as: format) }
                pendingExportFormat = nil
            }
            Button(L("common.cancel"), role: .cancel) { pendingExportFormat = nil }
        } message: {
            Text(L("sessionNote.ageSexMessage"))
        }
        .sheet(isPresented: $showShareSheet) {
            if let url = exportFileURL {
                ShareSheet(items: [url])
            }
        }
        // Change-template picker — the 8 built-in note templates. Selecting one
        // regenerates the note from the STORED transcript (no re-record).
        .confirmationDialog(
            L("noteOptions.templateTitle"),
            isPresented: $showTemplatePicker,
            titleVisibility: .visible
        ) {
            ForEach(BuiltInTemplate.keys, id: \.self) { key in
                Button(localizedTemplate(key)) {
                    Task { await regenerate(templateKey: key) }
                }
            }
        }
        // Change-output-language picker — regenerates the note in the chosen
        // language (EN/FR at pilot parity).
        .confirmationDialog(
            L("noteOptions.languageTitle"),
            isPresented: $showLanguagePicker,
            titleVisibility: .visible
        ) {
            Button(L("noteOptions.langEnglish")) {
                Task { await regenerate(outputLanguage: "en") }
            }
            Button(L("noteOptions.langFrench")) {
                Task { await regenerate(outputLanguage: "fr") }
            }
        }
        // Change/add encounter context — a short free-text sheet. On
        // Regenerate the note is re-run focused on the new context (the
        // breast-aug → also-lipo case). Descriptive mode is preserved
        // server-side (the context is framing, never a fabricated finding).
        .sheet(isPresented: $showContextEditor) {
            NoteContextEditorSheet(
                text: $contextDraft,
                onRegenerate: {
                    let value = contextDraft
                    showContextEditor = false
                    Task { await regenerate(encounterContext: value) }
                },
                onCancel: { showContextEditor = false }
            )
        }
        // Regenerate-failure alert.
        .alert(
            L("noteOptions.failedShort"),
            isPresented: Binding(
                get: { regenerateError != nil },
                set: { if !$0 { regenerateError = nil } }
            ),
            presenting: regenerateError
        ) { _ in
            Button(L("common.ok"), role: .cancel) { regenerateError = nil }
        } message: { detail in
            Text(detail)
        }
        // Export-failure alert. Sits over the loaded note (the `error`
        // EmptyStateView only renders when note==nil, so an export that
        // fails on a loaded note would otherwise be silent).
        .alert(
            L("export.failedShort"),
            isPresented: Binding(
                get: { exportError != nil },
                set: { if !$0 { exportError = nil } }
            ),
            presenting: exportError
        ) { _ in
            Button(L("common.ok"), role: .cancel) { exportError = nil }
        } message: { detail in
            Text(detail)
        }
    }

    // MARK: - Loading skeleton (document-shaped)

    /// Shimmer placeholder shaped like the note — title, meta, then a few
    /// sections of heading + body lines — so the document reads as forming.
    private var skeletonDocument: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                AurionSkeleton().frame(width: 230, height: 30)   // title
                AurionSkeleton().frame(width: 150, height: 14)   // meta
                ForEach(0..<3, id: \.self) { _ in
                    VStack(alignment: .leading, spacing: 10) {
                        AurionSkeleton().frame(width: 140, height: 16)  // section heading
                        AurionSkeleton().frame(maxWidth: .infinity).frame(height: 12)
                        AurionSkeleton().frame(maxWidth: .infinity).frame(height: 12)
                        AurionSkeleton().frame(width: 210, height: 12)
                    }
                    .padding(.top, 6)
                }
            }
            .padding(AurionSpacing.xl)
            .frame(maxWidth: horizontalSizeClass == .regular ? 700 : .infinity, alignment: .leading)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .disabled(true)
    }

    // MARK: - Note Content (Apple-Notes-style flowing document)

    private func noteContent(_ note: NoteResponse) -> some View {
        ScrollView {
            VStack(spacing: 16) {
                NoteDocumentBody(
                    note: note,
                    specialtyTitle: displaySpecialty,
                    dateString: displayDate,
                    patientAgeSex: patientAgeSex,
                    encounterType: displayEncounterType,
                    forPDF: false
                )

                // Orders card (#58). Approval-gated; the extractor
                // runs against the approved Stage 1 note. Drafts at
                // the top with per-row Confirm + Cancel. Prescription
                // rows with unrecognized drug names surface the drug-
                // catalog warning inline + at the top of the card.
                //
                // Gated on `orders_card_enabled` (lane-full/card-
                // visibility-flags). Hidden by default until an ADMIN
                // flips the AppConfig flag via the web portal — when
                // hidden the card's own .onAppear fetch never fires.
                if remoteConfig.featureFlags.ordersCardEnabled {
                    OrdersCard(
                        sessionId: session.id,
                        sessionState: session.state
                    )
                    .padding(.horizontal, 24)
                }

                // Coding & billing suggestions card (#69). Strategic
                // SEPARATE inference surface — visually distinct from
                // the gold-accented clinical cards above. Always
                // shows an "Assistive — physician must confirm"
                // disclaimer. Suggestions NEVER flow back into the
                // clinical note's sections.
                //
                // Gated on `coding_card_enabled` (lane-full/card-
                // visibility-flags). See OrdersCard above for the
                // hidden-fetch-suppression contract.
                if remoteConfig.featureFlags.codingCardEnabled {
                    CodingSuggestionsCard(
                        sessionId: session.id,
                        sessionState: session.state
                    )
                    .padding(.horizontal, 24)
                }

                // Patient summary card (#59). Approval-gated
                // internally — renders a locked notice for unsigned
                // notes so the physician knows what unlocks it. Lives
                // INSIDE the iPad reading clamp so it never visually
                // outruns the note above it.
                //
                // Gated on `patient_summary_card_enabled` (lane-full/
                // card-visibility-flags).
                if remoteConfig.featureFlags.patientSummaryCardEnabled {
                    PatientSummaryCard(
                        sessionId: session.id,
                        sessionState: session.state
                    )
                    .padding(.horizontal, 24)
                }

                // EMR write-back card (#57) — outbound terminal step.
                // Approval-gated; surfaces a "Pilot mode" banner when
                // only the stub connector is registered so the
                // physician doesn't think the note actually went to
                // a chart system. Per-row scheduled-retry / terminal-
                // failure indicators mirror the portal.
                //
                // Gated on `emr_writeback_card_enabled` (lane-full/
                // card-visibility-flags). The `.padding(.bottom, 28)`
                // attaches to this card so when it's the last visible
                // card it preserves the scroll-view tail spacing;
                // when ALL four are hidden the layout collapses to
                // just the document body + the EMR-coming-soon footer
                // that already sits on NoteDocumentBody.
                if remoteConfig.featureFlags.emrWritebackCardEnabled {
                    EmrWriteBackCard(
                        sessionId: session.id,
                        sessionState: session.state
                    )
                    .padding(.horizontal, 24)
                    .padding(.bottom, 28)
                }
            }
            // iPad reading-measure clamp — applied to the inner
            // VStack so both the document body and the summary card
            // share the same column width.
            .frame(maxWidth: horizontalSizeClass == .regular ? 720 : .infinity)
            .frame(maxWidth: .infinity, alignment: .center)
        }
        .background(Color.aurionBackground)
    }

    // MARK: - Helpers

    private var displaySpecialty: String {
        localizedSpecialty(session.specialty)
    }

    private var displayDate: String {
        // Shared fractional-tolerant parser (Theme.parseISODate); a bare
        // ISO8601DateFormatter would reject the backend's fractional-seconds
        // timestamps and fall back to the raw ISO string (#279).
        if let date = parseISODate(session.createdAt) {
            let display = DateFormatter()
            display.dateStyle = .medium
            display.timeStyle = .short
            return display.string(from: date)
        }
        return session.createdAt
    }

    /// Human-readable encounter type for the document header, resolved from
    /// the session's `encounter_type` code. Unknown codes titlecase cleanly
    /// (e.g. "follow_up" → "Follow Up") so new values never render raw.
    private var displayEncounterType: String {
        switch session.encounterType {
        case "doctor_patient": return L("noteDoc.encounterInPerson")
        case "dictation":      return L("noteDoc.encounterDictation")
        default:
            return session.encounterType
                .replacingOccurrences(of: "_", with: " ")
                .capitalized
        }
    }

    /// Hold the chosen format and surface the age/sex prompt; the alert's
    /// Export button resumes `exportNote(as:)`. The field is pre-filled with
    /// whatever was typed earlier this session so re-exports don't re-ask
    /// from scratch.
    private func promptAgeSexThenExport(_ format: SharedExportFormat) {
        pendingExportFormat = format
        showAgeSexPrompt = true
    }

    private func sectionStatusBadge(_ status: String) -> some View {
        Group {
            switch status {
            case "populated":
                StatusBadge(text: "Complete", color: .clinicalNormal)
            case "pending_video":
                StatusBadge(text: "Pending", color: .clinicalInfo)
            case "not_captured":
                StatusBadge(text: "Empty", color: .secondary)
            case "processing_failed":
                StatusBadge(text: "Failed", color: .clinicalAlert)
            default:
                StatusBadge(text: status.capitalized, color: .secondary)
            }
        }
    }

    // MARK: - Actions

    /// Regenerate the note from the STORED transcript with a different template
    /// and/or output language (note-Options phase 1). Owner-scoped + auto-
    /// versioned server-side; on success we reload the freshly-created version.
    /// The expensive transcription/vision work is NOT repeated — this is a
    /// note-gen re-run over stored data, so it takes a few seconds.
    private func regenerate(
        templateKey: String? = nil,
        outputLanguage: String? = nil,
        encounterContext: String? = nil
    ) async {
        guard let note else { return }
        isRegenerating = true
        regenerateError = nil
        do {
            _ = try await APIClient.shared.regenerateNote(
                sessionId: note.sessionId,
                templateKey: templateKey,
                outputLanguage: outputLanguage,
                encounterContext: encounterContext
            )
            // Pull the new version so the screen reflects the regenerated note.
            await loadNote()
            AurionHaptics.notification(.success)
            withAnimation { regenToast = L("noteOptions.regenerated") }
            toastDismissTask?.cancel()
            toastDismissTask = Task {
                try? await Task.sleep(nanoseconds: 2_000_000_000)
                guard !Task.isCancelled else { return }
                withAnimation { regenToast = nil }
            }
        } catch {
            regenerateError = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        isRegenerating = false
    }

    private func loadNote() async {
        isLoading = true
        do {
            note = try await APIClient.shared.getFullNote(sessionId: session.id)
        } catch {
            // The previous catch block here returned a hardcoded knee-pain
            // SOAP note as a "Simulator fallback" — but it wasn't gated by
            // #if DEBUG / targetEnvironment(simulator), so it shipped to
            // TestFlight and made every failed note fetch look like a
            // populated v3 anthropic note. The 92% completeness, "twisting
            // injury during soccer", "medial meniscus tear" content you may
            // have seen on real sessions all came from this fallback.
            //
            // Keeping the fallback for Simulator-only so the demo flow
            // (no microphone) still produces a populated screen.
            #if targetEnvironment(simulator)
            note = sampleSimulatorNote(sessionId: session.id, specialty: session.specialty)
            #else
            note = nil
            self.error = (error as? APIError)?.errorDescription ?? error.localizedDescription
            #endif
        }
        isLoading = false
    }

    #if targetEnvironment(simulator)
    private func sampleSimulatorNote(sessionId: String, specialty: String) -> NoteResponse {
        NoteResponse(
            sessionId: sessionId,
            stage: 2,
            version: 3,
            providerUsed: "anthropic",
            specialty: specialty,
            completenessScore: 0.92,
            sections: [
                NoteSectionResponse(id: "chief_complaint", title: "Chief Complaint", status: "populated", claims: [
                    NoteClaimResponse(id: "c1", text: "Physician noted patient presents with right knee pain for the past three weeks, worsening with activity.", sourceType: "transcript", sourceId: "seg_001", sourceQuote: "right knee pain for the past three weeks")
                ]),
                NoteSectionResponse(id: "hpi", title: "History of Present Illness", status: "populated", claims: [
                    NoteClaimResponse(id: "c2", text: "Physician noted pain began after a twisting injury during soccer. Aggravated by stairs and prolonged sitting, rated 6/10.", sourceType: "transcript", sourceId: "seg_002", sourceQuote: "twisting injury during a recreational soccer game")
                ]),
                NoteSectionResponse(id: "physical_exam", title: "Physical Examination", status: "populated", claims: [
                    NoteClaimResponse(id: "c3", text: "Physician noted tenderness on palpation at the medial joint line of the right knee.", sourceType: "transcript", sourceId: "seg_003", sourceQuote: "tenderness on palpation at the medial joint line"),
                    NoteClaimResponse(id: "c4", text: "Physician noted range of motion restricted -- flexion limited to approximately 110 degrees.", sourceType: "transcript", sourceId: "seg_004", sourceQuote: "flexion limited to approximately 110 degrees"),
                    NoteClaimResponse(id: "c5", text: "McMurray test positive with palpable click on the medial side.", sourceType: "transcript", sourceId: "seg_005", sourceQuote: "McMurray test is positive")
                ]),
                NoteSectionResponse(id: "imaging_review", title: "Imaging Review", status: "populated", claims: [
                    NoteClaimResponse(id: "c6", text: "Physician noted MRI shows horizontal tear of the medial meniscus posterior horn. No fracture or loose bodies.", sourceType: "transcript", sourceId: "seg_006", sourceQuote: "horizontal tear of the medial meniscus")
                ]),
                NoteSectionResponse(id: "assessment", title: "Assessment", status: "populated", claims: [
                    NoteClaimResponse(id: "c7", text: "Physician stated assessment is medial meniscus tear, right knee.", sourceType: "transcript", sourceId: "seg_007", sourceQuote: "medial meniscus tear, right knee")
                ]),
                NoteSectionResponse(id: "plan", title: "Plan", status: "populated", claims: [
                    NoteClaimResponse(id: "c8", text: "Physician noted plan is referral for arthroscopic partial meniscectomy and initiation of physiotherapy.", sourceType: "transcript", sourceId: "seg_008", sourceQuote: "refer for arthroscopic partial meniscectomy")
                ]),
            ]
        )
    }
    #endif

    private func copyToClipboard(_ note: NoteResponse) {
        let dateStr = displayDate
        let specialtyStr = displaySpecialty

        var text = ""
        text += "\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\n"
        text += "AURION CLINICAL NOTE\n"
        text += "\(specialtyStr) | \(dateStr)\n"
        text += "\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\u{2550}\n\n"

        for section in note.sections where !section.claims.isEmpty {
            text += "\(section.title.uppercased())\n"
            text += "\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\u{2500}\n"
            for claim in section.claims {
                text += "\(claim.text)\n"
            }
            text += "\n"
        }

        UIPasteboard.general.string = text.trimmingCharacters(in: .whitespacesAndNewlines)
        AurionHaptics.notification(.success)

        withAnimation { showCopiedToast = true }
        // Cancel any in-flight dismiss so a rapid second copy doesn't get
        // hidden early by the previous timer, then schedule a fresh one.
        toastDismissTask?.cancel()
        toastDismissTask = Task {
            try? await Task.sleep(nanoseconds: 2_000_000_000)
            guard !Task.isCancelled else { return }
            withAnimation { showCopiedToast = false }
        }
    }

    /// Format options on the toolbar share button. Mirrors the
    /// subset of `ExportView.ExportFormat` that makes sense as a
    /// quick "save a copy" affordance on the note review screen —
    /// plain text isn't presented here because no clinician asks
    /// for a .txt of a SOAP note from this surface.
    private enum SharedExportFormat {
        case pdf, docx

        var fileExtension: String {
            switch self {
            case .pdf:  return "pdf"
            case .docx: return "docx"
            }
        }

        /// Server-side `format` value for the audit POST. Matches the
        /// strings ExportView sends so the dashboard's by-format
        /// rollup stays single-source.
        var auditFormatName: String {
            switch self {
            case .pdf:  return "pdf"
            case .docx: return "docx"
            }
        }
    }

    /// Render the note locally, stage it as a temp file, audit, then
    /// present the system share sheet. The renderers
    /// (`NotePDFRenderer` + `NoteDocumentBuilder`) are on-device and
    /// synchronous — the bytes never leave the simulator/device
    /// before the share sheet asks where to send them.
    ///
    /// Audit is best-effort: a backend hiccup must not stop the user
    /// from saving a copy locally. Errors at the audit boundary are
    /// logged and the share sheet still presents.
    private func exportNote(as format: SharedExportFormat) {
        guard let note else { return }
        isPreparingExport = true
        Task {
            do {
                let data: Data
                switch format {
                case .pdf:
                    data = try await MainActor.run {
                        try NotePDFRenderer.render(
                            note: note,
                            specialtyTitle: displaySpecialty,
                            dateString: displayDate,
                            patientAgeSex: patientAgeSex,
                            encounterType: displayEncounterType
                        )
                    }
                case .docx:
                    data = try NoteDocumentBuilder.makeDocx(
                        note, sessionId: note.sessionId,
                        dateString: displayDate,
                        patientAgeSex: patientAgeSex,
                        encounterType: displayEncounterType
                    )
                }

                let url = try writeToTempFile(
                    data: data, sessionId: note.sessionId, ext: format.fileExtension
                )

                // Best-effort audit so the export shows up in the
                // compliance officer's dashboard (parity with the
                // ExportView path). A 4xx/5xx here should not block
                // the share sheet — saving a local copy isn't a
                // state-altering action.
                _ = try? await APIClient.shared.recordExportAudit(
                    sessionId: note.sessionId,
                    format: format.auditFormatName,
                    bytesProduced: data.count
                )

                await MainActor.run {
                    self.exportFileURL = url
                    self.showShareSheet = true
                    self.isPreparingExport = false
                }
                AurionHaptics.notification(.success)
            } catch {
                await MainActor.run {
                    // Surface via the dedicated export alert (NOT `self.error`,
                    // which only paints the note==nil empty state) so the
                    // failure is visible while the note stays on screen.
                    self.exportError = L("sessionNote.exportFailedMessage")
                    self.isPreparingExport = false
                    AurionHaptics.notification(.error)
                }
            }
        }
    }

    /// Stage the rendered bytes under the system temp dir with the
    /// right filename + extension so the share sheet labels it
    /// clearly (Files / Mail / Messages all show the extension).
    private func writeToTempFile(
        data: Data, sessionId: String, ext: String
    ) throws -> URL {
        let dir = FileManager.default.temporaryDirectory
        let filename = "aurion_note_\(sessionId).\(ext)"
        let url = dir.appendingPathComponent(filename)
        try data.write(to: url, options: [.atomic])
        return url
    }
}

// MARK: - Change-context editor sheet (note-options phase 2)

/// Short free-text editor for the encounter context. Tapping Regenerate re-runs
/// the note focused on the entered context (e.g. "Breast augmentation consult;
/// also discussed liposuction"). Framing only — the backend never mints a claim
/// from it, so descriptive mode is preserved.
private struct NoteContextEditorSheet: View {
    @Binding var text: String
    let onRegenerate: () -> Void
    let onCancel: () -> Void

    var body: some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: AurionSpacing.md) {
                Text(L("noteOptions.contextHint"))
                    .aurionFont(14, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)

                ZStack(alignment: .topLeading) {
                    if text.isEmpty {
                        Text(L("noteOptions.contextPlaceholder"))
                            .aurionFont(16, relativeTo: .body)
                            .foregroundColor(.aurionTextSecondary.opacity(0.6))
                            .padding(.horizontal, 6)
                            .padding(.vertical, 10)
                            .allowsHitTesting(false)
                    }
                    TextEditor(text: $text)
                        .aurionFont(16, relativeTo: .body)
                        .frame(minHeight: 140)
                        .scrollContentBackground(.hidden)
                }
                .padding(8)
                .background(Color.aurionFieldBackground)
                .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))

                Spacer()
            }
            .padding(AurionSpacing.xl)
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
            .background(Color.aurionBackground.ignoresSafeArea())
            .navigationTitle(L("noteOptions.changeContext"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("common.cancel"), action: onCancel)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L("noteOptions.regenerateAction"), action: onRegenerate)
                        .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }
}
