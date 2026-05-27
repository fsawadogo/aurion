import SwiftUI
import UniformTypeIdentifiers

/// Export view -- generates DOCX / plain text fully on-device. The
/// backend is only told that an export happened (via /export-audit) so
/// no clinical bytes leave the phone. Triggers the cleanup pipeline on
/// the same audit hook the server-side flow uses.
///
/// PDF is intentionally deferred — DOCX opens in Pages/Word and the
/// pilot doesn't require a separate PDF path.
struct ExportView: View {
    let sessionId: String
    @EnvironmentObject var sessionManager: SessionManager
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

        var isAvailable: Bool { true }

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
            case .pdf: return "pdf"  // unreachable per isAvailable
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
            // Format selector pills
            formatSelector
                .padding(.top, AurionSpacing.xxl)
                .padding(.horizontal, AurionSpacing.xl)

            Spacer()

            if exportComplete {
                completionView
            } else if isExporting {
                progressView
            } else {
                initialView
            }

            Spacer()
        }
        .padding(AurionSpacing.xl)
        .background(Color.aurionBackground.ignoresSafeArea())
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
        .sheet(isPresented: $showShareSheet) {
            if let url = exportFileURL {
                ShareSheet(items: [url])
            }
        }
    }

    // MARK: - Format Selector

    private var formatSelector: some View {
        HStack(spacing: 0) {
            ForEach(ExportFormat.allCases, id: \.self) { format in
                Button {
                    if format.isAvailable {
                        AurionHaptics.selection()
                        withAnimation(AurionAnimation.spring) {
                            selectedFormat = format
                        }
                    }
                } label: {
                    VStack(spacing: AurionSpacing.xxs) {
                        Text(format.rawValue)
                            .font(.system(size: 13, weight: .bold))

                        if !format.isAvailable {
                            Text(L("export.comingSoon"))
                                .font(.system(size: 9, weight: .medium))
                                .foregroundColor(.secondary.opacity(0.6))
                        }
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, AurionSpacing.sm)
                    .background(
                        selectedFormat == format
                            ? Color.aurionGold
                            : Color.aurionFieldBackground
                    )
                    .foregroundColor(
                        selectedFormat == format
                            ? .white
                            : (format.isAvailable ? .aurionTextPrimary : .secondary.opacity(0.5))
                    )
                }
                .disabled(!format.isAvailable)
            }
        }
        .clipShape(Capsule())
        .overlay(Capsule().stroke(Color.aurionGold.opacity(0.2), lineWidth: 1))
    }

    // MARK: - Initial State

    private var initialView: some View {
        VStack(spacing: AurionSpacing.xxl) {
            // Document icon
            ZStack {
                Circle()
                    .fill(Color.aurionNavy.opacity(0.06))
                    .frame(width: 100, height: 100)

                Image(systemName: selectedFormat.icon)
                    .font(.system(size: 40, weight: .light))
                    .foregroundColor(.aurionTextPrimary)
            }

            VStack(spacing: AurionSpacing.sm) {
                Text(L("export.title"))
                    .aurionTitle()

                Text(L("export.subtitle", selectedFormat.mimeDescription))
                    .font(.system(size: 15, weight: .regular))
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, AurionSpacing.xl)
            }

            // File info card
            HStack(spacing: AurionSpacing.lg) {
                fileInfoItem(icon: "doc.text", label: L("export.format"), value: selectedFormat.rawValue)
                Divider().frame(height: 32)
                fileInfoItem(icon: "internaldrive", label: L("export.estSize"), value: "~25 KB")
                Divider().frame(height: 32)
                fileInfoItem(icon: "lock.shield", label: L("export.phi"), value: L("export.scrubbed"))
            }
            .padding(AurionSpacing.lg)
            .background(Color.aurionCardBackground)
            .cornerRadius(AurionSpacing.sm)

            Button(L("export.exportAs", selectedFormat.rawValue)) {
                exportNote()
            }
            .buttonStyle(AurionPrimaryButtonStyle())

            if let error = errorMessage {
                HStack(spacing: AurionSpacing.xs) {
                    Image(systemName: "exclamationmark.circle")
                        .foregroundColor(.clinicalAlert)
                    Text(error)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(.clinicalAlert)
                }
            }
        }
    }

    // MARK: - Progress State

    private var progressView: some View {
        VStack(spacing: AurionSpacing.xxl) {
            ZStack {
                Circle()
                    .fill(Color.aurionNavy.opacity(0.06))
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
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundColor(.aurionTextPrimary)

                Text(progressLabel)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(.secondary)
            }

            // Linear progress bar
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 4)
                        .fill(Color.aurionNavy.opacity(0.1))
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

    private var completionView: some View {
        VStack(spacing: AurionSpacing.xxl) {
            AurionIconBubble(symbol: "checkmark.circle.fill", tint: .aurionGold, size: 100, symbolWeight: .regular)
                .transition(AurionTransition.scaleIn)

            VStack(spacing: AurionSpacing.sm) {
                Text(L("export.done"))
                    .aurionTitle()

                Text(L("export.doneSub", selectedFormat.rawValue))
                    .font(.system(size: 15, weight: .regular))
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, AurionSpacing.xl)
            }

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
            }

            // M-12: visible confirmation that the local raw bytes were
            // purged. Surfaces the artifact count so the clinician can
            // see *what* was cleaned up, not just that something happened.
            if let report = purgeReport {
                HStack(spacing: AurionSpacing.xs) {
                    Image(systemName: "checkmark.shield.fill")
                        .foregroundColor(.clinicalNormal)
                    Text(Lplural("export.purged", report.totalArtifactsPurged))
                        .font(.system(size: 12, weight: .medium))
                        .foregroundColor(.aurionTextSecondary)
                }
                .padding(.horizontal, AurionSpacing.md)
                .padding(.vertical, AurionSpacing.xs)
                .background(Color.clinicalNormal.opacity(0.08))
                .clipShape(Capsule())
            }
        }
    }

    // MARK: - File Info Item

    private func fileInfoItem(icon: String, label: String, value: String) -> some View {
        VStack(spacing: AurionSpacing.xxs) {
            Image(systemName: icon)
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(.aurionGold)
            Text(value)
                .font(.system(size: 13, weight: .bold))
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
                let report = LocalDataPurger.purgeAll(
                    sessionManager: sessionManager,
                    reason: "post_export"
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
