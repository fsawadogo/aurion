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
    @State private var exportProgress: CGFloat = 0

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            if exportComplete {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 60))
                    .foregroundColor(Color.aurionGold)
                    .transition(AurionTransition.scaleIn)

                Text("Note Exported")
                    .font(.title2)
                    .fontWeight(.bold)
                    .foregroundColor(.aurionTextPrimary)

                Text("The DOCX file is ready. Raw data cleanup has been triggered.")
                    .font(.body)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 20)

                if exportData != nil {
                    Button("Share DOCX") {
                        showShareSheet = true
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                }
            } else if isExporting {
                // Custom export progress view
                VStack(spacing: 20) {
                    Image(systemName: "doc.richtext")
                        .font(.system(size: 36))
                        .foregroundColor(.aurionTextPrimary)

                    Text("Exporting note...")
                        .font(.headline)
                        .foregroundColor(.aurionTextPrimary)

                    // Indeterminate gold progress bar
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            RoundedRectangle(cornerRadius: 4)
                                .fill(Color.aurionNavy.opacity(0.1))
                                .frame(height: 6)

                            RoundedRectangle(cornerRadius: 4)
                                .fill(Color.aurionGold)
                                .frame(width: geo.size.width * 0.3, height: 6)
                                .offset(x: exportProgress * (geo.size.width * 0.7))
                        }
                    }
                    .frame(height: 6)
                    .padding(.horizontal, 40)
                    .onAppear {
                        withAnimation(
                            .easeInOut(duration: 1.0).repeatForever(autoreverses: true)
                        ) {
                            exportProgress = 1.0
                        }
                    }
                }
            } else {
                // Initial state with document icon
                VStack(spacing: 20) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 14)
                            .fill(Color.aurionNavy.opacity(0.06))
                            .frame(width: 80, height: 80)

                        Image(systemName: "doc.richtext")
                            .font(.system(size: 36))
                            .foregroundColor(.aurionTextPrimary)
                    }

                    Text("Export your clinical note as a DOCX document.")
                        .font(.body)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                        .padding(.horizontal, 20)

                    Button("Export as DOCX") {
                        exportNote()
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                }

                if let error = errorMessage {
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.red)
                }
            }

            Spacer()
        }
        .padding(20)
        .sheet(isPresented: $showShareSheet) {
            if let data = exportData {
                ShareSheet(items: [data])
            }
        }
    }

    private func exportNote() {
        isExporting = true
        exportProgress = 0
        Task {
            do {
                let data = try await APIClient.shared.exportNote(sessionId: sessionId)
                exportData = data
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
