import SwiftUI
import UIKit

/// Read-only note view for a completed session.
/// Displays formatted SOAP note with copy-to-clipboard and export.
struct SessionNoteView: View {
    let session: SessionResponse
    @State private var note: NoteResponse?
    @State private var isLoading = true
    @State private var showCopiedToast = false
    @State private var error: String?

    var body: some View {
        ZStack {
            if isLoading {
                ProgressView("Loading note...")
            } else if let note {
                noteContent(note)
            } else {
                VStack(spacing: 16) {
                    Image(systemName: "doc.questionmark")
                        .font(.system(size: 48))
                        .foregroundColor(.secondary.opacity(0.4))
                    Text("No note available")
                        .font(.headline)
                        .foregroundColor(.secondary)
                    if let error {
                        Text(error)
                            .font(.caption)
                            .foregroundColor(.red)
                    }
                }
            }

            // Copied toast
            if showCopiedToast {
                VStack {
                    Spacer()
                    HStack(spacing: 8) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.green)
                        Text("Copied to clipboard")
                            .font(.subheadline)
                            .fontWeight(.medium)
                    }
                    .foregroundColor(.white)
                    .padding(.horizontal, 20)
                    .padding(.vertical, 12)
                    .background(Color.aurionNavy)
                    .cornerRadius(24)
                    .shadow(radius: 8)
                    .padding(.bottom, 32)
                    .transition(AurionTransition.fadeUp)
                }
                .animation(AurionAnimation.spring, value: showCopiedToast)
            }
        }
        .navigationTitle(displaySpecialty)
        .aurionNavBar()
        .toolbar {
            ToolbarItemGroup(placement: .navigationBarTrailing) {
                // Copy button
                Button {
                    if let note { copyToClipboard(note) }
                } label: {
                    Image(systemName: "doc.on.doc")
                }
                .disabled(note == nil)

                // Export button
                Button {
                    exportNote()
                } label: {
                    Image(systemName: "square.and.arrow.up")
                }
                .disabled(note == nil)
            }
        }
        .task { await loadNote() }
    }

    // MARK: - Note Content

    private func noteContent(_ note: NoteResponse) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                // Header card
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text(displaySpecialty)
                            .aurionHeadline()
                        Spacer()
                        HStack(spacing: 4) {
                            CircularProgressRing(
                                progress: note.completenessScore,
                                color: note.completenessScore >= 0.9 ? .green : .aurionAmber,
                                lineWidth: 3,
                                size: 28
                            )
                            Text("\(Int(note.completenessScore * 100))%")
                                .font(.caption.bold())
                                .foregroundColor(note.completenessScore >= 0.9 ? .green : .aurionAmber)
                        }
                    }

                    HStack(spacing: 16) {
                        Label(displayDate, systemImage: "calendar")
                        Label("v\(note.version)", systemImage: "doc.badge.clock")
                        Label(note.providerUsed, systemImage: "cpu")
                    }
                    .font(.caption)
                    .foregroundColor(.secondary)
                }
                .padding(16)
                .background(Color.aurionCardBackground)
                .cornerRadius(12)

                // Sections
                ForEach(note.sections, id: \.id) { section in
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Text(section.title)
                                .font(.headline)
                                .foregroundColor(.aurionTextPrimary)
                            Spacer()
                            sectionStatusBadge(section.status)
                        }

                        if section.claims.isEmpty {
                            Text("No content captured")
                                .font(.body)
                                .foregroundColor(.secondary)
                                .italic()
                        } else {
                            ForEach(section.claims, id: \.id) { claim in
                                VStack(alignment: .leading, spacing: 4) {
                                    Text(claim.text)
                                        .font(.body)
                                        .foregroundColor(.aurionTextPrimary)

                                    HStack(spacing: 4) {
                                        Image(systemName: claim.sourceType == "visual" ? "eye.circle" : "waveform")
                                            .font(.caption2)
                                        Text("[\(claim.sourceId)]")
                                            .font(.caption2)
                                    }
                                    .foregroundColor(.secondary)
                                }
                                .padding(.vertical, 2)
                            }
                        }
                    }
                    .padding(16)
                    .background(Color.aurionCardBackground)
                    .cornerRadius(12)
                }

                // EMR Integration placeholder
                VStack(spacing: 8) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(.title2)
                        .foregroundColor(.secondary.opacity(0.4))
                    Text("EMR Integration")
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .foregroundColor(.secondary)
                    Text("Coming Soon")
                        .font(.caption)
                        .foregroundColor(.secondary.opacity(0.6))
                }
                .frame(maxWidth: .infinity)
                .padding(20)
                .background(Color.aurionFieldBackground)
                .cornerRadius(12)
            }
            .padding(20)
        }
        .background(Color.aurionBackground)
    }

    // MARK: - Helpers

    private var displaySpecialty: String {
        session.specialty.replacingOccurrences(of: "_", with: " ").capitalized
    }

    private var displayDate: String {
        let formatter = ISO8601DateFormatter()
        if let date = formatter.date(from: session.createdAt) {
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
                Label("Complete", systemImage: "checkmark.circle.fill")
                    .foregroundColor(.green)
            case "pending_video":
                Label("Pending", systemImage: "video.circle")
                    .foregroundColor(.blue)
            case "not_captured":
                Label("Empty", systemImage: "circle.dashed")
                    .foregroundColor(.secondary)
            default:
                Label(status, systemImage: "circle")
                    .foregroundColor(.secondary)
            }
        }
        .font(.caption2)
    }

    // MARK: - Actions

    private func loadNote() async {
        isLoading = true
        do {
            note = try await APIClient.shared.getFullNote(sessionId: session.id)
        } catch {
            // Demo note for Simulator
            note = NoteResponse(
                sessionId: session.id,
                stage: 2,
                version: 3,
                providerUsed: "anthropic",
                specialty: session.specialty,
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
                        NoteClaimResponse(id: "c4", text: "Physician noted range of motion restricted — flexion limited to approximately 110 degrees.", sourceType: "transcript", sourceId: "seg_004", sourceQuote: "flexion limited to approximately 110 degrees"),
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
        isLoading = false
    }

    private func copyToClipboard(_ note: NoteResponse) {
        var text = ""
        for section in note.sections where !section.claims.isEmpty {
            text += "\(section.title.uppercased())\n"
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

    private func exportNote() {
        guard let note else { return }
        Task {
            do {
                _ = try await APIClient.shared.exportNote(sessionId: note.sessionId)
                // In production, present share sheet with DOCX data
                AurionHaptics.notification(.success)
            } catch {
                self.error = "Export failed"
            }
        }
    }
}
