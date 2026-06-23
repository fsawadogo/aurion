import SwiftUI
import UniformTypeIdentifiers

/// Export view -- generates DOCX / PDF / plain text fully on-device. The
/// backend is only told that an export happened (via /export-audit) so
/// no clinical bytes leave the phone. Triggers the cleanup pipeline on
/// the same audit hook the server-side flow uses.
///
/// All three formats ship and are selectable: DOCX opens in Pages/Word,
/// PDF renders via NotePDFRenderer, and plain text is the fallback.
struct ExportView: View {
    let sessionId: String
    @EnvironmentObject var sessionManager: SessionManager
    /// #271 DT: drives the file-info card's two-up → stacked fallback.
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    /// #271 DT: the file-info card's vertical dividers scale with Dynamic
    /// Type instead of a hardcoded 32pt so they match the (taller) content.
    @ScaledMetric private var fileInfoDividerHeight: CGFloat = 32
    @State private var note: NoteResponse?
    /// Most recent purge result — drives the "Local data purged" status
    /// chip in the completion view. nil until purge fires.
    @State private var purgeReport: LocalDataPurger.PurgeReport?
    @State private var isExporting = false
    @State private var exportComplete = false
    @State private var exportFileURL: URL?
    @State private var showShareSheet = false
    @State private var errorMessage: String?
    @State private var exportProgress: Double = 0
    @State private var selectedFormat: ExportFormat = .docx

    enum ExportFormat: String, CaseIterable {
        case docx = "DOCX"
        case pdf = "PDF"
        case text = "Text"

        var icon: String {
            switch self {
            case .docx: return "doc.richtext"
            case .pdf: return "doc.fill"
            case .text: return "doc.plaintext"
            }
        }

        var mimeDescription: String {
            switch self {
            case .docx: return L("export.mime.docx")
            case .pdf: return L("export.mime.pdf")
            case .text: return L("export.mime.text")
            }
        }

        /// Server-side `format` value for the audit POST.
        var auditFormatName: String {
            switch self {
            case .docx: return "docx"
            case .text: return "plain_text"
            case .pdf: return "pdf"
            }
        }

        var fileExtension: String {
            switch self {
            case .docx: return "docx"
            case .text: return "txt"
            case .pdf: return "pdf"
            }
        }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Format selector pills — pinned above the scrolling content.
            formatSelector
                .padding(.top, AurionSpacing.xl)
                .padding(.horizontal, AurionSpacing.xl)

            // #271 DT: the descriptive state content scrolls and the primary
            // action (Export / Share) rides a pinned bottom footer so the CTA
            // never clips off-screen at large Dynamic Type sizes. The
            // min-height frame keeps the content vertically centered when it
            // fits.
            GeometryReader { proxy in
                ScrollView {
                    VStack(spacing: 0) {
                        Spacer(minLength: AurionSpacing.xl)
                        stateContent
                        Spacer(minLength: AurionSpacing.xl)
                    }
                    .frame(maxWidth: .infinity)
                    .frame(minHeight: proxy.size.height)
                    .padding(.horizontal, AurionSpacing.xl)
                }
                .scrollBounceBehavior(.basedOnSize)
            }
        }
        .background(Color.aurionBackground.ignoresSafeArea())
        .safeAreaInset(edge: .bottom) { exportFooter }
        .task {
            // Fetch the LATEST note version once — `getFullNote` returns
            // the Stage 2-enriched version when available so the export
            // includes visual citations. Stage 1 only is the wrong source
            // if vision finished after approval. The exporter is pure;
            // bytes are produced locally from this snapshot.
            if note == nil {
                note = try? await APIClient.shared.getFullNote(sessionId: sessionId)
            }
        }
        .sheet(isPresented: $showShareSheet, onDismiss: {
            // The export file (full note — PHI) was kept out of the post-export
            // purge so Share could use it; remove it now that the user is done.
            // The 24h stale sweep is the backstop if the app dies before this.
            if let url = exportFileURL {
                try? FileManager.default.removeItem(at: url)
                exportFileURL = nil
            }
        }) {
            if let url = exportFileURL {
                ShareSheet(items: [url])
            }
        }
    }

    // MARK: - Scrolling content (per state)

    /// The descriptive body for the current state. The actionable CTA lives
    /// in ``exportFooter`` so it stays pinned + reachable (#271 DT).
    @ViewBuilder
    private var stateContent: some View {
        if exportComplete {
            completionContent
        } else if isExporting {
            progressView
        } else {
            initialContent
        }
    }

    // MARK: - Footer (pinned primary action)

    /// State-dependent primary action, pinned to the bottom safe area so it
    /// never scrolls off-screen at large Dynamic Type sizes (#271).
    @ViewBuilder
    private var exportFooter: some View {
        if exportComplete {
            if let url = exportFileURL {
                VStack(spacing: AurionSpacing.sm) {
                    Button {
                        showShareSheet = true
                    } label: {
                        HStack {
                            Image(systemName: "square.and.arrow.up")
                            Text(L("export.share", selectedFormat.rawValue))
                        }
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())

                    if let size = try? url.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                        Text("\(selectedFormat.rawValue) -- \(ByteCountFormatter.string(fromByteCount: Int64(size), countStyle: .file))")
                            .aurionCaption()
                    }
                }
                .padding(.horizontal, AurionSpacing.xl)
                .padding(.top, AurionSpacing.md)
                .padding(.bottom, AurionSpacing.sm)
            }
        } else if !isExporting {
            Button(L("export.exportAs", selectedFormat.rawValue)) {
                exportNote()
            }
            .buttonStyle(AurionPrimaryButtonStyle())
            .padding(.horizontal, AurionSpacing.xl)
            .padding(.top, AurionSpacing.md)
            .padding(.bottom, AurionSpacing.sm)
        }
        // While exporting there is no action — the progress view owns the screen.
    }

    // MARK: - Format Selector

    private var formatSelector: some View {
        HStack(spacing: 0) {
            ForEach(ExportFormat.allCases, id: \.self) { format in
                Button {
                    AurionHaptics.selection()
                    withAnimation(AurionAnimation.spring) {
                        selectedFormat = format
                    }
                } label: {
                    Text(format.rawValue)
                        .aurionFont(13, weight: .bold, relativeTo: .footnote)
                        // #271 DT: the labels are fixed short tokens
                        // (DOCX/PDF/Text), so the horizontal 3-up holds at
                        // accessibility sizes — clamp to one line with a
                        // shrink floor rather than adding a vertical fallback.
                        .lineLimit(1)
                        .minimumScaleFactor(0.6)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, AurionSpacing.sm)
                        .background(
                            selectedFormat == format
                                ? Color.aurionGold
                                : Color.aurionFieldBackground
                        )
                        .foregroundColor(
                            // Brand-navy on gold — matches AurionGoldButton.
                            // `.white` washed out against the gold fill (#298).
                            selectedFormat == format
                                ? .aurionNavy
                                : .aurionTextPrimary
                        )
                }
                .accessibilityAddTraits(selectedFormat == format ? .isSelected : [])
            }
        }
        .clipShape(Capsule())
        .overlay(Capsule().stroke(Color.aurionGold.opacity(0.2), lineWidth: 1))
    }

    // MARK: - Initial State

    /// Descriptive part of the initial state. The "Export as …" button lives
    /// in ``exportFooter`` (#271 DT) so it can't clip off-screen.
    private var initialContent: some View {
        VStack(spacing: AurionSpacing.xxl) {
            // Document icon
            ZStack {
                Circle()
                    // Adaptive halo (was .aurionNavy.opacity(0.06),
                    // invisible on the dark background in dark mode) (#293).
                    .fill(Color.aurionSurfaceAlt)
                    .frame(width: 100, height: 100)

                Image(systemName: selectedFormat.icon)
                    .font(.system(size: 40, weight: .light))
                    .foregroundColor(.aurionTextPrimary)
            }

            VStack(spacing: AurionSpacing.sm) {
                Text(L("export.title"))
                    .aurionTitle()

                Text(L("export.subtitle", selectedFormat.mimeDescription))
                    .aurionFont(15, weight: .regular, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, AurionSpacing.xl)
            }

            fileInfoCard

            if let error = errorMessage {
                ErrorBanner(
                    error,
                    onRetry: { exportNote() },
                    onDismiss: { errorMessage = nil }
                )
            }
        }
    }

    // MARK: - File Info Card

    /// Format / size / PHI summary. #271 DT: three columns with scaled
    /// vertical dividers when they fit; stacks to rows with full-width
    /// dividers when they can't (accessibility text sizes).
    private var fileInfoCard: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: AurionSpacing.lg) {
                fileInfoItem(icon: "doc.text", label: L("export.format"), value: selectedFormat.rawValue)
                Divider().frame(height: fileInfoDividerHeight)
                fileInfoItem(icon: "internaldrive", label: L("export.estSize"), value: estimatedSizeLabel)
                Divider().frame(height: fileInfoDividerHeight)
                fileInfoItem(icon: "lock.shield", label: L("export.phi"), value: L("export.scrubbed"))
            }
            VStack(spacing: AurionSpacing.md) {
                fileInfoItem(icon: "doc.text", label: L("export.format"), value: selectedFormat.rawValue)
                Divider()
                fileInfoItem(icon: "internaldrive", label: L("export.estSize"), value: estimatedSizeLabel)
                Divider()
                fileInfoItem(icon: "lock.shield", label: L("export.phi"), value: L("export.scrubbed"))
            }
        }
        .padding(AurionSpacing.lg)
        .background(Color.aurionCardBackground)
        .cornerRadius(AurionSpacing.sm)
    }

    // MARK: - Progress State

    private var progressView: some View {
        VStack(spacing: AurionSpacing.xxl) {
            ZStack {
                Circle()
                    // Adaptive halo (was .aurionNavy.opacity(0.06),
                    // invisible on the dark background in dark mode) (#293).
                    .fill(Color.aurionSurfaceAlt)
                    .frame(width: 100, height: 100)

                CircularProgressRing(
                    progress: exportProgress,
                    color: .aurionGold,
                    lineWidth: 4,
                    size: 80
                )

                Text("\(Int(exportProgress * 100))%")
                    .font(.system(size: 18, weight: .bold, design: .rounded))
                    .foregroundColor(.aurionTextPrimary)
            }

            VStack(spacing: AurionSpacing.sm) {
                Text(L("export.exporting"))
                    .aurionFont(17, weight: .semibold, relativeTo: .headline)
                    .foregroundColor(.aurionTextPrimary)

                Text(progressLabel)
                    .aurionFont(13, weight: .medium, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
            }

            // Linear progress bar
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 4)
                        // Adaptive track (was .aurionNavy.opacity(0.1),
                        // invisible in dark mode) (#293).
                        .fill(Color.aurionSurfaceAlt)
                        .frame(height: 6)

                    RoundedRectangle(cornerRadius: 4)
                        .fill(
                            LinearGradient(
                                colors: [.aurionGold, .aurionGoldLight],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: geo.size.width * exportProgress, height: 6)
                        .animation(AurionAnimation.smooth, value: exportProgress)
                }
            }
            .frame(height: 6)
            .padding(.horizontal, AurionSpacing.xxl)
        }
    }

    private var progressLabel: String {
        if exportProgress < 0.3 {
            return L("export.prep")
        } else if exportProgress < 0.6 {
            return L("export.formatting")
        } else if exportProgress < 0.9 {
            return L("export.generating")
        } else {
            return L("export.finalizing")
        }
    }

    // MARK: - Completion State

    /// Descriptive part of the completion state. The Share button + size
    /// label live in ``exportFooter`` (#271 DT); the purge-confirmation chip
    /// stays here as a status note.
    private var completionContent: some View {
        VStack(spacing: AurionSpacing.xxl) {
            AurionIconBubble(symbol: "checkmark.circle.fill", tint: .aurionGold, size: 100, symbolWeight: .regular)
                .transition(AurionTransition.scaleIn)

            VStack(spacing: AurionSpacing.sm) {
                Text(L("export.done"))
                    .aurionTitle()

                Text(L("export.doneSub", selectedFormat.rawValue))
                    .aurionFont(15, weight: .regular, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, AurionSpacing.xl)
            }

            // M-12: visible confirmation that the local raw bytes were
            // purged. Surfaces the artifact count so the clinician can
            // see *what* was cleaned up, not just that something happened.
            if let report = purgeReport {
                HStack(spacing: AurionSpacing.xs) {
                    Image(systemName: "checkmark.shield.fill")
                        .foregroundColor(.clinicalNormal)
                    Text(Lplural("export.purged", report.totalArtifactsPurged))
                        .aurionFont(12, weight: .medium, relativeTo: .caption)
                        .foregroundColor(.aurionTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.horizontal, AurionSpacing.md)
                .padding(.vertical, AurionSpacing.xs)
                .background(Color.clinicalNormal.opacity(0.08))
                .clipShape(Capsule())
            }
        }
    }

    /// Rough on-device size estimate for the file-info card. The
    /// exporters run synchronously from the loaded note, so we approximate
    /// the output by tallying the section + claim text the document will
    /// contain and dividing by 1 KB (#298 — replaces a hardcoded "~25 KB"
    /// that ignored content). Cosmetic: the completion view shows the true
    /// byte count once the file is written.
    private var estimatedSizeLabel: String {
        guard let note else { return "--" }
        let chars = note.sections.reduce(0) { sectionSum, section in
            sectionSum + section.title.count + section.claims.reduce(0) { claimSum, claim in
                claimSum + claim.text.count + claim.sourceQuote.count
            }
        }
        let kb = max(1, Int((Double(chars) / 1024.0).rounded()))
        return L("export.estSizeValue", kb)
    }

    // MARK: - File Info Item

    private func fileInfoItem(icon: String, label: String, value: String) -> some View {
        VStack(spacing: AurionSpacing.xxs) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(.aurionGold)
            Text(value)
                .aurionFont(13, weight: .bold, relativeTo: .footnote)
                .foregroundColor(.aurionTextPrimary)
            Text(label)
                .aurionMicro()
        }
        .frame(maxWidth: .infinity)
    }

    // MARK: - Export Action

    private func exportNote() {
        guard let note else {
            errorMessage = L("export.notLoaded")
            return
        }
        isExporting = true
        exportProgress = 0
        errorMessage = nil

        Task {
            // Smooth determinate progress for UX; the actual generation
            // is synchronous and instant on-device, so the steps are
            // cosmetic but match the user's expectation of "working".
            for step in stride(from: 0.1, through: 0.7, by: 0.15) {
                try? await Task.sleep(nanoseconds: 120_000_000)
                await MainActor.run { exportProgress = step }
            }

            do {
                let data: Data
                switch selectedFormat {
                case .docx:
                    data = try NoteDocumentBuilder.makeDocx(note, sessionId: sessionId)
                case .text:
                    data = NoteDocumentBuilder.makePlainText(note, sessionId: sessionId)
                case .pdf:
                    let (specialty, date) = noteDisplayStrings(for: sessionId, fallbackNote: note)
                    data = try await MainActor.run {
                        try NotePDFRenderer.render(
                            note: note,
                            specialtyTitle: specialty,
                            dateString: date
                        )
                    }
                }

                let url = try writeToTempFile(data: data, format: selectedFormat)
                exportFileURL = url

                await MainActor.run { exportProgress = 0.9 }

                // Audit BEFORE finalising the UI — if the backend rejects
                // the state transition (e.g., note not approved), we want
                // to surface that, not silently succeed locally.
                _ = try await APIClient.shared.recordExportAudit(
                    sessionId: sessionId,
                    format: selectedFormat.auditFormatName,
                    bytesProduced: data.count
                )

                await MainActor.run { exportProgress = 1.0 }
                try? await Task.sleep(nanoseconds: 200_000_000)

                withAnimation(AurionAnimation.smooth) {
                    exportComplete = true
                }
                AurionHaptics.notification(.success)
                AuditLogger.log(
                    event: .noteExported,
                    sessionId: sessionId,
                    extra: ["format": selectedFormat.auditFormatName]
                )

                // M-12: the export-triggered purge is the canonical
                // local-data cleanup hook. We run it AFTER the audit
                // event is written so the timeline reads
                // exported → purged in the right order.
                // Keep the just-written export file — the Share sheet is about
                // to hand it to UIActivityViewController. Without this, the
                // post-export sweep deleted it out from under Share, leaving a
                // dead URL. It's cleaned when the Share sheet dismisses
                // (`.sheet` onDismiss) or by the 24h stale sweep otherwise.
                let report = LocalDataPurger.purgeAll(
                    sessionManager: sessionManager,
                    reason: "post_export",
                    keep: [url]
                )
                await MainActor.run { purgeReport = report }
            } catch {
                errorMessage = L("export.failed", error.localizedDescription)
            }
            isExporting = false
        }
    }

    /// Display strings for the PDF title block. Mirrors what
    /// ``SessionNoteView`` computes from its ``SessionResponse``, but
    /// ExportView only has the loaded ``NoteResponse`` to draw from —
    /// note.specialty gives us the title; date defaults to the export
    /// timestamp since the note payload doesn't carry the encounter date.
    private func noteDisplayStrings(for sessionId: String, fallbackNote: NoteResponse) -> (String, String) {
        let title = localizedSpecialty(fallbackNote.specialty)
        let f = DateFormatter()
        f.dateStyle = .medium
        f.timeStyle = .short
        return (title, f.string(from: Date()))
    }

    /// Stage the bytes as a temporary file so the share sheet shows the
    /// right filename + extension instead of a generic Data preview.
    private func writeToTempFile(data: Data, format: ExportFormat) throws -> URL {
        let dir = FileManager.default.temporaryDirectory
        let filename = "aurion_note_\(sessionId).\(format.fileExtension)"
        let url = dir.appendingPathComponent(filename)
        try data.write(to: url, options: [.atomic])
        return url
    }
}

// MARK: - Share Sheet

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}
