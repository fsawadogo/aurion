import SwiftUI
import UniformTypeIdentifiers

/// Export view -- generates DOCX on-device or triggers backend export.
/// Triggers cleanup pipeline on export completion.
struct ExportView: View {
    let sessionId: String
    @State private var isExporting = false
    @State private var exportComplete = false
    @State private var exportData: Data?
    @State private var showShareSheet = false
    @State private var errorMessage: String?
    @State private var exportProgress: Double = 0
    @State private var selectedFormat: ExportFormat = .docx

    enum ExportFormat: String, CaseIterable {
        case docx = "DOCX"
        case pdf = "PDF"
        case text = "Text"

        var isAvailable: Bool { self == .docx }

        var icon: String {
            switch self {
            case .docx: return "doc.richtext"
            case .pdf: return "doc.fill"
            case .text: return "doc.plaintext"
            }
        }

        var mimeDescription: String {
            switch self {
            case .docx: return "Microsoft Word Document"
            case .pdf: return "Portable Document Format"
            case .text: return "Plain Text File"
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
        .sheet(isPresented: $showShareSheet) {
            if let data = exportData {
                ShareSheet(items: [data])
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
                            Text("Coming Soon")
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
                Text("Export Clinical Note")
                    .aurionTitle()

                Text("Generate a \(selectedFormat.mimeDescription) for your records.")
                    .font(.system(size: 15, weight: .regular))
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, AurionSpacing.xl)
            }

            // File info card
            HStack(spacing: AurionSpacing.lg) {
                fileInfoItem(icon: "doc.text", label: "Format", value: selectedFormat.rawValue)
                Divider().frame(height: 32)
                fileInfoItem(icon: "internaldrive", label: "Est. Size", value: "~25 KB")
                Divider().frame(height: 32)
                fileInfoItem(icon: "lock.shield", label: "PHI", value: "Scrubbed")
            }
            .padding(AurionSpacing.lg)
            .background(Color.aurionCardBackground)
            .cornerRadius(AurionSpacing.sm)

            Button("Export as \(selectedFormat.rawValue)") {
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
                Text("Exporting note...")
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
            return "Preparing document..."
        } else if exportProgress < 0.6 {
            return "Formatting sections..."
        } else if exportProgress < 0.9 {
            return "Generating file..."
        } else {
            return "Finalizing..."
        }
    }

    // MARK: - Completion State

    private var completionView: some View {
        VStack(spacing: AurionSpacing.xxl) {
            ZStack {
                Circle()
                    .fill(Color.clinicalNormal.opacity(0.1))
                    .frame(width: 100, height: 100)

                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 52))
                    .foregroundColor(Color.aurionGold)
            }
            .transition(AurionTransition.scaleIn)

            VStack(spacing: AurionSpacing.sm) {
                Text("Note Exported")
                    .aurionTitle()

                Text("The \(selectedFormat.rawValue) file is ready. Raw data cleanup has been triggered.")
                    .font(.system(size: 15, weight: .regular))
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, AurionSpacing.xl)
            }

            if exportData != nil {
                VStack(spacing: AurionSpacing.sm) {
                    Button {
                        showShareSheet = true
                    } label: {
                        HStack {
                            Image(systemName: "square.and.arrow.up")
                            Text("Share \(selectedFormat.rawValue)")
                        }
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())

                    // File info
                    if let data = exportData {
                        Text("\(selectedFormat.rawValue) -- \(ByteCountFormatter.string(fromByteCount: Int64(data.count), countStyle: .file))")
                            .aurionCaption()
                    }
                }
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
        isExporting = true
        exportProgress = 0
        errorMessage = nil

        Task {
            // Simulate determinate progress steps
            for step in stride(from: 0.1, through: 0.7, by: 0.15) {
                try? await Task.sleep(nanoseconds: 200_000_000)
                await MainActor.run { exportProgress = step }
            }

            do {
                let data = try await APIClient.shared.exportNote(sessionId: sessionId)
                exportData = data

                await MainActor.run { exportProgress = 0.9 }
                try? await Task.sleep(nanoseconds: 200_000_000)
                await MainActor.run { exportProgress = 1.0 }

                try? await Task.sleep(nanoseconds: 300_000_000)

                withAnimation(AurionAnimation.smooth) {
                    exportComplete = true
                }
                AurionHaptics.notification(.success)
                AuditLogger.log(event: .noteExported, sessionId: sessionId)
            } catch {
                errorMessage = "Export failed: \(error.localizedDescription)"
            }
            isExporting = false
        }
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
