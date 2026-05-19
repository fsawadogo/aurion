import SwiftUI

// MARK: - Conflict / classification helpers

private extension NoteClaimResponse {
    /// Unresolved Stage 2 vision conflict. A physician edit (which flips
    /// `physicianEdited`) is the resolution signal — once edited, the
    /// claim no longer blocks approval.
    var isConflict: Bool { id.hasPrefix("conflict_") && !physicianEdited }

    /// One-letter badge per source — surfaces provenance in the SOURCES
    /// panel so the clinician knows at a glance whether a claim came from
    /// transcript (T), visual frame (V), screen capture (S), or a manual
    /// physician edit (E).
    var sourceBadge: String {
        switch sourceType {
        case "transcript": return "T"
        case "visual": return "V"
        case "screen": return "S"
        case "physician_edit": return "E"
        default: return "?"
        }
    }
}

private extension NoteSectionResponse {
    var hasConflicts: Bool { claims.contains { $0.isConflict } }
    var conflictCount: Int { claims.filter { $0.isConflict }.count }
}

private extension NoteResponse {
    var hasUnresolvedConflicts: Bool { sections.contains { $0.hasConflicts } }
    /// Total unresolved Stage 2 conflicts across all sections.
    var totalConflictCount: Int { sections.reduce(0) { $0 + $1.conflictCount } }
    /// Section id of the first conflict in document order. Used by the
    /// "Show" affordance on the conflicts banner to scroll to it.
    var firstConflictSectionID: String? {
        sections.first(where: { $0.hasConflicts })?.id
    }
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

/// Selection carrier for the conflict edit sheet. Bundling the claim id with
/// the seed text means the sheet always opens against the same claim it was
/// summoned for, even if the note refreshes mid-edit.
private struct ConflictEditTarget: Identifiable {
    let claimId: String
    var draft: String
    var id: String { claimId }
}

// MARK: - Note Review (pixel-perfect port of screens.jsx → NoteReviewScreen)

struct NoteReviewView: View {
    let sessionId: String
    var initialNote: NoteResponse?
    let onDismiss: () -> Void
    @StateObject private var wsClient: WebSocketClient
    @State private var note: NoteResponse?
    /// Which section's source panel is currently expanded inline. nil = none.
    /// Sections render as continuous prose (one paragraph per section); tapping
    /// the paragraph toggles the per-section citation list.
    @State private var expandedSectionId: String?
    // Edit mode state. In the full-prose layout we keep per-section editing
    // (one TextEditor per section in a sheet) so saving still produces one
    // PATCH /notes/{id}/edit per round trip — backend writes a single new
    // immutable note version on the server.
    @State private var isEditing = false
    @State private var draftEdits: [String: String] = [:]
    @State private var isSavingEdits = false
    @State private var isApproving = false
    @State private var approveError: String?
    @State private var showApprovedToast = false
    /// Claim id currently in flight to the conflict-resolution endpoint —
    /// disables the action row so a double-tap can't double-resolve.
    @State private var resolvingClaimId: String?
    /// Claim selected for inline edit. Driving the sheet off an Identifiable
    /// item value (vs. a bool) keeps the seed-text and target-claim atomic.
    @State private var conflictBeingEdited: ConflictEditTarget?
    /// Captured from ``ScrollViewReader`` so the conflicts banner's
    /// "Show" button can scroll to the first conflicting section.
    @State private var conflictsBannerScrollProxy: ScrollViewProxy?
    /// Latest Stage 2 job snapshot. Polled in the background while the
    /// async job runs so the banner reflects pending → running → completed.
    @State private var stage2Status: Stage2StatusResponse?
    /// Drives the ring + percent count-up on first reveal. Starts at 0 and
    /// springs to the note's actual completeness when the view appears (or
    /// the score changes mid-session as Stage 2 enrichment lands).
    @State private var displayedCompleteness: Double = 0
    /// Per-section reveal flag — flipped after a small delay on first paint
    /// so the section cards staircase in instead of all appearing at once.
    /// Restarts on note (re)load.
    @State private var sectionsRevealed = false

    init(sessionId: String, initialNote: NoteResponse? = nil, onDismiss: @escaping () -> Void = {}) {
        self.sessionId = sessionId
        self.initialNote = initialNote
        self.onDismiss = onDismiss
        _wsClient = StateObject(wrappedValue: WebSocketClient(sessionId: sessionId))
    }

    private var note_unsafe: NoteResponse? { note }

    var body: some View {
        VStack(spacing: 0) {
            AurionNavBar(title: "Review Note") {
                AurionTextButton(label: "Back") { onDismiss() }
            } trailing: {
                AurionTextButton(label: isEditing ? "Done" : "Edit") {
                    if isEditing {
                        draftEdits.removeAll()
                    } else if let n = note {
                        // Seed drafts with the full prose paragraph per section
                        // (all non-conflict claims joined). Matches what the
                        // physician sees in read mode.
                        draftEdits = Dictionary(uniqueKeysWithValues: n.sections.map { s in
                            (s.id, joinedProse(s))
                        })
                    }
                    isEditing.toggle()
                }
            }

            if let n = note {
                stage2Banner
                conflictsBanner(n)
                ScrollViewReader { proxy in
                    ScrollView {
                        if isEditing {
                            editableProseBody(n)
                        } else {
                            fullProseBody(n)
                        }
                    }
                    .onAppear { conflictsBannerScrollProxy = proxy }
                }
                if let approveError {
                    Text(approveError)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(.aurionRed)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: .infinity, alignment: .center)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(Color.aurionRed.opacity(0.08))
                        .transition(.opacity)
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
        .onAppear {
            loadNote()
            // Kick off the staircase + ring count-up on the next runloop so
            // the initial paint is `sectionsRevealed = false / displayed = 0`
            // and the springs have actual deltas to work with.
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                sectionsRevealed = true
                if let n = note {
                    withAnimation(.interpolatingSpring(stiffness: 100, damping: 18)) {
                        displayedCompleteness = requiredCompleteness(n)
                    }
                }
            }
        }
        .task(id: sessionId) {
            // Background poll for Stage 2 job status. Bails out as soon as
            // the job reaches a terminal state OR the view goes away — the
            // `.task(id:)` is auto-cancelled when sessionId or the view
            // disappears.
            await pollStage2Status()
        }
        .onChange(of: note?.sections.count) { _, _ in
            // If Stage 2 finishes mid-view (or a fresh note version lands
            // via WebSocket) the ring smoothly re-targets the new score
            // computed over required (non-optional) sections.
            guard let n = note else { return }
            withAnimation(.interpolatingSpring(stiffness: 100, damping: 18)) {
                displayedCompleteness = requiredCompleteness(n)
            }
        }
        .onChange(of: wsClient.latestNote) { _, newNote in
            if let newNote {
                note = newNote
                // Replay the staircase for the new section list — feels
                // intentional rather than a content swap mid-render.
                sectionsRevealed = false
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                    sectionsRevealed = true
                }
            }
        }
        .overlay(alignment: .center) {
            if showApprovedToast {
                approvedToast
                    .transition(.scale(scale: 0.85).combined(with: .opacity))
            }
        }
        .animation(AurionAnimation.smooth, value: showApprovedToast)
        .sheet(item: $conflictBeingEdited) { target in
            conflictEditSheet(target: target)
        }
    }

    /// Sheet used when the physician picks "Edit" on a conflict. Saves via
    /// the same resolve endpoint with `action="edit"` and the new text.
    private func conflictEditSheet(target: ConflictEditTarget) -> some View {
        // Local draft mirror so cancel doesn't mutate the carrier until save.
        let draftBinding = Binding<String>(
            get: { conflictBeingEdited?.draft ?? target.draft },
            set: { conflictBeingEdited?.draft = $0 }
        )
        return VStack(alignment: .leading, spacing: 16) {
            Text("Edit conflict")
                .font(.system(size: 20, weight: .bold))
                .foregroundColor(.aurionNavy)
            Text("Replace the conflicting claim. The original text is preserved in the audit log.")
                .font(.system(size: 13))
                .foregroundColor(.aurionTextSecondary)
            TextEditor(text: draftBinding)
                .font(.system(size: 15))
                .foregroundColor(.aurionNavy)
                .frame(minHeight: 140)
                .padding(8)
                .background(Color.aurionBackground)
                .clipShape(RoundedRectangle(cornerRadius: AurionRadius.xs))
                .overlay(
                    RoundedRectangle(cornerRadius: AurionRadius.xs)
                        .stroke(Color.aurionBorder, lineWidth: 1)
                )
            HStack(spacing: 12) {
                Button("Cancel") { conflictBeingEdited = nil }
                    .buttonStyle(.bordered)
                Spacer()
                Button("Save") {
                    let draft = conflictBeingEdited?.draft ?? target.draft
                    let trimmed = draft.trimmingCharacters(in: .whitespacesAndNewlines)
                    guard !trimmed.isEmpty,
                          let claim = note?.sections.flatMap({ $0.claims }).first(where: { $0.id == target.claimId })
                    else { return }
                    conflictBeingEdited = nil
                    Task { await resolveConflict(claim, action: .edit, text: trimmed) }
                }
                .buttonStyle(.borderedProminent)
                .disabled((conflictBeingEdited?.draft ?? target.draft).trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(24)
        .presentationDetents([.medium, .large])
    }

    /// Sticky banner at the top of the review surface that surfaces
    /// unresolved Stage 2 conflicts. Replaces the prior "scroll-and-find"
    /// burden: physician sees the count immediately and can tap "Show"
    /// to jump to the first conflict. The Approve button stays disabled
    /// while conflicts > 0, but the layout no longer forces linear
    /// resolution order — physicians often know what they want before
    /// reading.
    @ViewBuilder
    private func conflictsBanner(_ note: NoteResponse) -> some View {
        let count = note.totalConflictCount
        if count > 0 {
            HStack(spacing: 10) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.aurionAmber)
                    // Soft heartbeat on the warning glyph — keeps the
                    // unresolved-conflicts state visible at a glance
                    // without the noisy strobe that earlier prototypes
                    // had. Anchored on the count so a resolved conflict
                    // re-fires the effect for the remaining ones.
                    .symbolEffect(.pulse, options: .repeating, value: count)
                Text("\(count) conflict\(count == 1 ? "" : "s") to resolve")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundColor(.aurionStatusConflict)
                Spacer()
                if let firstID = note.firstConflictSectionID {
                    Button {
                        AurionHaptics.selection()
                        withAnimation(.aurionIOS) {
                            conflictsBannerScrollProxy?.scrollTo(firstID, anchor: .top)
                        }
                    } label: {
                        Text("Show")
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(.aurionStatusConflict)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(Color.aurionAmberBg.opacity(0.6))
                            .clipShape(Capsule())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Scroll to first conflict")
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color.aurionAmberBg)
            .overlay(alignment: .bottom) {
                Rectangle().fill(Color.aurionBorder).frame(height: 1)
            }
            .transition(.move(edge: .top).combined(with: .opacity))
        }
    }

    /// Strip across the top of the note when Stage 2 is still running.
    /// Hidden when the job hasn't started yet, completed, or failed
    /// (errors surface in `approveError` instead). Returns an EmptyView
    /// when there's nothing to show — `@ViewBuilder` + the implicit
    /// `if` handles that.
    @ViewBuilder
    private var stage2Banner: some View {
        if let status = stage2Status, status.isInProgress {
            HStack(spacing: 10) {
                ProgressView()
                    .controlSize(.small)
                Text("Visual enrichment in progress…")
                    .font(.system(size: 13, weight: .medium))
                    .foregroundColor(.aurionNavy)
                Spacer()
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(Color.aurionAmberBg.opacity(0.6))
        }
    }

    /// Poll the Stage 2 job until it reaches a terminal state. Polling
    /// stops automatically when the view disappears (`.task(id:)` is
    /// cancelled), so there's no manual teardown needed.
    private func pollStage2Status() async {
        // 2s while a job is actively running keeps the banner snappy;
        // 4s when idle (no job yet, or after a network blip) saves
        // battery while we're effectively waiting on the user.
        let activePollInterval: UInt64 = 2_000_000_000  // 2s
        let idlePollInterval: UInt64 = 4_000_000_000    // 4s

        while !Task.isCancelled {
            let status: Stage2StatusResponse
            do {
                status = try await APIClient.shared.getStage2Status(sessionId: sessionId)
            } catch {
                // Network blip — back off and retry. Stage 2 is best-effort
                // so we don't surface this to the UI.
                try? await Task.sleep(nanoseconds: idlePollInterval)
                continue
            }
            await MainActor.run { stage2Status = status }

            if status.isCompleted {
                // Refresh the note so any new conflict claims surface.
                loadNote()
                return
            }
            if status.isFailed {
                await MainActor.run {
                    approveError = "Stage 2 failed: \(status.errorMessage ?? "unknown error"). You can still approve the Stage 1 note."
                }
                return
            }
            let nextInterval = status.hasStarted ? activePollInterval : idlePollInterval
            try? await Task.sleep(nanoseconds: nextInterval)
        }
    }

    private var approvedToast: some View {
        VStack(spacing: 12) {
            AurionIconBubble(symbol: "checkmark", tint: .aurionGreen, size: 64, symbolWeight: .bold)
            Text("Note Approved")
                .font(.system(size: 16, weight: .semibold))
                .foregroundColor(.aurionNavy)
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 22)
        .background(Color.aurionCardBackground)
        .clipShape(RoundedRectangle(cornerRadius: 16))
        .shadow(color: .black.opacity(0.12), radius: 18, x: 0, y: 6)
    }

    // MARK: - Full-prose body (Word-doc-style, single scroll)

    /// Renders the note as one continuous prose document — bold section
    /// headings, each section body as a single flowing paragraph (all
    /// non-conflict claims joined). Tap a paragraph to reveal the per-section
    /// source citations. Conflicts surface inline below the paragraph.
    private func fullProseBody(_ note: NoteResponse) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            ForEach(Array(note.sections.enumerated()), id: \.element.id) { idx, section in
                proseSection(section, index: idx)
                    // Exposed to ScrollViewReader so the conflicts banner's
                    // "Show" button can scroll to the first conflicting section.
                    .id(section.id)
            }
            Spacer(minLength: 8)
        }
        // Cap prose width on big iPads — past ~720pt the line length
        // outpaces what a clinician can scan comfortably. iPhone is
        // always under the cap so this is a no-op there.
        .frame(maxWidth: 720, alignment: .leading)
        .frame(maxWidth: .infinity, alignment: .center)
        .aurionScreenEdge()
        .padding(.top, 16)
        .padding(.bottom, 24)
    }

    /// Joins all non-conflict claim texts for a section into one prose
    /// paragraph. Empty sections render an italic placeholder.
    private func joinedProse(_ s: NoteSectionResponse) -> String {
        s.claims
            .filter { !$0.isConflict }
            .map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
            .joined(separator: " ")
    }

    /// Completeness over required sections only. pending_video and pending
    /// are optional and excluded from both numerator and denominator so a
    /// Stage 1 note with imaging not shown can still read 100%.
    private func requiredCompleteness(_ n: NoteResponse) -> Double {
        let required = n.sections.filter { $0.status != "pending_video" && $0.status != "pending" }
        guard !required.isEmpty else { return 0 }
        let populated = required.filter { s in
            s.status == "populated" && s.claims.contains(where: { !$0.isConflict })
        }.count
        return Double(populated) / Double(required.count)
    }

    private func proseSection(_ s: NoteSectionResponse, index: Int) -> some View {
        let body = joinedProse(s)
        let isExpanded = expandedSectionId == s.id
        let sourceClaims = s.claims.filter { !$0.isConflict && !$0.sourceQuote.isEmpty }

        return VStack(alignment: .leading, spacing: 6) {
            // Section title — bold, similar to a Word heading
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Text(s.title)
                    .font(.system(size: 18, weight: .bold))
                    .foregroundColor(.aurionNavy)
                if s.hasConflicts {
                    Text("CONFLICT")
                        .font(.system(size: 10, weight: .bold))
                        .tracking(0.6)
                        .foregroundColor(.aurionStatusConflict)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.aurionAmberBg)
                        .clipShape(Capsule())
                } else if s.status == "pending_video" || s.status == "pending" {
                    // Soft "OPTIONAL" chip — pending_video sections never
                    // block approval; Stage 2 vision fills them only if
                    // imaging was actually reviewed during the encounter.
                    Text("OPTIONAL")
                        .font(.system(size: 10, weight: .bold))
                        .tracking(0.6)
                        .foregroundColor(.aurionTextSecondary)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.aurionSurfaceAlt)
                        .clipShape(Capsule())
                }
            }

            // Body — one continuous prose paragraph per section. Tap to
            // reveal the citation list under this section.
            if body.isEmpty {
                Text(s.status == "pending_video"
                     ? "Optional — fills only if imaging was shown during the encounter."
                     : "No content captured for this section.")
                    .font(.system(size: 14).italic())
                    .foregroundColor(.aurionTextSecondary)
            } else {
                Button {
                    guard !sourceClaims.isEmpty else { return }
                    AurionHaptics.selection()
                    withAnimation(AurionAnimation.smooth) {
                        expandedSectionId = isExpanded ? nil : s.id
                    }
                } label: {
                    Text(body)
                        .font(.system(size: 15))
                        .foregroundColor(.aurionNavy)
                        .lineSpacing(5)
                        .multilineTextAlignment(.leading)
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
                .buttonStyle(.plain)

                if isExpanded && !sourceClaims.isEmpty {
                    sourcesPanel(sourceClaims)
                        .transition(.opacity.combined(with: .move(edge: .top)))
                }
            }

            // Conflicts surfaced separately at the end of the section
            ForEach(s.claims.filter { $0.isConflict }, id: \.id) { conflict in
                inlineConflict(conflict)
            }
        }
        .opacity(sectionsRevealed ? 1 : 0)
        .offset(y: sectionsRevealed ? 0 : 10)
        .animation(
            .interpolatingSpring(stiffness: 220, damping: 24)
                .delay(Double(index) * 0.05),
            value: sectionsRevealed
        )
    }

    /// Collapsed source citation list shown under a section's prose paragraph.
    private func sourcesPanel(_ claims: [NoteClaimResponse]) -> some View {
        HStack(spacing: 0) {
            Rectangle().fill(Color.aurionGold).frame(width: 2)
            VStack(alignment: .leading, spacing: 10) {
                Text("SOURCES")
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(0.6)
                    .foregroundColor(.aurionTextSecondary)
                ForEach(claims, id: \.id) { claim in
                    VStack(alignment: .leading, spacing: 2) {
                        HStack(spacing: 6) {
                            Text(claim.sourceBadge)
                                .font(.system(size: 9, weight: .bold))
                                .foregroundColor(.aurionBackground)
                                .frame(width: 14, height: 14)
                                .background(Color.aurionTextSecondary)
                                .clipShape(RoundedRectangle(cornerRadius: 3))
                            Text(claim.sourceId)
                                .font(.system(size: 10, weight: .semibold))
                                .tracking(0.4)
                                .foregroundColor(.aurionTextSecondary)
                            if claim.physicianEdited {
                                Text("EDITED")
                                    .font(.system(size: 9, weight: .bold))
                                    .tracking(0.5)
                                    .foregroundColor(.aurionGold)
                            }
                        }
                        if !claim.sourceQuote.isEmpty {
                            Text("\u{201C}\(claim.sourceQuote)\u{201D}")
                                .font(.system(size: 13).italic())
                                .foregroundColor(.aurionTextSecondary)
                                .lineSpacing(2)
                        }
                    }
                }
            }
            .padding(.leading, 10)
        }
        .padding(.vertical, 10)
        .padding(.horizontal, 10)
        .background(Color.aurionBackground)
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.xs))
    }

    private func inlineConflict(_ claim: NoteClaimResponse) -> some View {
        let inFlight = resolvingClaimId == claim.id
        return VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 14))
                    .foregroundColor(.aurionAmber)
                    .padding(.top, 2)
                VStack(alignment: .leading, spacing: 4) {
                    Text("Visual vs audio conflict — resolve before approval.")
                        .font(.system(size: 11, weight: .semibold))
                        .tracking(0.4)
                        .foregroundColor(.aurionStatusConflict)
                    Text(claim.text)
                        .font(.system(size: 14))
                        .foregroundColor(.aurionNavy)
                        .lineSpacing(3)
                }
            }
            HStack(spacing: 8) {
                conflictActionButton("Accept visual", inFlight: inFlight) {
                    Task { await resolveConflict(claim, action: .acceptVisual) }
                }
                conflictActionButton("Reject visual", inFlight: inFlight) {
                    Task { await resolveConflict(claim, action: .rejectVisual) }
                }
                conflictActionButton("Edit", inFlight: inFlight) {
                    conflictBeingEdited = ConflictEditTarget(claimId: claim.id, draft: claim.text)
                }
            }
        }
        .padding(12)
        .background(Color.aurionAmberBg)
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
        .overlay(
            RoundedRectangle(cornerRadius: AurionRadius.sm)
                .stroke(Color.aurionAmber.opacity(0.35), lineWidth: 1)
        )
    }

    private func conflictActionButton(_ label: String, inFlight: Bool, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Text(label)
                .font(.system(size: 12, weight: .semibold))
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Color.aurionBackground)
                .foregroundColor(.aurionNavy)
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(
                    RoundedRectangle(cornerRadius: 6)
                        .stroke(Color.aurionBorder, lineWidth: 1)
                )
        }
        .disabled(inFlight)
        .opacity(inFlight ? 0.5 : 1)
    }

    /// Fire one resolution action and replace the local note with the new
    /// version the backend returns. On failure we surface the error inline
    /// and leave the conflict claim untouched so the clinician can retry.
    private func resolveConflict(_ claim: NoteClaimResponse, action: ConflictResolutionAction, text: String? = nil) async {
        resolvingClaimId = claim.id
        defer { resolvingClaimId = nil }
        do {
            let updated = try await APIClient.shared.resolveConflict(
                sessionId: sessionId,
                claimId: claim.id,
                action: action,
                resolutionText: text
            )
            note = updated
            AuditLogger.log(
                event: .conflictResolved,
                sessionId: sessionId,
                extra: ["claim_id": claim.id, "action": action.rawValue]
            )
        } catch {
            approveError = "Conflict resolution failed: \(error.localizedDescription)"
        }
    }

    // MARK: - Editable prose body — same layout, swap claim text for TextEditors

    private func editableProseBody(_ note: NoteResponse) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            ForEach(note.sections, id: \.id) { section in
                VStack(alignment: .leading, spacing: 8) {
                    Text(section.title)
                        .font(.system(size: 18, weight: .bold))
                        .foregroundColor(.aurionNavy)
                    TextEditor(text: Binding(
                        get: { draftEdits[section.id] ?? "" },
                        set: { draftEdits[section.id] = $0 }
                    ))
                    .font(.system(size: 15))
                    .foregroundColor(.aurionNavy)
                    .frame(minHeight: 90)
                    .padding(8)
                    .background(Color.aurionBackground)
                    .clipShape(RoundedRectangle(cornerRadius: AurionRadius.xs))
                    .overlay(
                        RoundedRectangle(cornerRadius: AurionRadius.xs)
                            .stroke(Color.aurionBorder, lineWidth: 1)
                    )
                }
            }
        }
        .aurionScreenEdge()
        .padding(.top, 16)
        .padding(.bottom, 24)
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
        .aurionScreenEdge()
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
        // pending_video sections are optional — Stage 2 fills them only if
        // imaging was actually reviewed. Exclude them from both numerator
        // and denominator so the ring / "X of Y" reflects required-only
        // sections and a Stage 1 note can read as 100% complete.
        let required = n.sections.filter { $0.status != "pending_video" && $0.status != "pending" }
        let populated = required.filter { s in
            s.status == "populated" && s.claims.contains(where: { !$0.isConflict })
        }.count
        let totalSections = required.count
        let conflicts = n.sections.filter { $0.hasConflicts }.count
        // Block approve while Stage 2 is still merging vision citations —
        // the backend returns 409 "still processing" if we hit /approve
        // before REVIEW_COMPLETE. The poller (`pollStage2Status`)
        // populates `stage2Status` so this gate reacts in ~2s when
        // Stage 2 finishes.
        let stage2Running = stage2Status?.isInProgress == true
        let blocked = conflicts > 0 || stage2Running
        let helpText: String
        if stage2Running {
            let frames = stage2Status?.framesProcessed ?? 0
            helpText = frames > 0
                ? "Finishing visual enrichment · \(frames) frame\(frames == 1 ? "" : "s") processed…"
                : "Finishing visual enrichment…"
        } else if conflicts > 0 {
            helpText = "\(conflicts) conflict\(conflicts == 1 ? "" : "s") must resolve before approval."
        } else {
            helpText = "Ready to sign and export."
        }
        let ringColor: Color = stage2Running ? .aurionGold
            : (conflicts > 0 ? .aurionAmber : .aurionGreen)

        return HStack(spacing: 14) {
            ZStack {
                // `displayedCompleteness` is driven by onAppear/onChange so
                // the ring sweeps from 0% up to the note's actual score
                // rather than snapping.
                CircularProgressRing(
                    progress: displayedCompleteness,
                    color: ringColor,
                    lineWidth: 4,
                    size: 48
                )
                Text("\(Int(displayedCompleteness * 100))%")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(.aurionNavy)
                    .contentTransition(.numericText())
                    .animation(AurionAnimation.smooth, value: displayedCompleteness)
            }
            VStack(alignment: .leading, spacing: 2) {
                // Numerator/denominator — the missing "5 of 6 sections" hint
                // so the percentage isn't the only signal.
                Text("\(populated) of \(totalSections) sections")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundColor(.aurionNavy)
                Text(helpText)
                    .font(.system(size: 12))
                    .foregroundColor(.aurionTextSecondary)
                    .lineSpacing(2)
                    .contentTransition(.opacity)
                    .animation(AurionAnimation.smooth, value: helpText)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            AurionGoldButton(
                label: stage2Running
                    ? "Finishing…"
                    : (isApproving ? "Signing…" : "Approve & Sign"),
                size: .sm,
                disabled: blocked || isApproving
            ) {
                approveNote()
            }
        }
        .aurionScreenEdge()
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
        guard !isApproving else { return }
        isApproving = true
        approveError = nil
        AurionHaptics.impact(.medium)
        Task {
            // Stage 1 review screen typically sits on a session in
            // AWAITING_REVIEW. /approve-stage1 transitions to
            // PROCESSING_STAGE2 (runs Stage 2 vision inline), and /approve
            // then transitions to REVIEW_COMPLETE.
            //
            // If the session is already past those states (REVIEW_COMPLETE,
            // EXPORTED, PURGED — common when reviewing seeded demo sessions),
            // the backend returns 400. We treat that as "already approved":
            // play the success toast and dismiss, since there's nothing more
            // for the physician to do.
            let stage1Result = await runApprovalStep {
                try await APIClient.shared.approveStage1(sessionId: sessionId)
            }
            // Even if stage1 returned "already past" we still try /approve —
            // the session may be in PROCESSING_STAGE2/REVIEW_COMPLETE which
            // /approve accepts.
            let approveResult = await runApprovalStep {
                try await APIClient.shared.approveFinalNote(sessionId: sessionId)
            }

            // Surface only real failures (network, 5xx). State mismatches
            // mean the session was already approved — treat as success.
            if let err = stage1Result.realFailure ?? approveResult.realFailure {
                await MainActor.run {
                    isApproving = false
                    approveError = err
                    AurionHaptics.notification(.error)
                }
                return
            }

            AuditLogger.log(event: .noteApproved, sessionId: sessionId)
            await MainActor.run {
                AurionHaptics.notification(.success)
                showApprovedToast = true
            }
            try? await Task.sleep(nanoseconds: 900_000_000)
            await MainActor.run {
                isApproving = false
                onDismiss()
            }
        }
    }

    /// Result of one approval API call. `realFailure` is non-nil only when
    /// the error is something the user can act on (network, 5xx). State
    /// mismatches (already-approved) collapse to a no-op success.
    private struct ApprovalStepResult {
        let realFailure: String?
    }

    private func runApprovalStep(
        _ step: () async throws -> Any
    ) async -> ApprovalStepResult {
        do {
            _ = try await step()
            return ApprovalStepResult(realFailure: nil)
        } catch let APIError.conflict(body) {
            // 409 from the approval endpoints means a state mismatch. The
            // FastAPI body says which state the session is in. Map known
            // states to clean copy:
            //   - PROCESSING_STAGE1/2 → "still processing, try again"
            //   - REVIEW_COMPLETE / EXPORTED / PURGED → already approved
            //     (treat as success and dismiss)
            //   - anything else → use the parsed FastAPI detail string
            let state = sessionStateFromConflict(body)
            switch state {
            case .stillProcessing:
                return ApprovalStepResult(realFailure: "Note is still processing. Try again in a moment.")
            case .alreadyApproved:
                return ApprovalStepResult(realFailure: nil)
            case .other(let message):
                return ApprovalStepResult(realFailure: message)
            }
        } catch let APIError.serverError(code) where (400...499).contains(code) {
            // 4xx (other than 409 above) → invalid state; suppress so
            // approval flow falls through to success.
            return ApprovalStepResult(realFailure: nil)
        } catch APIError.notFound {
            return ApprovalStepResult(realFailure: "Note not found on server.")
        } catch APIError.unauthorized {
            return ApprovalStepResult(realFailure: "Session expired — please sign in again.")
        } catch let APIError.serverError(code) {
            return ApprovalStepResult(realFailure: "Server error (\(code)). Try again.")
        } catch {
            return ApprovalStepResult(realFailure: error.localizedDescription)
        }
    }

    private enum ConflictKind {
        case stillProcessing
        case alreadyApproved
        case other(String)
    }

    /// Pull the human-readable detail out of FastAPI's
    /// `{"detail":"..."}` body and classify by the server state name it
    /// reports. Falls back to the raw detail (or the whole body) if we
    /// can't parse it.
    private func sessionStateFromConflict(_ body: String) -> ConflictKind {
        let detail: String = {
            if let data = body.data(using: .utf8),
               let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
               let d = json["detail"] as? String {
                return d
            }
            return body
        }()

        let upper = detail.uppercased()
        if upper.contains("PROCESSING_STAGE1") || upper.contains("PROCESSING_STAGE2") {
            return .stillProcessing
        }
        if upper.contains("REVIEW_COMPLETE") || upper.contains("EXPORTED") || upper.contains("PURGED") {
            return .alreadyApproved
        }
        return .other(detail)
    }

    private func saveEdits() {
        // Submit only sections whose draft text differs from the joined prose
        // currently displayed. Backend creates one new note version per call.
        guard let n = note else { return }
        let changed = draftEdits.filter { sectionId, draftText in
            guard let s = n.sections.first(where: { $0.id == sectionId }) else { return false }
            return joinedProse(s) != draftText
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
