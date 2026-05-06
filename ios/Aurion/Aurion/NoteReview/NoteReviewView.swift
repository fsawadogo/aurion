import SwiftUI

// MARK: - Conflict / classification helpers

private extension NoteClaimResponse {
    var isConflict: Bool { id.hasPrefix("conflict_") }
}

private extension NoteSectionResponse {
    var hasConflicts: Bool { claims.contains { $0.isConflict } }
    var conflictCount: Int { claims.filter { $0.isConflict }.count }
}

private extension NoteResponse {
    var hasUnresolvedConflicts: Bool { sections.contains { $0.hasConflicts } }
}

/// Maps a section id to its design-system accent color (left bar + icon).
/// Per `colors_and_type.css`: info=blue, exam=green, assessment=amber, plan=navy.
private extension String {
    var sectionAccent: Color {
        switch self {
        case "chief_complaint", "hpi", "imaging_review", "investigations", "vital_signs":
            return .aurionSectionInfo
        case "physical_exam", "wound_assessment", "functional_assessment":
            return .aurionSectionExam
        case "assessment":
            return .aurionSectionAssessment
        case "plan", "disposition":
            return .aurionSectionPlan
        default:
            return .aurionTextSecondary
        }
    }
}

// MARK: - Note Review (pixel-perfect port of screens.jsx → NoteReviewScreen)

struct NoteReviewView: View {
    let sessionId: String
    var initialNote: NoteResponse?
    @StateObject private var wsClient: WebSocketClient
    @State private var note: NoteResponse?
    @State private var activeSectionId: String?
    // Edit mode state. When isEditing is true, the section detail swaps each
    // section's first claim for a TextEditor bound to draftEdits[section.id].
    // Saving submits the whole map to PATCH /notes/{id}/edit, which produces
    // a new immutable note version on the server.
    @State private var isEditing = false
    @State private var draftEdits: [String: String] = [:]
    @State private var isSavingEdits = false

    init(sessionId: String, initialNote: NoteResponse? = nil) {
        self.sessionId = sessionId
        self.initialNote = initialNote
        _wsClient = StateObject(wrappedValue: WebSocketClient(sessionId: sessionId))
    }

    private var note_unsafe: NoteResponse? { note }

    private var activeSection: NoteSectionResponse? {
        guard let n = note else { return nil }
        if let id = activeSectionId, let s = n.sections.first(where: { $0.id == id }) {
            return s
        }
        return n.sections.first { $0.hasConflicts } ?? n.sections.first
    }

    var body: some View {
        VStack(spacing: 0) {
            AurionNavBar(title: "Review Note") {
                AurionTextButton(label: "Back") {}
            } trailing: {
                AurionTextButton(label: isEditing ? "Cancel" : "Edit") {
                    if isEditing {
                        draftEdits.removeAll()
                    } else if let n = note {
                        // Seed drafts from the current note's first-claim text
                        // so the editor opens pre-populated.
                        draftEdits = Dictionary(uniqueKeysWithValues: n.sections.compactMap { s in
                            s.claims.first(where: { !$0.isConflict }).map { (s.id, $0.text) }
                        })
                    }
                    isEditing.toggle()
                }
            }

            if let n = note {
                ScrollView {
                    VStack(spacing: 0) {
                        sectionList(n)
                        if let s = activeSection {
                            sectionDetail(s)
                        }
                    }
                }
                if isEditing {
                    editingBar(n)
                } else {
                    approvalBar(n)
                }
            } else {
                Spacer()
                ProgressView("Loading note…")
                Spacer()
            }
        }
        .background(Color.aurionBackground)
        .onAppear { loadNote() }
        .onChange(of: wsClient.latestNote) { _, newNote in
            if let newNote { note = newNote }
        }
    }

    // MARK: - Section list (4 stacked rows with colored left bars)

    private func sectionList(_ note: NoteResponse) -> some View {
        VStack(spacing: 8) {
            ForEach(note.sections, id: \.id) { s in
                Button {
                    AurionHaptics.selection()
                    activeSectionId = s.id
                } label: {
                    HStack(spacing: 0) {
                        // 3pt accent bar
                        Rectangle()
                            .fill(s.id.sectionAccent)
                            .frame(width: 3)

                        VStack(alignment: .leading, spacing: 2) {
                            Text(s.title)
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundColor(.aurionNavy)
                            Text(claimSummary(for: s))
                                .font(.system(size: 12))
                                .foregroundColor(.aurionTextSecondary)
                        }
                        .padding(.leading, 12)

                        Spacer()

                        AurionStatusPill(kind: kindFor(s), labelOverride: pillLabel(for: s))
                    }
                    .padding(.vertical, 10)
                    .padding(.trailing, 12)
                    .background(Color.aurionCardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
                    .overlay(
                        RoundedRectangle(cornerRadius: AurionRadius.sm)
                            .stroke(Color.aurionBorder, lineWidth: 1)
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: AurionRadius.sm)
                            .stroke(activeSection?.id == s.id ? Color.aurionGold : .clear, lineWidth: 2)
                            .padding(-1)
                    )
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.horizontal, AurionSpacing.edgeIPhone)
        .padding(.top, 4)
        .padding(.bottom, 12)
    }

    private func claimSummary(for s: NoteSectionResponse) -> String {
        let total = s.claims.count
        let valid = s.claims.filter { !$0.isConflict }.count
        if s.conflictCount > 0 {
            return "\(valid)/\(total) claims · \(s.conflictCount) conflict"
        }
        if total == 0 { return "Empty" }
        return "\(total) claims · clean"
    }

    private func kindFor(_ s: NoteSectionResponse) -> AurionStatusKind {
        if s.hasConflicts { return .conflict }
        switch s.status {
        case "populated": return .done
        case "processing_failed": return .archived
        default: return .pending
        }
    }

    private func pillLabel(for s: NoteSectionResponse) -> String? {
        if s.hasConflicts { return "Review" }
        switch s.status {
        case "populated": return "Done"
        case "pending_video", "pending": return "Pending"
        case "processing_failed": return "Failed"
        default: return nil
        }
    }

    // MARK: - Section detail (conflict card + claim cards)

    private func sectionDetail(_ s: NoteSectionResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(s.title).aurionTitle3().padding(.top, 8)

            if s.hasConflicts {
                conflictCard(s)
            }

            if isEditing {
                sectionEditor(s)
            } else {
                ForEach(s.claims.filter { !$0.isConflict }, id: \.id) { claim in
                    claimCard(claim)
                }
            }
        }
        .padding(.horizontal, AurionSpacing.edgeIPhone)
        .padding(.bottom, 16)
    }

    private func sectionEditor(_ s: NoteSectionResponse) -> some View {
        AurionCard(padding: 14) {
            VStack(alignment: .leading, spacing: 8) {
                Text("EDIT")
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(0.66)
                    .foregroundColor(.aurionTextSecondary)
                TextEditor(text: Binding(
                    get: { draftEdits[s.id] ?? "" },
                    set: { draftEdits[s.id] = $0 }
                ))
                .font(.system(size: 14))
                .foregroundColor(.aurionNavy)
                .frame(minHeight: 120)
                .padding(8)
                .background(Color.aurionBackground)
                .clipShape(RoundedRectangle(cornerRadius: AurionRadius.xs))
            }
        }
    }

    private func conflictCard(_ s: NoteSectionResponse) -> some View {
        let detail = s.claims.first(where: { $0.isConflict })?.text ?? "Conflict detected — confirm before approval."
        return VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "exclamationmark.circle")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(.aurionAmber)
                VStack(alignment: .leading, spacing: 4) {
                    Text("CONFLICT")
                        .font(.system(size: 11, weight: .semibold))
                        .tracking(0.66)
                        .foregroundColor(.aurionStatusConflict)
                    Text(detail)
                        .font(.system(size: 14))
                        .foregroundColor(.aurionNavy)
                        .lineSpacing(3)
                    HStack(spacing: 8) {
                        conflictPill("Right")
                        conflictPill("Left")
                    }
                    .padding(.top, 4)
                }
            }
        }
        .padding(14)
        .background(Color.aurionAmberBg)
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .stroke(Color.aurionAmber.opacity(0.30), lineWidth: 1)
        )
    }

    private func conflictPill(_ label: String) -> some View {
        Button { AurionHaptics.selection() } label: {
            Text(label)
                .font(.system(size: 13, weight: .semibold))
                .foregroundColor(.aurionNavy)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(Color.aurionCardBackground)
                .clipShape(Capsule())
                .overlay(Capsule().stroke(Color.aurionNavy.opacity(0.18), lineWidth: 1))
        }
        .buttonStyle(.plain)
    }

    private func claimCard(_ claim: NoteClaimResponse) -> some View {
        AurionCard(padding: 14) {
            VStack(alignment: .leading, spacing: 8) {
                Text(claim.text)
                    .font(.system(size: 14))
                    .foregroundColor(.aurionNavy)
                    .lineSpacing(3)

                if !claim.sourceQuote.isEmpty {
                    HStack(spacing: 0) {
                        Rectangle().fill(Color.aurionGold).frame(width: 2)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("SOURCE · \(claim.sourceId)")
                                .font(.system(size: 11, weight: .semibold))
                                .tracking(0.66)
                                .foregroundColor(.aurionTextSecondary)
                            Text("\u{201C}\(claim.sourceQuote)\u{201D}")
                                .font(.system(size: 13).italic())
                                .foregroundColor(.aurionTextSecondary)
                        }
                        .padding(.leading, 8)
                    }
                    .padding(8)
                    .background(Color.aurionBackground)
                    .clipShape(RoundedRectangle(cornerRadius: AurionRadius.xs))
                }
            }
        }
    }

    // MARK: - Editing bar (shown instead of approvalBar while isEditing)

    private func editingBar(_ n: NoteResponse) -> some View {
        HStack(spacing: 14) {
            Text("\(draftEdits.count) section\(draftEdits.count == 1 ? "" : "s") edited")
                .font(.system(size: 13))
                .foregroundColor(.aurionTextSecondary)
                .frame(maxWidth: .infinity, alignment: .leading)
            AurionGoldButton(
                label: isSavingEdits ? "Saving…" : "Save",
                size: .sm,
                disabled: isSavingEdits || draftEdits.isEmpty
            ) {
                saveEdits()
            }
        }
        .padding(.horizontal, AurionSpacing.edgeIPhone)
        .padding(.vertical, 14)
        .background(
            VStack(spacing: 0) {
                Rectangle().fill(Color.aurionBorder).frame(height: 1)
                Color.aurionCardBackground
            }
        )
    }

    // MARK: - Approval bar (always-visible bottom bar)

    private func approvalBar(_ n: NoteResponse) -> some View {
        let done = n.completenessScore
        let conflicts = n.sections.filter { $0.hasConflicts }.count
        let blocked = conflicts > 0
        let helpText: String = blocked
            ? "\(conflicts) conflict\(conflicts == 1 ? "" : "s") must resolve before approval."
            : "Ready to sign and export."

        return HStack(spacing: 14) {
            ZStack {
                CircularProgressRing(
                    progress: done,
                    color: blocked ? .aurionAmber : .aurionGreen,
                    lineWidth: 4,
                    size: 48
                )
                Text("\(Int(done * 100))%")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(.aurionNavy)
            }
            Text(helpText)
                .font(.system(size: 13))
                .foregroundColor(.aurionTextSecondary)
                .lineSpacing(3)
                .frame(maxWidth: .infinity, alignment: .leading)
            AurionGoldButton(label: "Approve & Sign", size: .sm, disabled: blocked) {
                approveNote()
            }
        }
        .padding(.horizontal, AurionSpacing.edgeIPhone)
        .padding(.vertical, 14)
        .background(
            VStack(spacing: 0) {
                Rectangle().fill(Color.aurionBorder).frame(height: 1)
                Color.aurionCardBackground
            }
        )
    }

    // MARK: - Data

    private func loadNote() {
        if let initialNote {
            note = initialNote
            return
        }
        wsClient.connect()
        Task {
            note = try? await APIClient.shared.getFullNote(sessionId: sessionId)
        }
    }

    private func approveNote() {
        AurionHaptics.notification(.success)
        Task {
            _ = try? await APIClient.shared.approveFinalNote(sessionId: sessionId)
            AuditLogger.log(event: .noteApproved, sessionId: sessionId)
        }
    }

    private func saveEdits() {
        // Submit only sections whose draft text differs from the current
        // first-claim text. Backend creates one new note version per call.
        guard let n = note else { return }
        let changed = draftEdits.filter { sectionId, draftText in
            let current = n.sections.first(where: { $0.id == sectionId })?
                .claims.first(where: { !$0.isConflict })?.text ?? ""
            return current != draftText
        }
        guard !changed.isEmpty else {
            isEditing = false
            draftEdits.removeAll()
            return
        }

        isSavingEdits = true
        Task {
            defer { Task { @MainActor in isSavingEdits = false } }
            do {
                let updated = try await APIClient.shared.editNote(
                    sessionId: sessionId,
                    edits: changed
                )
                await MainActor.run {
                    note = updated
                    draftEdits.removeAll()
                    isEditing = false
                    AurionHaptics.notification(.success)
                }
            } catch {
                await MainActor.run {
                    // Stay in edit mode so the user can retry; surface the
                    // error via haptic — full error UI is handled elsewhere.
                    AurionHaptics.notification(.error)
                }
            }
        }
    }
}
