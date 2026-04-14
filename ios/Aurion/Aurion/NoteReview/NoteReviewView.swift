import SwiftUI

// MARK: - Conflict Detection

private extension NoteClaimResponse {
    var isConflict: Bool { id.hasPrefix("conflict_") }
}

private extension NoteSectionResponse {
    var hasConflicts: Bool { claims.contains { $0.isConflict } }
}

private extension NoteResponse {
    var hasUnresolvedConflicts: Bool { sections.contains { $0.hasConflicts } }
}

// MARK: - Section Styling (shared with SessionNoteView)

private extension String {
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

// MARK: - Note Review

struct NoteReviewView: View {
    let sessionId: String
    var initialNote: NoteResponse?
    @StateObject private var wsClient: WebSocketClient
    @State private var note: NoteResponse?
    @State private var selectedSection: NoteSectionResponse?
    @State private var hasUnresolvedConflicts = false
    @State private var showApprovalSheet = false
    @Environment(\.horizontalSizeClass) var sizeClass

    init(sessionId: String, initialNote: NoteResponse? = nil) {
        self.sessionId = sessionId
        self.initialNote = initialNote
        _wsClient = StateObject(wrappedValue: WebSocketClient(sessionId: sessionId))
    }

    var body: some View {
        ZStack(alignment: .bottom) {
            Group {
                if sizeClass == .regular {
                    // iPad: two-column split view
                    NavigationSplitView {
                        sectionList
                    } detail: {
                        if let section = selectedSection {
                            SectionDetailView(section: section)
                        } else {
                            EmptyStateView(
                                icon: "hand.tap",
                                title: "Select a section",
                                subtitle: "Tap a section on the left to review its content."
                            )
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

            // Custom approval bottom sheet
            if showApprovalSheet, let note {
                approvalSheet(note: note)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }
        }
        .animation(AurionAnimation.spring, value: showApprovalSheet)
        .onAppear { loadNote() }
        .onChange(of: wsClient.latestNote) { _, newNote in
            if let newNote {
                note = newNote
                checkConflicts()
            }
        }
    }

    // MARK: - Section List

    private var sectionList: some View {
        List {
            if let note {
                // Completeness header
                Section {
                    HStack(spacing: AurionSpacing.lg) {
                        ZStack {
                            CircularProgressRing(
                                progress: note.completenessScore,
                                color: note.completenessScore >= 0.9 ? .clinicalNormal : .clinicalWarning
                            )
                            Text("\(Int(note.completenessScore * 100))%")
                                .font(.system(size: 12, weight: .bold, design: .rounded))
                                .monospacedDigit()
                                .foregroundColor(.aurionTextPrimary)
                        }

                        VStack(alignment: .leading, spacing: AurionSpacing.xxs) {
                            Text("Completeness")
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundColor(.aurionTextPrimary)
                            Text(note.completenessScore >= 0.9 ? "Meets target" : "Below 90% target")
                                .font(.system(size: 12, weight: .medium))
                                .foregroundColor(note.completenessScore >= 0.9 ? .clinicalNormal : .clinicalWarning)
                        }

                        Spacer()
                    }
                    .padding(.vertical, AurionSpacing.xxs)
                }

                // Section cards with colored left borders
                Section {
                    SectionHeader("Note Sections", count: note.sections.count)
                        .listRowBackground(Color.clear)
                        .listRowInsets(EdgeInsets(top: 0, leading: AurionSpacing.lg, bottom: 0, trailing: AurionSpacing.lg))

                    ForEach(note.sections, id: \.id) { section in
                        ReviewSectionCardView(section: section)
                            .onTapGesture {
                                AurionHaptics.selection()
                                selectedSection = section
                            }
                    }
                }

                // Approval button
                Section {
                    if hasUnresolvedConflicts {
                        HStack(spacing: AurionSpacing.sm) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundColor(.clinicalWarning)
                            Text("Resolve all conflicts before approving")
                                .font(.system(size: 14, weight: .medium))
                                .foregroundColor(.clinicalWarning)
                        }
                        .padding(.vertical, AurionSpacing.xxs)
                    }

                    Button {
                        AurionHaptics.impact(.medium)
                        showApprovalSheet = true
                    } label: {
                        HStack {
                            Spacer()
                            Text("Review & Approve")
                                .font(.system(size: 16, weight: .bold))
                            Spacer()
                        }
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
                        .aurionCaption()
                }
            }
        }
    }

    // MARK: - Approval Bottom Sheet

    private func approvalSheet(note: NoteResponse) -> some View {
        let populatedCount = note.sections.filter { !$0.claims.isEmpty }.count
        let totalCount = note.sections.count
        let conflictCount = note.sections.filter { $0.hasConflicts }.count

        return VStack(spacing: 0) {
            // Drag handle
            RoundedRectangle(cornerRadius: 2.5)
                .fill(Color.secondary.opacity(0.3))
                .frame(width: 36, height: 5)
                .padding(.top, AurionSpacing.sm)
                .padding(.bottom, AurionSpacing.lg)

            // Title
            Text("Approve Clinical Note")
                .aurionTitle()
                .padding(.bottom, AurionSpacing.lg)

            // Summary metrics row
            HStack(spacing: AurionSpacing.xl) {
                // Completeness ring
                VStack(spacing: AurionSpacing.xs) {
                    ZStack {
                        CircularProgressRing(
                            progress: note.completenessScore,
                            color: note.completenessScore >= 0.9 ? .clinicalNormal : .clinicalWarning,
                            lineWidth: 4,
                            size: 48
                        )
                        Text("\(Int(note.completenessScore * 100))%")
                            .font(.system(size: 11, weight: .bold, design: .rounded))
                            .foregroundColor(.aurionTextPrimary)
                    }
                    Text("Complete")
                        .aurionMicro()
                }

                // Sections count
                VStack(spacing: AurionSpacing.xs) {
                    Text("\(populatedCount)/\(totalCount)")
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .foregroundColor(.aurionTextPrimary)
                    Text("Sections")
                        .aurionMicro()
                }

                // Conflicts
                VStack(spacing: AurionSpacing.xs) {
                    Text("\(conflictCount)")
                        .font(.system(size: 22, weight: .bold, design: .rounded))
                        .foregroundColor(conflictCount > 0 ? .clinicalWarning : .clinicalNormal)
                    Text("Conflicts")
                        .aurionMicro()
                }
            }
            .padding(.bottom, AurionSpacing.xxl)

            // Approve button -- full width gold
            Button {
                approveNote()
                showApprovalSheet = false
            } label: {
                HStack {
                    Image(systemName: "checkmark.seal.fill")
                    Text("Approve & Sign")
                        .fontWeight(.bold)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, AurionSpacing.lg)
            }
            .font(.system(size: 16, weight: .bold))
            .foregroundColor(.white)
            .background(Color.aurionGold)
            .cornerRadius(AurionSpacing.sm)
            .shadow(color: Color.aurionGold.opacity(0.3), radius: 8, y: 4)
            .padding(.horizontal, AurionSpacing.xxl)
            .disabled(hasUnresolvedConflicts)

            // Continue editing button
            Button {
                showApprovalSheet = false
            } label: {
                Text("Continue Editing")
                    .font(.system(size: 15, weight: .medium))
                    .foregroundColor(.aurionTextPrimary)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, AurionSpacing.sm)
            }
            .padding(.horizontal, AurionSpacing.xxl)
            .padding(.top, AurionSpacing.sm)
            .padding(.bottom, AurionSpacing.xxl)
        }
        .background(
            Color.aurionCardBackground
                .cornerRadius(AurionSpacing.xl, corners: [.topLeft, .topRight])
                .shadow(color: .black.opacity(0.15), radius: 20, y: -8)
                .ignoresSafeArea(edges: .bottom)
        )
    }

    // MARK: - Actions

    private func loadNote() {
        if let initialNote {
            note = initialNote
            checkConflicts()
            return
        }
        wsClient.connect()
        Task {
            note = try? await APIClient.shared.getFullNote(sessionId: sessionId)
            checkConflicts()
        }
    }

    private func checkConflicts() {
        guard let note else { return }
        hasUnresolvedConflicts = note.hasUnresolvedConflicts
    }

    private func approveNote() {
        AurionHaptics.notification(.success)
        Task {
            _ = try? await APIClient.shared.approveFinalNote(sessionId: sessionId)
            AuditLogger.log(event: .noteApproved, sessionId: sessionId)
        }
    }
}

// MARK: - Corner Radius Helper

private extension View {
    func cornerRadius(_ radius: CGFloat, corners: UIRectCorner) -> some View {
        clipShape(RoundedCorner(radius: radius, corners: corners))
    }
}

private struct RoundedCorner: Shape {
    var radius: CGFloat
    var corners: UIRectCorner

    func path(in rect: CGRect) -> Path {
        let path = UIBezierPath(
            roundedRect: rect,
            byRoundingCorners: corners,
            cornerRadii: CGSize(width: radius, height: radius)
        )
        return Path(path.cgPath)
    }
}

// MARK: - Review Section Card (with colored left border)

struct ReviewSectionCardView: View {
    let section: NoteSectionResponse

    var body: some View {
        let borderColor = section.id.sectionBorderColor
        let icon = section.id.sectionIcon

        HStack(spacing: 0) {
            // Colored left bar
            RoundedRectangle(cornerRadius: 2)
                .fill(borderColor)
                .frame(width: 4)
                .padding(.vertical, AurionSpacing.xxs)

            VStack(alignment: .leading, spacing: AurionSpacing.xs) {
                HStack(spacing: AurionSpacing.sm) {
                    Image(systemName: icon)
                        .font(.system(size: 13, weight: .semibold))
                        .foregroundColor(borderColor)

                    Text(section.title)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundColor(.aurionTextPrimary)

                    Spacer()

                    reviewStatusBadge(section)
                }

                if !section.claims.isEmpty {
                    Text("\(section.claims.count) claim\(section.claims.count == 1 ? "" : "s")")
                        .aurionCaption()
                }
            }
            .padding(.leading, AurionSpacing.sm)
        }
        .padding(.vertical, AurionSpacing.xxs)
        .listRowBackground(section.hasConflicts ? Color.clinicalWarning.opacity(0.08) : Color.clear)
    }

    private func reviewStatusBadge(_ section: NoteSectionResponse) -> some View {
        Group {
            if section.hasConflicts {
                StatusBadge(text: "Conflict", color: .clinicalWarning)
            } else {
                switch section.status {
                case "populated":
                    StatusBadge(text: "Complete", color: .clinicalNormal)
                case "pending_video":
                    StatusBadge(text: "Pending", color: .clinicalInfo)
                case "processing_failed":
                    StatusBadge(text: "Failed", color: .clinicalAlert)
                default:
                    StatusBadge(text: "Empty", color: .secondary)
                }
            }
        }
    }
}

// MARK: - Section Detail

struct SectionDetailView: View {
    let section: NoteSectionResponse

    var body: some View {
        let borderColor = section.id.sectionBorderColor
        let icon = section.id.sectionIcon

        ScrollView {
            VStack(alignment: .leading, spacing: AurionSpacing.lg) {
                // Section title with icon
                HStack(spacing: AurionSpacing.sm) {
                    Image(systemName: icon)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundColor(borderColor)
                    Text(section.title)
                        .font(.system(size: 22, weight: .bold))
                        .foregroundColor(.aurionTextPrimary)
                }

                ForEach(section.claims, id: \.id) { claim in
                    ClaimView(claim: claim)
                }

                if section.claims.isEmpty {
                    EmptyStateView(
                        icon: "doc.text",
                        title: "No content captured",
                        subtitle: "This section was not populated during the encounter."
                    )
                    .frame(maxWidth: .infinity)
                    .padding(.top, AurionSpacing.xxl)
                }
            }
            .padding(AurionSpacing.xl)
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

    private var isVisual: Bool { claim.sourceType == "visual" }

    var body: some View {
        VStack(alignment: .leading, spacing: AurionSpacing.xs) {
            if isEditing {
                // Edit mode
                TextEditor(text: $editText)
                    .aurionBody()
                    .frame(minHeight: 60)
                    .padding(AurionSpacing.sm)
                    .background(Color.aurionFieldBackground)
                    .cornerRadius(AurionSpacing.sm)
                    .overlay(
                        RoundedRectangle(cornerRadius: AurionSpacing.sm)
                            .stroke(Color.aurionGold, lineWidth: 2)
                    )

                HStack(spacing: AurionSpacing.lg) {
                    Button("Save") {
                        AurionHaptics.impact(.light)
                        onEdit?(editText)
                        withAnimation(AurionAnimation.spring) {
                            isEditing = false
                        }
                    }
                    .font(.system(size: 13, weight: .bold))
                    .foregroundColor(.aurionGold)

                    Button("Cancel") {
                        withAnimation(AurionAnimation.spring) {
                            editText = claim.text
                            isEditing = false
                        }
                    }
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(.secondary)

                    Spacer()
                }
            } else {
                // Display mode
                Text(claim.text)
                    .aurionBody()
                    .foregroundColor(claim.isConflict ? Color.clinicalWarning : .aurionTextPrimary)
                    .fontWeight(claim.isConflict ? .semibold : .regular)
                    .onTapGesture(count: 2) {
                        editText = claim.text
                        withAnimation(AurionAnimation.spring) {
                            isEditing = true
                        }
                        AurionHaptics.selection()
                    }
            }

            HStack(spacing: AurionSpacing.xxs) {
                Image(systemName: isVisual ? "eye.circle" : "waveform")
                    .font(.system(size: 10))
                Text("[\(claim.sourceId)]")
                    .font(.system(size: 10))
                Text(claim.sourceType)
                    .font(.system(size: 10))
                    .foregroundColor(.secondary)

                Spacer()

                if !isEditing && onEdit != nil {
                    Image(systemName: "pencil")
                        .font(.system(size: 11))
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
                    .aurionCaption()
                    .padding(.leading, AurionSpacing.sm)
                    .italic()
                    .transition(AurionTransition.fadeUp)
            }
        }
        .padding(.vertical, AurionSpacing.xxs)
        .padding(.horizontal, AurionSpacing.sm)
        .background(claim.isConflict ? Color.clinicalWarning.opacity(0.05) : Color.clear)
        .cornerRadius(AurionSpacing.sm)
    }
}
