import SwiftUI

/// Note review UI -- adaptive layout for iPhone and iPad.
/// iPhone: single column section cards. iPad: two-column split view.
/// CONFLICTS flagged amber -- mandatory resolution before approval.
struct NoteReviewView: View {
    let sessionId: String
    var initialNote: NoteResponse?
    @StateObject private var wsClient: WebSocketClient
    @State private var note: NoteResponse?
    @State private var selectedSection: NoteSectionResponse?
    @State private var hasUnresolvedConflicts = false
    @State private var showApprovalConfirmation = false
    @Environment(\.horizontalSizeClass) var sizeClass

    init(sessionId: String, initialNote: NoteResponse? = nil) {
        self.sessionId = sessionId
        self.initialNote = initialNote
        _wsClient = StateObject(wrappedValue: WebSocketClient(sessionId: sessionId))
    }

    var body: some View {
        Group {
            if sizeClass == .regular {
                // iPad: two-column split view
                NavigationSplitView {
                    sectionList
                } detail: {
                    if let section = selectedSection {
                        SectionDetailView(section: section)
                    } else {
                        Text("Select a section")
                            .foregroundColor(.secondary)
                    }
                }
                .aurionNavBar()
            } else {
                // iPhone: single column
                NavigationStack {
                    sectionList
                }
                .aurionNavBar()
            }
        }
        .onAppear { loadNote() }
        .onChange(of: wsClient.latestNote) { _, newNote in
            if let newNote {
                note = newNote
                checkConflicts()
            }
        }
        .alert("Approve Note", isPresented: $showApprovalConfirmation) {
            Button("Approve", role: .destructive) { approveNote() }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will finalize the note. Are you sure?")
        }
    }

    // MARK: - Section List

    private var sectionList: some View {
        List {
            if let note {
                // Completeness score with progress ring
                HStack(spacing: 16) {
                    ZStack {
                        CircularProgressRing(
                            progress: note.completenessScore,
                            color: note.completenessScore >= 0.9 ? .green : .aurionAmber
                        )
                        Text("\(Int(note.completenessScore * 100))%")
                            .font(.caption)
                            .fontWeight(.bold)
                            .monospacedDigit()
                            .foregroundColor(.aurionTextPrimary)
                    }

                    VStack(alignment: .leading, spacing: 2) {
                        Text("Completeness")
                            .font(.headline)
                            .foregroundColor(.aurionTextPrimary)
                        Text(note.completenessScore >= 0.9 ? "Meets target" : "Below 90% target")
                            .font(.caption)
                            .foregroundColor(note.completenessScore >= 0.9 ? .green : .aurionAmber)
                    }

                    Spacer()
                }
                .padding(.vertical, 4)

                // Section cards
                ForEach(note.sections, id: \.id) { section in
                    SectionCardView(section: section)
                        .onTapGesture {
                            AurionHaptics.selection()
                            selectedSection = section
                        }
                }

                // Approval button
                Section {
                    if hasUnresolvedConflicts {
                        Label("Resolve all conflicts before approving", systemImage: "exclamationmark.triangle.fill")
                            .foregroundColor(Color.aurionAmber)
                    }

                    Button("Approve Note") {
                        showApprovalConfirmation = true
                    }
                    .buttonStyle(AurionPrimaryButtonStyle())
                    .disabled(hasUnresolvedConflicts)
                    .opacity(hasUnresolvedConflicts ? 0.5 : 1.0)
                }
            } else {
                ProgressView("Loading note...")
            }
        }
        .navigationTitle("Review Note")
        .toolbar {
            ToolbarItem(placement: .navigationBarTrailing) {
                if let note {
                    Text("Stage \(note.stage) v\(note.version)")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            }
        }
    }

    // MARK: - Actions

    private func loadNote() {
        // Use the note passed in from SessionManager if available
        if let initialNote {
            note = initialNote
            checkConflicts()
            return
        }
        // Otherwise fetch from backend
        wsClient.connect()
        Task {
            note = try? await APIClient.shared.getFullNote(sessionId: sessionId)
            checkConflicts()
        }
    }

    private func checkConflicts() {
        guard let note else { return }
        hasUnresolvedConflicts = note.sections.contains { section in
            section.claims.contains { $0.text.contains("CONFLICT") }
        }
    }

    private func approveNote() {
        AurionHaptics.notification(.success)
        Task {
            _ = try? await APIClient.shared.approveFinalNote(sessionId: sessionId)
            AuditLogger.log(event: .noteApproved, sessionId: sessionId)
        }
    }
}

// MARK: - Section Card

struct SectionCardView: View {
    let section: NoteSectionResponse

    private var isConflict: Bool {
        section.claims.contains { $0.text.contains("CONFLICT") }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text(section.title)
                    .font(.headline)
                    .foregroundColor(.aurionTextPrimary)
                Spacer()
                statusBadge
            }

            if !section.claims.isEmpty {
                Text("\(section.claims.count) claim\(section.claims.count == 1 ? "" : "s")")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
        .listRowBackground(isConflict ? Color.aurionAmber.opacity(0.1) : Color.clear)
    }

    private var statusBadge: some View {
        Group {
            switch section.status {
            case "populated":
                Label("Complete", systemImage: "checkmark.circle.fill")
                    .font(.caption2)
                    .foregroundColor(.green)
            case "pending_video":
                Label("Pending Video", systemImage: "video.circle")
                    .font(.caption2)
                    .foregroundColor(.blue)
            case "processing_failed":
                Label("Failed", systemImage: "exclamationmark.circle")
                    .font(.caption2)
                    .foregroundColor(.red)
            default:
                Label("Empty", systemImage: "circle.dashed")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
    }
}

// MARK: - Section Detail

struct SectionDetailView: View {
    let section: NoteSectionResponse

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text(section.title)
                    .font(.title2)
                    .fontWeight(.bold)
                    .foregroundColor(.aurionTextPrimary)

                ForEach(section.claims, id: \.id) { claim in
                    ClaimView(claim: claim)
                }

                if section.claims.isEmpty {
                    Text("No content captured for this section.")
                        .font(.body)
                        .foregroundColor(.secondary)
                        .italic()
                }
            }
            .padding()
        }
        .navigationTitle(section.title)
    }
}

// MARK: - Claim View (tap-to-source)

struct ClaimView: View {
    let claim: NoteClaimResponse
    var onEdit: ((String) -> Void)?
    @State private var showSource = false
    @State private var isEditing = false
    @State private var editText: String = ""

    private var isConflict: Bool { claim.text.contains("CONFLICT") }
    private var isVisual: Bool { claim.sourceType == "visual" }

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if isEditing {
                // Edit mode
                TextEditor(text: $editText)
                    .font(.body)
                    .foregroundColor(.aurionTextPrimary)
                    .frame(minHeight: 60)
                    .padding(8)
                    .background(Color.aurionFieldBackground)
                    .cornerRadius(8)
                    .overlay(
                        RoundedRectangle(cornerRadius: 8)
                            .stroke(Color.aurionGold, lineWidth: 2)
                    )

                HStack {
                    Button("Save") {
                        AurionHaptics.impact(.light)
                        onEdit?(editText)
                        withAnimation(AurionAnimation.spring) {
                            isEditing = false
                        }
                    }
                    .font(.caption.bold())
                    .foregroundColor(.aurionGold)

                    Button("Cancel") {
                        withAnimation(AurionAnimation.spring) {
                            editText = claim.text
                            isEditing = false
                        }
                    }
                    .font(.caption)
                    .foregroundColor(.secondary)

                    Spacer()
                }
            } else {
                // Display mode
                Text(claim.text)
                    .aurionClaimText()
                    .foregroundColor(isConflict ? Color.aurionAmber : .aurionTextPrimary)
                    .fontWeight(isConflict ? .semibold : .regular)
                    .onTapGesture(count: 2) {
                        // Double-tap to edit
                        editText = claim.text
                        withAnimation(AurionAnimation.spring) {
                            isEditing = true
                        }
                        AurionHaptics.selection()
                    }
            }

            HStack(spacing: 4) {
                Image(systemName: isVisual ? "eye.circle" : "waveform")
                    .font(.caption2)
                Text("[\(claim.sourceId)]")
                    .font(.caption2)
                Text(claim.sourceType)
                    .font(.caption2)
                    .foregroundColor(.secondary)

                Spacer()

                if !isEditing && onEdit != nil {
                    Image(systemName: "pencil")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                        .onTapGesture {
                            editText = claim.text
                            withAnimation(AurionAnimation.spring) {
                                isEditing = true
                            }
                            AurionHaptics.selection()
                        }
                }
            }
            .foregroundColor(Color.aurionNavy.opacity(0.5))
            .onTapGesture {
                AurionHaptics.selection()
                withAnimation(AurionAnimation.spring) {
                    showSource.toggle()
                }
            }

            if showSource && !claim.sourceQuote.isEmpty {
                Text("Source: \"\(claim.sourceQuote)\"")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .padding(.leading, 12)
                    .italic()
                    .transition(AurionTransition.fadeUp)
            }
        }
        .padding(.vertical, 4)
        .padding(.horizontal, 12)
        .background(isConflict ? Color.aurionAmber.opacity(0.05) : Color.clear)
        .cornerRadius(8)
    }
}
