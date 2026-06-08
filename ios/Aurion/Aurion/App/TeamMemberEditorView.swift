import SwiftUI

/// Sheet for editing the clinician's allied-health team (nurses, scribes,
/// residents, PAs, MOAs — the people in the room during a visit).
///
/// Wired from `ProfileView.swift` via `.sheet(isPresented: $showTeamMemberEditor)`.
/// Closes GH-260 — the button on the Profile screen was flipping a state
/// flag with no observer; the sheet now opens and persists changes on
/// dismiss.
///
/// Design notes:
/// - Buffers edits locally so a swipe-to-dismiss without changes is a true
///   no-op (no API call, no audit row).
/// - Persistence is **opt-in** via the top-right "Done" button (which
///   diffs the buffer against the original list and calls
///   `APIClient.updateProfile` only when there's an actual change).
/// - Name / role hard-capped at 60 chars client-side to discourage
///   note-style free text from creeping into a workforce field (AC-9).
/// - Audit event (`TEAM_MEMBERS_UPDATED`) is emitted server-side by
///   `PUT /profile`; iOS just calls the existing endpoint.
struct TeamMemberEditorView: View {
    @EnvironmentObject var appState: AppState
    @Environment(\.dismiss) private var dismiss

    /// Test seam — the view normally calls `APIClient.shared.updateProfile`
    /// but tests inject a no-op or counter closure to keep network out of
    /// the unit-test loop. Returning the updated profile keeps the
    /// `appState.physicianProfile` refresh deterministic.
    let persist: ([AlliedHealthMember]) async throws -> PhysicianProfileResponse

    /// Working buffer — initialized from the live profile on first
    /// appearance, then mutated freely. Diffed against `original` on
    /// "Done" so an idempotent dismiss skips the network call.
    @State private var buffer: [AlliedHealthMember] = []
    @State private var original: [AlliedHealthMember] = []

    @State private var draftName: String = ""
    @State private var draftRole: String = ""
    @State private var draftEmail: String = ""
    @State private var showAddForm = false
    @FocusState private var nameFocused: Bool

    /// Edit-in-place (#275 / I3 — folds in the #300 deferred team-editor
    /// edit item). The local `id` of the member currently open in the edit
    /// sheet, or nil when no edit is in flight. Edits are buffered in the
    /// `edit*` drafts and replaced at the member's buffer index on Save;
    /// Cancel drops them. Separate from the add-form drafts so the inline
    /// add and the edit sheet never cross-contaminate.
    @State private var editingMemberID: UUID?
    @State private var editName: String = ""
    @State private var editRole: String = ""
    @State private var editEmail: String = ""
    @FocusState private var editNameFocused: Bool

    @State private var isSaving = false
    @State private var saveError: String?

    /// Hard cap matches the AC: 60 chars per name/role keeps the audit
    /// trail noise-free and signals to the user "this is a tag, not a
    /// note". Email isn't capped here — it goes through the standard
    /// `textContentType(.emailAddress)` keyboard and the backend's JSON
    /// column tolerates any value.
    private static let fieldCharLimit = 60

    /// Default initializer used by `ProfileView` — production path. Wraps
    /// the live `APIClient.updateProfile` call.
    init() {
        self.persist = { team in
            try await APIClient.shared.updateProfile([
                "allied_health_team": team.map(Self.encodeMember),
            ])
        }
    }

    /// Test initializer — swap the persist closure for a stub. Keeps the
    /// view's API surface minimal (the test only ever needs to observe
    /// what was passed to persist).
    init(persist: @escaping ([AlliedHealthMember]) async throws -> PhysicianProfileResponse) {
        self.persist = persist
    }

    // MARK: - Body

    var body: some View {
        NavigationStack {
            content
                .navigationTitle(L("profile.teamEditor.title"))
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button(L("profile.teamEditor.cancel")) {
                            // Swipe-style dismiss: drop the buffer, no
                            // network call. Mirrors the system gesture
                            // and makes the no-op contract explicit.
                            dismiss()
                        }
                        .foregroundColor(.aurionTextPrimary)
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Button(L("profile.teamEditor.done")) {
                            Task { await commit() }
                        }
                        .foregroundColor(.aurionGold)
                        .fontWeight(.semibold)
                        .disabled(isSaving)
                    }
                }
                .onAppear(perform: seedBuffer)
                .sheet(
                    isPresented: Binding(
                        get: { editingMemberID != nil },
                        set: { if !$0 { cancelEditing() } }
                    )
                ) {
                    editMemberSheet
                }
        }
    }

    private var content: some View {
        List {
            if let saveError {
                Section {
                    ErrorBanner(saveError, onDismiss: { self.saveError = nil })
                        .listRowInsets(EdgeInsets())
                        .listRowBackground(Color.clear)
                }
            }

            // ── Existing members ──────────────────────────────────────
            Section {
                if buffer.isEmpty {
                    Text(L("profile.noTeam"))
                        .aurionCaption()
                } else {
                    ForEach(buffer) { member in
                        memberRow(member)
                    }
                    .onDelete(perform: deleteMembers)
                }
            } header: {
                SectionHeader(
                    title: L("profile.teamEditor.sectionMembers"),
                    count: buffer.isEmpty ? nil : buffer.count
                )
            }

            // ── Add member ────────────────────────────────────────────
            Section {
                if showAddForm {
                    addMemberForm
                } else {
                    Button {
                        AurionHaptics.impact(.light)
                        withAnimation { showAddForm = true }
                        // Defer focus until the field is in the view tree
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                            nameFocused = true
                        }
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "plus.circle.fill")
                                .foregroundColor(.aurionGold)
                            Text(L("profile.teamEditor.addMember"))
                                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                                .foregroundColor(.aurionTextPrimary)
                            Spacer()
                        }
                    }
                    .buttonStyle(.plain)
                }
            } footer: {
                Text(L("profile.teamEditor.footer"))
                    .font(.caption2)
                    .foregroundColor(.aurionTextSecondary)
            }
        }
        .overlay {
            if isSaving {
                ZStack {
                    Color.black.opacity(0.3).ignoresSafeArea()
                    ProgressView()
                        .padding(AurionSpacing.lg)
                        .background(.ultraThinMaterial)
                        .cornerRadius(AurionSpacing.md)
                }
            }
        }
    }

    // MARK: - Rows

    private func memberRow(_ member: AlliedHealthMember) -> some View {
        HStack(spacing: 12) {
            // Decorative — the role/name text already conveys the entry, so
            // hide the bubble from VoiceOver to avoid a stray focus stop.
            AurionIconBubble(symbol: "person.fill", tint: .aurionBlue, size: 36)
                .accessibilityHidden(true)
            // Tapping the member opens the edit sheet (#275 / I3). Scoped to
            // the text column (NOT the whole row) so the trailing "Working
            // today" toggle keeps its own hit target.
            Button {
                beginEditing(member)
            } label: {
                VStack(alignment: .leading, spacing: 2) {
                    Text(member.name)
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                    Text(member.role.displayFormatted)
                        .aurionFont(12, relativeTo: .caption)
                        .foregroundColor(.aurionTextSecondary)
                    if let email = member.email, !email.isEmpty {
                        Text(email)
                            .aurionFont(11, relativeTo: .caption2)
                            .foregroundColor(.aurionMutedGray)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            // Read the name/role/email column as one element; expose edit.
            .accessibilityElement(children: .combine)
            .accessibilityHint(L("profile.teamEditor.editHint"))

            // Per-day roster toggle (#275 / I2). Marks the member as working
            // today; the start-sheet day-roster picker filters on the
            // backend's effective-presence so only today's team shows.
            Toggle("", isOn: workingTodayBinding(for: member))
                .labelsHidden()
                .tint(.aurionGold)
                .accessibilityLabel(L("profile.teamEditor.workingToday"))
        }
        .padding(.vertical, 4)
    }

    /// Two-way binding for a member's "working today" flag, written straight
    /// into the buffer so the diff→persist path picks it up on Done. Setting
    /// it stamps today's date (so the backend's effective-presence check
    /// passes); clearing it drops the date.
    private func workingTodayBinding(for member: AlliedHealthMember) -> Binding<Bool> {
        Binding(
            get: {
                guard let idx = buffer.firstIndex(where: { $0.id == member.id }) else { return false }
                return buffer[idx].isWorkingToday
            },
            set: { newValue in
                guard let idx = buffer.firstIndex(where: { $0.id == member.id }) else { return }
                buffer[idx] = buffer[idx].settingWorkingToday(newValue)
                AurionHaptics.selection()
            }
        )
    }

    /// Subtle "NN/60" counter that fades in only as a field nears the hard
    /// cap, so the silent truncation at 60 chars has visible feedback —
    /// mirrors the inline validation copy used for custom visit types in
    /// `PhysicianProfileSetupView`. Turns gold once the cap is reached.
    @ViewBuilder
    private func charCountHint(_ count: Int) -> some View {
        if count >= Self.fieldCharLimit - 10 {
            Text("\(count)/\(Self.fieldCharLimit)")
                .aurionFont(11, relativeTo: .caption2)
                .monospacedDigit()
                .foregroundColor(count >= Self.fieldCharLimit ? .aurionGold : .aurionTextSecondary)
                .frame(maxWidth: .infinity, alignment: .trailing)
                .accessibilityLabel(L("profile.teamEditor.charCount", count, Self.fieldCharLimit))
        }
    }

    private var addMemberForm: some View {
        VStack(alignment: .leading, spacing: AurionSpacing.sm) {
            // Name
            VStack(alignment: .leading, spacing: 4) {
                Text(L("profile.teamEditor.nameLabel"))
                    .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
                TextField(L("profile.teamEditor.namePlaceholder"), text: $draftName)
                    .focused($nameFocused)
                    .textContentType(.name)
                    .autocorrectionDisabled()
                    .onChange(of: draftName) { _, new in
                        if new.count > Self.fieldCharLimit {
                            draftName = String(new.prefix(Self.fieldCharLimit))
                        }
                    }
                charCountHint(draftName.count)
            }

            // Role
            VStack(alignment: .leading, spacing: 4) {
                Text(L("profile.teamEditor.roleLabel"))
                    .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
                TextField(L("profile.teamEditor.rolePlaceholder"), text: $draftRole)
                    .textContentType(.jobTitle)
                    .autocorrectionDisabled()
                    .onChange(of: draftRole) { _, new in
                        if new.count > Self.fieldCharLimit {
                            draftRole = String(new.prefix(Self.fieldCharLimit))
                        }
                    }
                charCountHint(draftRole.count)
            }

            // Email (optional)
            VStack(alignment: .leading, spacing: 4) {
                Text(L("profile.teamEditor.emailLabel"))
                    .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
                TextField(L("profile.teamEditor.emailPlaceholder"), text: $draftEmail)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
            }

            HStack(spacing: AurionSpacing.sm) {
                Button(L("profile.teamEditor.cancelAdd")) {
                    resetForm()
                    withAnimation { showAddForm = false }
                }
                // Explicit button style is mandatory inside a List row:
                // default (.automatic) buttons make the whole row the tap
                // target and fire EVERY button's action in order, so a tap
                // ran Cancel (clearing the drafts) then Add (no-op). Borderless
                // gives each its own hit target (#274). [Re-applied — this fix
                // was dropped from the build-256 bundle merge.]
                .buttonStyle(.borderless)
                .foregroundColor(.aurionTextSecondary)

                Spacer()

                Button(L("profile.teamEditor.confirmAdd")) {
                    addMember()
                }
                .buttonStyle(.borderless)
                .foregroundColor(canAdd ? .aurionGold : .aurionMutedGray)
                .fontWeight(.semibold)
                .disabled(!canAdd)
            }
            .padding(.top, 4)
        }
        .padding(.vertical, 6)
    }

    private var canAdd: Bool {
        !draftName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !draftRole.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    // MARK: - Edit-in-place (#275 / I3)

    /// Sheet form prefilled from the tapped member; Save replaces the entry
    /// at its buffer index (preserving its `id` + presence flags), Cancel
    /// drops the edits. Reuses the same 60-char field caps + `charCountHint`
    /// as the add form.
    private var editMemberSheet: some View {
        NavigationStack {
            Form {
                Section {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(L("profile.teamEditor.nameLabel"))
                            .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                            .foregroundColor(.aurionTextSecondary)
                        TextField(L("profile.teamEditor.namePlaceholder"), text: $editName)
                            .focused($editNameFocused)
                            .textContentType(.name)
                            .autocorrectionDisabled()
                            .onChange(of: editName) { _, new in
                                if new.count > Self.fieldCharLimit {
                                    editName = String(new.prefix(Self.fieldCharLimit))
                                }
                            }
                        charCountHint(editName.count)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text(L("profile.teamEditor.roleLabel"))
                            .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                            .foregroundColor(.aurionTextSecondary)
                        TextField(L("profile.teamEditor.rolePlaceholder"), text: $editRole)
                            .textContentType(.jobTitle)
                            .autocorrectionDisabled()
                            .onChange(of: editRole) { _, new in
                                if new.count > Self.fieldCharLimit {
                                    editRole = String(new.prefix(Self.fieldCharLimit))
                                }
                            }
                        charCountHint(editRole.count)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text(L("profile.teamEditor.emailLabel"))
                            .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                            .foregroundColor(.aurionTextSecondary)
                        TextField(L("profile.teamEditor.emailPlaceholder"), text: $editEmail)
                            .textContentType(.emailAddress)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    }
                }
            }
            .navigationTitle(L("profile.teamEditor.editTitle"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(L("profile.teamEditor.cancel")) { cancelEditing() }
                        .foregroundColor(.aurionTextPrimary)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L("profile.teamEditor.save")) { commitEdit() }
                        .foregroundColor(canEditSave ? .aurionGold : .aurionMutedGray)
                        .fontWeight(.semibold)
                        .disabled(!canEditSave)
                }
            }
            .onAppear {
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) {
                    editNameFocused = true
                }
            }
        }
        .presentationDetents([.medium, .large])
    }

    private var canEditSave: Bool {
        !editName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !editRole.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private func beginEditing(_ member: AlliedHealthMember) {
        AurionHaptics.impact(.light)
        editName = member.name
        editRole = member.role
        editEmail = member.email ?? ""
        editingMemberID = member.id
    }

    private func cancelEditing() {
        editingMemberID = nil
        editName = ""
        editRole = ""
        editEmail = ""
    }

    /// Replace the edited member at its buffer index, preserving the local
    /// `id` (list-identity stability) and the per-day presence flags (the
    /// edit form only touches name/role/email).
    private func commitEdit() {
        guard canEditSave,
              let id = editingMemberID,
              let idx = buffer.firstIndex(where: { $0.id == id }) else { return }
        let existing = buffer[idx]
        let trimmedEmail = editEmail.trimmingCharacters(in: .whitespacesAndNewlines)
        buffer[idx] = AlliedHealthMember(
            id: existing.id,
            name: editName.trimmingCharacters(in: .whitespacesAndNewlines),
            role: editRole.trimmingCharacters(in: .whitespacesAndNewlines),
            email: trimmedEmail.isEmpty ? nil : trimmedEmail,
            presentToday: existing.presentToday,
            presentTodayDate: existing.presentTodayDate,
            presentTodayEffective: existing.presentTodayEffective
        )
        AurionHaptics.notification(.success)
        cancelEditing()
    }

    // MARK: - State mutations

    private func seedBuffer() {
        guard buffer.isEmpty, original.isEmpty else { return }
        let team = appState.physicianProfile?.alliedHealthTeam ?? []
        original = team
        buffer = team
    }

    private func deleteMembers(at offsets: IndexSet) {
        buffer.remove(atOffsets: offsets)
        AurionHaptics.impact(.light)
    }

    /// Appends `draftName + draftRole + draftEmail` as a new
    /// `AlliedHealthMember` and resets the inline form so the next add
    /// starts clean. No-op when `canAdd` is false (defensive — the
    /// button is disabled too).
    private func addMember() {
        guard canAdd else { return }
        let trimmedName = draftName.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedRole = draftRole.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedEmail = draftEmail.trimmingCharacters(in: .whitespacesAndNewlines)
        let member = AlliedHealthMember(
            name: trimmedName,
            role: trimmedRole,
            email: trimmedEmail.isEmpty ? nil : trimmedEmail
        )
        buffer.append(member)
        AurionHaptics.notification(.success)
        resetForm()
        withAnimation { showAddForm = false }
    }

    private func resetForm() {
        draftName = ""
        draftRole = ""
        draftEmail = ""
    }

    // MARK: - Persistence

    /// Diff `buffer` against `original`; if unchanged, dismiss without
    /// touching the network so a no-op editor session leaves no audit
    /// row. Otherwise call `persist`, update the cached profile, and
    /// dismiss on success.
    private func commit() async {
        guard !isSaving else { return }
        if Self.contentEqual(buffer, original) {
            dismiss()
            return
        }
        isSaving = true
        defer { isSaving = false }
        do {
            let profile = try await persist(buffer)
            appState.physicianProfile = profile
            AurionHaptics.notification(.success)
            dismiss()
        } catch {
            saveError = L("profile.teamEditor.saveFailed")
            AurionHaptics.notification(.error)
        }
    }

    /// Compare by the wire-meaningful fields only — the local `id` is
    /// regenerated on decode and would otherwise force every comparison
    /// to return false.
    static func contentEqual(_ a: [AlliedHealthMember], _ b: [AlliedHealthMember]) -> Bool {
        guard a.count == b.count else { return false }
        for (x, y) in zip(a, b) {
            // Compare the wire-meaningful fields, now including the raw
            // per-day presence keys (#275 / I2) so a "working today" toggle
            // — with no name/role/email change — still trips the diff and
            // persists. `presentTodayEffective` is backend-derived and
            // intentionally excluded.
            if x.name != y.name || x.role != y.role || x.email != y.email
                || x.presentToday != y.presentToday
                || x.presentTodayDate != y.presentTodayDate {
                return false
            }
        }
        return true
    }

    /// Serialize a member to the `[String: Any]` shape `updateProfile`
    /// expects. Strips `id` (local-only) and omits `email` when nil so
    /// the wire payload matches pre-existing rows. Emits the two raw
    /// presence keys (#275 / I2) when set; the backend recomputes the
    /// effective flag on read, so `present_today_effective` is never sent.
    static func encodeMember(_ member: AlliedHealthMember) -> [String: Any] {
        var dict: [String: Any] = [
            "name": member.name,
            "role": member.role,
        ]
        if let email = member.email, !email.isEmpty {
            dict["email"] = email
        }
        if let presentToday = member.presentToday {
            dict["present_today"] = presentToday
        }
        if let date = member.presentTodayDate, !date.isEmpty {
            dict["present_today_date"] = date
        }
        return dict
    }
}
