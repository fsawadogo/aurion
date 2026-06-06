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
    let forPDF: Bool

    // On-screen reading text scales with Dynamic Type so physicians can size
    // the note to their preference. The PDF path always uses the literal point
    // sizes below, so exported documents render identically regardless of the
    // reader's text-size setting.
    @ScaledMetric(relativeTo: .largeTitle) private var titleSize: CGFloat = 32
    @ScaledMetric(relativeTo: .subheadline) private var dateSize: CGFloat = 15
    @ScaledMetric(relativeTo: .caption) private var metaSize: CGFloat = 12
    @ScaledMetric(relativeTo: .title2) private var sectionHeadingSize: CGFloat = 20
    @ScaledMetric(relativeTo: .body) private var emptySectionSize: CGFloat = 16
    @ScaledMetric(relativeTo: .body) private var claimBodySize: CGFloat = 17

    var body: some View {
        VStack(alignment: .leading, spacing: 28) {
            // Title block — specialty (Notes-size title), then meta row.
            VStack(alignment: .leading, spacing: 6) {
                Text(specialtyTitle)
                    .font(.system(size: forPDF ? 32 : titleSize, weight: .bold))
                    .foregroundColor(forPDF ? .black : .aurionTextPrimary)
                Text(dateString)
                    .font(.system(size: forPDF ? 15 : dateSize))
                    .foregroundColor(forPDF ? Color.black.opacity(0.55) : .aurionTextSecondary)
                HStack(spacing: 12) {
                    Text(L("noteDoc.percentComplete", Int(note.completenessScore * 100)))
                    Text("·").foregroundColor((forPDF ? Color.black : .aurionTextSecondary).opacity(0.4))
                    Text("v\(note.version)")
                    Text("·").foregroundColor((forPDF ? Color.black : .aurionTextSecondary).opacity(0.4))
                    Text(note.providerUsed)
                }
                .font(.system(size: forPDF ? 12 : metaSize))
                .foregroundColor(forPDF ? Color.black.opacity(0.55) : .aurionTextSecondary)
                .padding(.top, 4)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            ForEach(note.sections, id: \.id) { section in
                sectionView(section)
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

    @ViewBuilder
    private func sectionView(_ section: NoteSectionResponse) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(section.title)
                    .font(.system(size: forPDF ? 20 : sectionHeadingSize, weight: .semibold))
                    .foregroundColor(forPDF ? .black : .aurionTextPrimary)
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
                EmptyStateView(
                    icon: "doc.questionmark",
                    title: L("sessionNote.noNote"),
                    subtitle: error ?? L("sessionNote.noNoteSub")
                )
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
                            .font(.system(size: 14, weight: .semibold))
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
            Button(L("sessionNote.exportPDF")) { exportNote(as: .pdf) }
            Button(L("sessionNote.exportDOCX")) { exportNote(as: .docx) }
        }
        .sheet(isPresented: $showShareSheet) {
            if let url = exportFileURL {
                ShareSheet(items: [url])
            }
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
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
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
                            dateString: displayDate
                        )
                    }
                case .docx:
                    data = try NoteDocumentBuilder.makeDocx(
                        note, sessionId: note.sessionId
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
                    self.error = L("export.failedShort")
                    self.isPreparingExport = false
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
