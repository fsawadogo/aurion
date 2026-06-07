import SwiftUI

/// Coding & billing suggestions card (#69) — strategic separate
/// inference surface.
///
/// Aurion's clinical note is descriptive-only by policy. Coding is
/// fundamentally inferential (free-text findings → discrete billing
/// codes). The contradiction is resolved by giving coding its OWN
/// surface: own table, own card, always-visible "Assistive — physician
/// must confirm" disclaimer. Suggestions NEVER flow back into the
/// clinical note's sections or claims.
///
/// The descriptive-only moat depends on this surface being clearly
/// separate. UI choices that uphold that:
///   * cool-toned card border (navy, not the gold of clinical cards)
///   * always-visible amber disclaimer banner at the top
///   * per-system color chips (E/M navy, ICD-10 purple, CPT emerald)
///     visually group rows by family without using the brand gold
///   * low-confidence rows render expanded by default; high collapsed
///
/// Mirrors the portal's `<CodingSuggestionsCard />` from #168 + #171.
struct CodingSuggestionsCard: View {
    let sessionId: String
    let sessionState: String

    @State private var items: [CodingSuggestionResponse] = []
    @State private var isLoading = true
    @State private var isExtracting = false
    @State private var busyId: String?
    @State private var errorMessage: String?
    /// `true` when the initial GET errored out. Suppresses the
    /// empty-state CTA in favor of a Retry — clicking Suggest would
    /// fail the same way.
    @State private var loadFailed = false

    @State private var rejectTarget: CodingSuggestionResponse?
    @State private var editing: CodingSuggestionResponse?
    @State private var editingCode: String = ""
    @State private var editingDescription: String = ""

    private static let approvedStates: Set<String> = [
        "REVIEW_COMPLETE", "EXPORTED", "PURGED",
    ]

    private var isApproved: Bool {
        Self.approvedStates.contains(sessionState)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            header

            if !isApproved {
                gateNotice
            } else {
                // The assistive disclaimer ALWAYS shows once we're in
                // the approved branch — the safety property of this
                // surface depends on physicians knowing every render
                // that it's not chartable.
                assistiveBanner
                if isLoading {
                    ProgressView()
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 8)
                } else if loadFailed && sortedItems.isEmpty {
                    retryState(message: L("coding.loadFailed"))
                } else if sortedItems.isEmpty {
                    emptyState
                } else {
                    populatedState
                }
            }

            if let msg = errorMessage {
                Text(msg)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionRed)
            }
        }
        .padding(16)
        .background(Color.aurionCardBackground)
        .cornerRadius(16)
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                // Cool blue border distinguishes this from the gold-accented
                // clinical cards. Was .aurionNavy.opacity(0.25) — invisible on
                // the dark card in dark mode; mid-tone blue keeps the "cool"
                // distinction in both modes and matches the E/M chip (#293).
                .stroke(Color.aurionBlue.opacity(0.3), lineWidth: 1)
        )
        .task { await loadIfNeeded() }
        .onChange(of: sessionState) { newValue in
            if Self.approvedStates.contains(newValue) {
                Task { await loadIfNeeded() }
            }
        }
        .confirmationDialog(
            L("coding.rejectConfirmTitle"),
            isPresented: Binding(
                get: { rejectTarget != nil },
                set: { if !$0 { rejectTarget = nil } }
            ),
            titleVisibility: .visible,
            presenting: rejectTarget
        ) { target in
            Button(L("coding.reject"), role: .destructive) {
                Task { await reject(target) }
            }
            Button(L("coding.cancel"), role: .cancel) { rejectTarget = nil }
        } message: { _ in
            Text(L("coding.rejectConfirmMessage"))
        }
        .sheet(item: $editing) { target in
            editSheet(for: target)
        }
    }

    // MARK: Sorting / counts

    /// Pending (suggested + edited) first → confirmed → rejected.
    /// Within each, newest-first.
    private var sortedItems: [CodingSuggestionResponse] {
        items.sorted { a, b in
            let rank: [String: Int] = [
                "suggested": 0, "edited": 1, "confirmed": 2, "rejected": 3,
            ]
            let ra = rank[a.status] ?? 99
            let rb = rank[b.status] ?? 99
            if ra != rb { return ra < rb }
            return a.createdAt > b.createdAt
        }
    }

    private var pendingCount: Int {
        items.filter { $0.status == "suggested" }.count
    }

    private var confirmedCount: Int {
        items.filter { $0.status == "confirmed" || $0.status == "edited" }.count
    }

    private var unvalidatedCount: Int {
        items.filter {
            $0.codeValidated == false && $0.status != "rejected"
        }.count
    }

    // MARK: Subviews

    private var header: some View {
        HStack(spacing: 8) {
            // Adaptive — `aurionNavy` was chosen originally to reinforce
            // the "separate inference surface" treatment vs the gold-
            // accented clinical cards, but on the adaptive card
            // background it goes navy-on-dark-slate in dark mode and
            // disappears. Use the same text-primary token as the
            // title; visual separation is still carried by the navy
            // card border + per-system color chips + the always-on
            // assistive amber banner — those three already brand the
            // surface as distinct.
            Image(systemName: "function")
                .font(.system(size: 16))
                .foregroundColor(.aurionTextPrimary)
            Text(L("coding.title"))
                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.aurionTextPrimary)
            Spacer()
            if !sortedItems.isEmpty {
                Text(L("coding.summaryCounts", pendingCount, confirmedCount))
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
            }
        }
    }

    private var assistiveBanner: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundColor(.aurionAmber)
            VStack(alignment: .leading, spacing: 2) {
                Text(L("coding.assistive"))
                    .aurionFont(12, weight: .semibold, relativeTo: .caption)
                    .foregroundColor(.aurionTextPrimary)
                Text(L("coding.assistiveDetail"))
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
        }
        .padding(10)
        .background(Color.aurionAmber.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.aurionAmber.opacity(0.35), lineWidth: 1)
        )
    }

    private var gateNotice: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lock.fill")
                .font(.system(size: 12))
                .foregroundColor(.aurionTextSecondary)
            Text(L("coding.gateMessage"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
            Spacer()
        }
    }

    /// Same shape as the OrdersCard retry block — load GET errored
    /// and we have no items cached, so suppress the Suggest CTA and
    /// offer Retry instead.
    private func retryState(message: String) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(alignment: .top, spacing: 8) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .font(.system(size: 13))
                    .foregroundColor(.aurionAmber)
                Text(message)
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                Spacer()
            }
            Button {
                Task { await loadIfNeeded() }
            } label: {
                HStack(spacing: 4) {
                    if isLoading {
                        ProgressView().tint(.aurionTextPrimary)
                    } else {
                        Image(systemName: "arrow.clockwise")
                            .font(.system(size: 11, weight: .semibold))
                    }
                    Text(L("coding.retry"))
                        .aurionFont(12, weight: .semibold, relativeTo: .caption)
                }
                .foregroundColor(.aurionTextPrimary)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(Color.aurionSurfaceAlt)
                .clipShape(Capsule())
            }
            .disabled(isLoading)
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(L("coding.subtitle"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
            extractButton(label: L("coding.suggest"))
        }
    }

    private var populatedState: some View {
        VStack(alignment: .leading, spacing: 8) {
            if unvalidatedCount > 0 {
                catalogCallout
            }
            ForEach(sortedItems) { item in
                row(for: item)
                if item.id != sortedItems.last?.id {
                    Divider().background(Color.aurionBorder)
                }
            }
            HStack {
                Spacer()
                extractButton(label: L("coding.reSuggest"), ghost: true)
            }
            .padding(.top, 4)
        }
    }

    private var catalogCallout: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundColor(.aurionAmber)
            Text(unvalidatedCount == 1
                 ? L("coding.unrecognizedSummary", unvalidatedCount)
                 : L("coding.unrecognizedSummary.plural", unvalidatedCount))
                .aurionFont(12, relativeTo: .caption)
                .foregroundColor(.aurionTextPrimary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer()
        }
        .padding(10)
        .background(Color.aurionAmber.opacity(0.12))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.aurionAmber.opacity(0.35), lineWidth: 1)
        )
    }

    private func extractButton(label: String, ghost: Bool = false) -> some View {
        Button {
            Task { await extract() }
        } label: {
            HStack(spacing: 6) {
                if isExtracting {
                    ProgressView().tint(ghost ? .aurionTextPrimary : .aurionNavy)
                } else {
                    Image(systemName: ghost ? "arrow.clockwise" : "function")
                        .font(.system(size: 12, weight: .semibold))
                }
                Text(isExtracting ? L("coding.suggesting") : label)
                    .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                    .foregroundColor(ghost ? .aurionTextPrimary : .aurionNavy)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 7)
            .background(ghost ? Color.aurionSurfaceAlt : Color.aurionGold)
            .clipShape(Capsule())
        }
        .disabled(isExtracting)
    }

    // MARK: Row

    @State private var expandedIds: Set<String> = []

    private func row(for item: CodingSuggestionResponse) -> some View {
        // Low-confidence rows expand by default — they deserve the
        // most attention. Track per-id expansion so the user can
        // collapse a low-confidence row after reading it.
        let defaultExpanded = item.confidence == "low"
        let isExpanded = defaultExpanded
            ? !expandedIds.contains("collapse-\(item.id)")
            : expandedIds.contains("expand-\(item.id)")
        let isRejected = item.status == "rejected"

        return VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top, spacing: 8) {
                systemChip(for: item.codeSystem)
                VStack(alignment: .leading, spacing: 4) {
                    Button {
                        withAnimation(AurionAnimation.smooth) {
                            toggleExpansion(id: item.id, defaultExpanded: defaultExpanded)
                        }
                    } label: {
                        VStack(alignment: .leading, spacing: 4) {
                            HStack(spacing: 6) {
                                Text(item.code)
                                    .monospaced()
                                    .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                                    .foregroundColor(.aurionTextPrimary)
                                Text(item.description)
                                    .aurionFont(12, relativeTo: .caption)
                                    .foregroundColor(.aurionTextSecondary)
                                    .lineLimit(2)
                                    .multilineTextAlignment(.leading)
                                // Disclosure affordance — signals the row
                                // expands to reveal the justification.
                                Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                                    .font(.system(size: 9, weight: .semibold))
                                    .foregroundColor(.aurionTextSecondary)
                                    .accessibilityHidden(true)
                            }
                            HStack(spacing: 5) {
                                confidenceBadge(for: item.confidence)
                                if item.codeValidated == false {
                                    catalogMissPill
                                }
                                statusBadge(for: item.status)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    if isExpanded {
                        Text(item.justification)
                            .aurionFont(11, relativeTo: .caption2)
                            .foregroundColor(.aurionTextSecondary)
                            .fixedSize(horizontal: false, vertical: true)
                            .padding(.top, 2)
                        if item.codeValidated == false {
                            Text(L("coding.notInCatalogHint"))
                                .aurionFont(11, relativeTo: .caption2)
                                .foregroundColor(.aurionAmber)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                    }
                }

                Spacer(minLength: 6)

                actionStack(for: item)
            }
        }
        .opacity(isRejected ? 0.55 : 1.0)
        .padding(.vertical, 6)
    }

    private func toggleExpansion(id: String, defaultExpanded: Bool) {
        // Two-key scheme: "collapse-{id}" set means the user has
        // collapsed a default-expanded row; "expand-{id}" means the
        // user has expanded a default-collapsed row.
        if defaultExpanded {
            if expandedIds.contains("collapse-\(id)") {
                expandedIds.remove("collapse-\(id)")
            } else {
                expandedIds.insert("collapse-\(id)")
            }
        } else {
            if expandedIds.contains("expand-\(id)") {
                expandedIds.remove("expand-\(id)")
            } else {
                expandedIds.insert("expand-\(id)")
            }
        }
    }

    @ViewBuilder
    private func actionStack(for item: CodingSuggestionResponse) -> some View {
        if item.status == "suggested" || item.status == "edited" {
            HStack(spacing: 4) {
                editIcon(item)
                Button {
                    Task { await confirm(item) }
                } label: {
                    HStack(spacing: 3) {
                        if busyId == item.id {
                            ProgressView().tint(.aurionNavy)
                        } else {
                            Image(systemName: "checkmark")
                                .font(.system(size: 10, weight: .semibold))
                        }
                        Text(L("coding.confirm"))
                            .aurionFont(10, weight: .semibold, relativeTo: .caption2)
                    }
                    .foregroundColor(.aurionNavy)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 5)
                    .background(Color.aurionGold)
                    .clipShape(Capsule())
                    // 44pt minimum tap target (HIG) without enlarging
                    // the visible capsule.
                    .frame(minHeight: 44)
                    .contentShape(Rectangle())
                }
                .disabled(busyId == item.id)
                Button {
                    rejectTarget = item
                } label: {
                    Image(systemName: "xmark")
                        .font(.system(size: 11))
                        .foregroundColor(.aurionTextSecondary)
                        .padding(5)
                        .background(Color.aurionSurfaceAlt)
                        .clipShape(Circle())
                        .frame(minWidth: 44, minHeight: 44)
                        .contentShape(Rectangle())
                }
                .accessibilityLabel(L("coding.reject.a11y"))
                .disabled(busyId == item.id)
            }
        } else if item.status == "confirmed" {
            editIcon(item)
        } else {
            EmptyView()
        }
    }

    private func editIcon(_ item: CodingSuggestionResponse) -> some View {
        Button {
            editingCode = item.code
            editingDescription = item.description
            editing = item
        } label: {
            Image(systemName: "pencil")
                .font(.system(size: 11))
                .foregroundColor(.aurionTextSecondary)
                .padding(5)
                .background(Color.aurionSurfaceAlt)
                .clipShape(Circle())
                .frame(minWidth: 44, minHeight: 44)
                .contentShape(Rectangle())
        }
        .accessibilityLabel(L("coding.editCode.a11y"))
        .disabled(busyId == item.id)
    }

    // MARK: Chips

    private func systemChip(for system: String) -> some View {
        let style: (Color, String) = {
            switch system {
            // Mid-tone blue (visible both modes) — was .aurionNavy, which
            // rendered navy-on-navy-tint, invisible in dark mode; now matches
            // the icd10/cpt chip pattern (#293).
            case "em":    return (Color.aurionBlue, L("coding.system.em"))
            case "icd10": return (Color.purple, L("coding.system.icd10"))
            case "cpt":   return (Color.aurionGreen, L("coding.system.cpt"))
            default:      return (Color.aurionTextSecondary, system.uppercased())
            }
        }()
        return Text(style.1)
            .aurionFont(10, weight: .bold, relativeTo: .caption2)
            .tracking(0.5)
            .foregroundColor(style.0)
            .padding(.horizontal, 6)
            .padding(.vertical, 3)
            .background(style.0.opacity(0.12))
            .clipShape(RoundedRectangle(cornerRadius: 4))
            .frame(width: 50, alignment: .center)
    }

    @ViewBuilder
    private func confidenceBadge(for confidence: String) -> some View {
        switch confidence {
        case "low":
            badge(text: L("coding.confidence.low"), color: .aurionAmber, filled: false, withDot: true)
        case "medium":
            badge(text: L("coding.confidence.medium"), color: .aurionTextSecondary, filled: false, withDot: false)
        case "high":
            badge(text: L("coding.confidence.high"), color: .aurionGreen, filled: true, withDot: false)
        default:
            EmptyView()
        }
    }

    @ViewBuilder
    private func statusBadge(for status: String) -> some View {
        switch status {
        case "suggested":
            EmptyView()  // default state — no chip clutter
        case "confirmed":
            badge(text: L("coding.confirmed"), color: .aurionGreen, filled: true, withDot: false)
        case "edited":
            badge(text: L("coding.editedConfirmed"), color: .clinicalInfo, filled: true, withDot: false)
        case "rejected":
            badge(text: L("coding.rejected"), color: .aurionTextSecondary, filled: false, withDot: false)
        default:
            EmptyView()
        }
    }

    private var catalogMissPill: some View {
        HStack(spacing: 3) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 8, weight: .semibold))
            Text(L("coding.notInCatalog"))
                .aurionFont(10, weight: .semibold, relativeTo: .caption2)
        }
        .foregroundColor(.aurionAmber)
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(Color.aurionAmber.opacity(0.15))
        .clipShape(Capsule())
    }

    private func badge(
        text: String,
        color: Color,
        filled: Bool,
        withDot: Bool
    ) -> some View {
        HStack(spacing: 3) {
            if withDot {
                Circle()
                    .fill(color)
                    .frame(width: 4, height: 4)
            }
            Text(text)
                .aurionFont(9, weight: .semibold, relativeTo: .caption2)
        }
        .foregroundColor(filled ? .white : color)
        .padding(.horizontal, 5)
        .padding(.vertical, 2)
        .background(filled ? color : color.opacity(0.15))
        .clipShape(Capsule())
    }

    // MARK: Edit sheet

    @ViewBuilder
    private func editSheet(for target: CodingSuggestionResponse) -> some View {
        NavigationStack {
            VStack(alignment: .leading, spacing: 14) {
                HStack(spacing: 8) {
                    systemChip(for: target.codeSystem)
                    Text(L("coding.edit"))
                        .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                        .foregroundColor(.aurionTextPrimary)
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text(L("coding.field.code"))
                        .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                        .foregroundColor(.aurionTextSecondary)
                    TextField(L("coding.field.code"), text: $editingCode)
                        .autocorrectionDisabled(true)
                        .textInputAutocapitalization(.characters)
                        .monospaced()
                        .aurionFont(16, weight: .semibold, relativeTo: .body)
                        .padding(10)
                        .background(Color.aurionSurfaceAlt)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                VStack(alignment: .leading, spacing: 6) {
                    Text(L("coding.field.description"))
                        .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                        .foregroundColor(.aurionTextSecondary)
                    TextField(L("coding.field.description"), text: $editingDescription)
                        .aurionFont(15, relativeTo: .body)
                        .padding(10)
                        .background(Color.aurionSurfaceAlt)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                Spacer()
            }
            .padding(20)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("coding.cancel")) { editing = nil }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(L("coding.save")) {
                        Task { await saveEdit(target: target) }
                    }
                    .disabled(editingCode.trimmingCharacters(in: .whitespaces).isEmpty
                              || editingDescription.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            }
        }
        .presentationDetents([.medium])
    }

    // MARK: Actions

    private func loadIfNeeded() async {
        guard isApproved else { isLoading = false; return }
        isLoading = true
        do {
            items = try await APIClient.shared.listCodingSuggestions(sessionId: sessionId)
            errorMessage = nil
            loadFailed = false
        } catch {
            loadFailed = true
            errorMessage = nil
        }
        isLoading = false
    }

    private func extract() async {
        isExtracting = true
        errorMessage = nil
        defer { isExtracting = false }
        do {
            let created = try await APIClient.shared.extractCodingSuggestions(
                sessionId: sessionId
            )
            await loadIfNeeded()
            if created.isEmpty {
                errorMessage = L("coding.extractEmpty")
            }
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("coding.extractFailed")
        }
    }

    private func confirm(_ item: CodingSuggestionResponse) async {
        busyId = item.id
        errorMessage = nil
        defer { busyId = nil }
        do {
            let updated = try await APIClient.shared.confirmCodingSuggestion(
                sessionId: sessionId,
                suggestionId: item.id
            )
            withAnimation(AurionAnimation.smooth) {
                items = items.map { $0.id == updated.id ? updated : $0 }
            }
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("coding.confirmFailed")
        }
    }

    private func reject(_ item: CodingSuggestionResponse) async {
        busyId = item.id
        rejectTarget = nil
        errorMessage = nil
        defer { busyId = nil }
        do {
            let updated = try await APIClient.shared.rejectCodingSuggestion(
                sessionId: sessionId,
                suggestionId: item.id
            )
            withAnimation(AurionAnimation.smooth) {
                items = items.map { $0.id == updated.id ? updated : $0 }
            }
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("coding.rejectFailed")
        }
    }

    private func saveEdit(target: CodingSuggestionResponse) async {
        let code = editingCode.trimmingCharacters(in: .whitespaces)
        let description = editingDescription.trimmingCharacters(in: .whitespaces)
        guard !code.isEmpty, !description.isEmpty else { return }
        busyId = target.id
        errorMessage = nil
        defer { busyId = nil }
        do {
            let updated = try await APIClient.shared.editCodingSuggestion(
                sessionId: sessionId,
                suggestionId: target.id,
                code: code,
                description: description
            )
            withAnimation(AurionAnimation.smooth) {
                items = items.map { $0.id == updated.id ? updated : $0 }
            }
            editing = nil
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("coding.editFailed")
        }
    }
}
