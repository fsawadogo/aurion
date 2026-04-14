import SwiftUI
import UIKit

// MARK: - Section Styling Helpers

private extension String {
    /// Map section ID to a left-border color.
    var sectionBorderColor: Color {
        switch self {
        case "chief_complaint", "hpi":
            return .clinicalInfo
        case "physical_exam", "wound_assessment", "functional_assessment":
            return .clinicalNormal
        case "imaging_review", "investigations", "vital_signs":
            return .clinicalInfo
        case "assessment":
            return .clinicalWarning
        case "plan", "disposition":
            return .aurionNavy
        default:
            return .secondary.opacity(0.3)
        }
    }

    /// Map section ID to an SF Symbol icon.
    var sectionIcon: String {
        switch self {
        case "chief_complaint": return "exclamationmark.bubble.fill"
        case "hpi": return "clock.fill"
        case "physical_exam": return "hand.raised.fill"
        case "wound_assessment": return "bandage.fill"
        case "functional_assessment": return "figure.walk"
        case "imaging_review": return "photo.on.rectangle.angled"
        case "investigations": return "flask.fill"
        case "vital_signs": return "heart.fill"
        case "assessment": return "list.clipboard.fill"
        case "plan": return "arrow.right.circle.fill"
        case "disposition": return "arrow.uturn.right.circle.fill"
        default: return "doc.text.fill"
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

    var body: some View {
        ZStack {
            if isLoading {
                ProgressView("Loading note...")
            } else if let note {
                noteContent(note)
            } else {
                EmptyStateView(
                    icon: "doc.questionmark",
                    title: "No note available",
                    subtitle: error ?? "The note could not be loaded."
                )
            }

            // Copied toast
            if showCopiedToast {
                VStack {
                    Spacer()
                    HStack(spacing: AurionSpacing.sm) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.clinicalNormal)
                        Text("Copied to clipboard")
                            .font(.system(size: 14, weight: .semibold))
                    }
                    .foregroundColor(.white)
                    .padding(.horizontal, AurionSpacing.xl)
                    .padding(.vertical, AurionSpacing.sm)
                    .background(Color.aurionNavy)
                    .clipShape(Capsule())
                    .shadow(color: .black.opacity(0.2), radius: 12, y: 6)
                    .padding(.bottom, AurionSpacing.xxl)
                    .transition(AurionTransition.fadeUp)
                }
                .animation(AurionAnimation.spring, value: showCopiedToast)
            }
        }
        .navigationTitle(displaySpecialty)
        .aurionNavBar()
        .toolbar {
            ToolbarItemGroup(placement: .navigationBarTrailing) {
                Button {
                    if let note { copyToClipboard(note) }
                } label: {
                    Image(systemName: "doc.on.doc")
                }
                .disabled(note == nil)

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
            VStack(alignment: .leading, spacing: AurionSpacing.lg) {
                // Header card
                VStack(alignment: .leading, spacing: AurionSpacing.sm) {
                    HStack {
                        Text(displaySpecialty)
                            .aurionTitle()
                        Spacer()
                        HStack(spacing: AurionSpacing.xs) {
                            CircularProgressRing(
                                progress: note.completenessScore,
                                color: note.completenessScore >= 0.9 ? .clinicalNormal : .clinicalWarning,
                                lineWidth: 3,
                                size: 28
                            )
                            Text("\(Int(note.completenessScore * 100))%")
                                .font(.system(size: 13, weight: .bold, design: .rounded))
                                .foregroundColor(note.completenessScore >= 0.9 ? .clinicalNormal : .clinicalWarning)
                        }
                    }

                    HStack(spacing: AurionSpacing.lg) {
                        Label(displayDate, systemImage: "calendar")
                        Label("v\(note.version)", systemImage: "doc.badge.clock")
                        Label(note.providerUsed, systemImage: "cpu")
                    }
                    .aurionCaption()
                }
                .padding(AurionSpacing.lg)
                .background(Color.aurionCardBackground)
                .cornerRadius(AurionSpacing.sm)

                // Sections
                ForEach(note.sections, id: \.id) { section in
                    sectionCard(section)
                }

                // EMR Integration placeholder
                VStack(spacing: AurionSpacing.sm) {
                    Image(systemName: "arrow.triangle.2.circlepath")
                        .font(.title2)
                        .foregroundColor(.secondary.opacity(0.4))
                    Text("EMR Integration")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundColor(.secondary)
                    Text("Coming Soon")
                        .aurionCaption()
                }
                .frame(maxWidth: .infinity)
                .padding(AurionSpacing.xl)
                .background(Color.aurionFieldBackground)
                .cornerRadius(AurionSpacing.sm)
            }
            .padding(AurionSpacing.xl)
        }
        .background(Color.aurionBackground)
    }

    // MARK: - Section Card with Colored Border

    private func sectionCard(_ section: NoteSectionResponse) -> some View {
        let borderColor = section.id.sectionBorderColor
        let icon = section.id.sectionIcon

        return VStack(alignment: .leading, spacing: AurionSpacing.sm) {
            // Section header with icon
            HStack(spacing: AurionSpacing.sm) {
                Image(systemName: icon)
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(borderColor)

                Text(section.title)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundColor(.aurionTextPrimary)

                Spacer()

                sectionStatusBadge(section.status)
            }

            if section.claims.isEmpty {
                Text("No content captured")
                    .aurionBody()
                    .foregroundColor(.secondary)
                    .italic()
                    .padding(.top, AurionSpacing.xxs)
            } else {
                ForEach(section.claims, id: \.id) { claim in
                    VStack(alignment: .leading, spacing: AurionSpacing.xxs) {
                        Text(claim.text)
                            .aurionBody()

                        HStack(spacing: AurionSpacing.xxs) {
                            Image(systemName: claim.sourceType == "visual" ? "eye.circle" : "waveform")
                                .font(.system(size: 10))
                            Text("[\(claim.sourceId)]")
                                .font(.system(size: 10))
                        }
                        .aurionCaption()
                    }
                    .padding(.vertical, AurionSpacing.xxs)
                }
            }
        }
        .padding(AurionSpacing.lg)
        .background(Color.aurionCardBackground)
        .cornerRadius(AurionSpacing.sm)
        .overlay(
            HStack {
                RoundedRectangle(cornerRadius: 2)
                    .fill(borderColor)
                    .frame(width: 4)
                Spacer()
            }
            .clipShape(RoundedRectangle(cornerRadius: AurionSpacing.sm))
        )
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
        isLoading = false
    }

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

    private func exportNote() {
        guard let note else { return }
        Task {
            do {
                _ = try await APIClient.shared.exportNote(sessionId: note.sessionId)
                AurionHaptics.notification(.success)
            } catch {
                self.error = "Export failed"
            }
        }
    }
}
