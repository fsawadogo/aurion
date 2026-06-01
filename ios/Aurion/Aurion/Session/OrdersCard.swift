import SwiftUI

/// Structured orders card (#58).
///
/// Lives on the `SessionNoteView` alongside `PatientSummaryCard`.
/// Approval-gated — the LLM extractor only runs against approved
/// notes (orders are EMR-bound; can't come from a draft).
///
/// Mirrors the portal's `<OrdersCard />` (PR #167) so a session opened
/// on web vs iPad sees the same surfaces:
///   * Empty (no extraction yet) → Extract CTA + brief explainer
///   * Populated → per-row Confirm / Cancel actions; drafts at the top
///   * Re-extract button when orders already exist
///
/// ## Drug catalog warnings (#58 follow-up via #172)
///
/// Prescription rows whose drug name didn't resolve in the curated
/// catalog render an amber "Drug not in catalog" pill + verify-before-
/// prescribing hint. The catalog itself stays server-side; iOS just
/// reads the `drugValidated` field on the row.
///
/// ## Cancel confirmation
///
/// A cancel is destructive (the row stays in the audit log but can't
/// be sent), so we wrap the action in a confirmation dialog. Confirm
/// is single-tap on the assumption that physicians have already
/// reviewed the row text before approving.
struct OrdersCard: View {
    let sessionId: String
    let sessionState: String

    @State private var orders: [NoteOrderResponse] = []
    @State private var isLoading = true
    @State private var isExtracting = false
    @State private var busyOrderId: String?
    @State private var errorMessage: String?

    @State private var cancelTarget: NoteOrderResponse?

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
            } else if isLoading {
                ProgressView()
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
            } else if visibleOrders.isEmpty {
                emptyState
            } else {
                populatedState
            }

            if let msg = errorMessage {
                Text(msg)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.red)
            }
        }
        .padding(16)
        .background(Color.aurionCardBackground)
        .cornerRadius(16)
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .task { await loadIfNeeded() }
        .onChange(of: sessionState) { newValue in
            if Self.approvedStates.contains(newValue) {
                Task { await loadIfNeeded() }
            }
        }
        .confirmationDialog(
            cancelTarget.map { L("orders.cancelConfirmTitle",
                                  localizedKindLabel($0.kind).lowercased()) } ?? "",
            isPresented: Binding(
                get: { cancelTarget != nil },
                set: { if !$0 { cancelTarget = nil } }
            ),
            titleVisibility: .visible,
            presenting: cancelTarget
        ) { target in
            Button(L("orders.cancel"), role: .destructive) {
                Task { await cancelOrder(target) }
            }
            Button(L("summary.cancel"), role: .cancel) { cancelTarget = nil }
        } message: { _ in
            Text(L("orders.cancelConfirmMessage"))
        }
    }

    // MARK: Sorted, header-visible orders

    /// Drafts first (need attention), then confirmed, then sent, then
    /// cancelled. Within each, newest-first.
    private var visibleOrders: [NoteOrderResponse] {
        orders.sorted { a, b in
            let rank: [String: Int] = [
                "draft": 0, "confirmed": 1, "sent": 2, "cancelled": 3,
            ]
            let ra = rank[a.status] ?? 99
            let rb = rank[b.status] ?? 99
            if ra != rb { return ra < rb }
            return a.createdAt > b.createdAt
        }
    }

    private var draftCount: Int { orders.filter { $0.status == "draft" }.count }
    private var confirmedCount: Int { orders.filter { $0.status == "confirmed" }.count }

    /// Header-level callout when one or more prescription drafts have
    /// drug_validated=false. Excludes cancelled rows (already declined).
    private var unrecognizedDrugCount: Int {
        orders.filter {
            $0.kind == "prescription"
                && $0.drugValidated == false
                && $0.status != "cancelled"
        }.count
    }

    // MARK: Subviews

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "list.bullet.clipboard")
                .font(.system(size: 16))
                .foregroundColor(.aurionGold)
            Text(L("orders.title"))
                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.aurionTextPrimary)
            Spacer()
            if !visibleOrders.isEmpty {
                Text(L("orders.countSummary", draftCount, confirmedCount))
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
            }
        }
    }

    private var gateNotice: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lock.fill")
                .font(.system(size: 12))
                .foregroundColor(.aurionTextSecondary)
            Text(L("orders.gateMessage"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
            Spacer()
        }
    }

    private var emptyState: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(L("orders.subtitle"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
            extractButton(label: L("orders.extract"))
        }
    }

    private var populatedState: some View {
        VStack(alignment: .leading, spacing: 8) {
            if unrecognizedDrugCount > 0 {
                drugCatalogCallout
            }
            ForEach(visibleOrders) { order in
                row(for: order)
                if order.id != visibleOrders.last?.id {
                    Divider().background(Color.aurionBorder)
                }
            }
            HStack {
                Spacer()
                extractButton(label: L("orders.reExtract"), ghost: true)
            }
            .padding(.top, 4)
        }
    }

    private var drugCatalogCallout: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundColor(.aurionAmber)
            Text(unrecognizedDrugCount == 1
                 ? L("orders.unrecognizedSummary", unrecognizedDrugCount)
                 : L("orders.unrecognizedSummary.plural", unrecognizedDrugCount))
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
                    Image(systemName: ghost ? "arrow.clockwise" : "sparkles")
                        .font(.system(size: 12, weight: .semibold))
                }
                Text(isExtracting ? L("orders.extracting") : label)
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

    private func row(for order: NoteOrderResponse) -> some View {
        let isCancelled = order.status == "cancelled"
        return HStack(alignment: .top, spacing: 10) {
            Image(systemName: iconName(for: order.kind))
                .font(.system(size: 16))
                .foregroundColor(.aurionTextSecondary)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(localizedKindLabel(order.kind))
                        .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                        .foregroundColor(.aurionTextPrimary)
                    statusBadge(for: order.status)
                    if order.kind == "prescription" && order.drugValidated == false {
                        catalogWarningPill
                    }
                }
                Text(summarize(order))
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                if order.kind == "prescription" && order.drugValidated == false {
                    Text(L("orders.drugVerifyHint"))
                        .aurionFont(11, relativeTo: .caption2)
                        .foregroundColor(.aurionAmber)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Spacer(minLength: 6)

            if order.status == "draft" {
                actionStack(for: order)
            } else if order.status == "confirmed" {
                cancelOnlyButton(order)
            }
        }
        .opacity(isCancelled ? 0.55 : 1.0)
        .padding(.vertical, 6)
    }

    private func actionStack(for order: NoteOrderResponse) -> some View {
        HStack(spacing: 6) {
            Button {
                Task { await confirmOrder(order) }
            } label: {
                HStack(spacing: 4) {
                    if busyOrderId == order.id {
                        ProgressView().tint(.aurionNavy)
                    } else {
                        Image(systemName: "checkmark")
                            .font(.system(size: 11, weight: .semibold))
                    }
                    Text(L("orders.confirm"))
                        .aurionFont(11, weight: .semibold, relativeTo: .caption)
                }
                .foregroundColor(.aurionNavy)
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Color.aurionGold)
                .clipShape(Capsule())
            }
            .disabled(busyOrderId == order.id)

            cancelOnlyButton(order)
        }
    }

    private func cancelOnlyButton(_ order: NoteOrderResponse) -> some View {
        Button {
            cancelTarget = order
        } label: {
            Image(systemName: "trash")
                .font(.system(size: 13))
                .foregroundColor(.aurionTextSecondary)
                .padding(6)
                .background(Color.aurionSurfaceAlt)
                .clipShape(Circle())
        }
        .disabled(busyOrderId == order.id)
    }

    // MARK: Chips + helpers

    @ViewBuilder
    private func statusBadge(for status: String) -> some View {
        switch status {
        case "draft":
            badge(text: L("orders.draft"), color: .aurionGold, filled: false)
        case "confirmed":
            badge(text: L("orders.confirmed"), color: .aurionGreen, filled: true)
        case "sent":
            badge(text: L("orders.sent"), color: .clinicalInfo, filled: true)
        case "cancelled":
            badge(text: L("orders.cancelled"), color: .aurionTextSecondary, filled: false)
        default:
            EmptyView()
        }
    }

    private func badge(text: String, color: Color, filled: Bool) -> some View {
        Text(text)
            .aurionFont(10, weight: .semibold, relativeTo: .caption2)
            .foregroundColor(filled ? .white : color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(filled ? color : color.opacity(0.15))
            .clipShape(Capsule())
    }

    private var catalogWarningPill: some View {
        HStack(spacing: 3) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 8, weight: .semibold))
            Text(L("orders.drugNotInCatalog"))
                .aurionFont(10, weight: .semibold, relativeTo: .caption2)
        }
        .foregroundColor(.aurionAmber)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(Color.aurionAmber.opacity(0.15))
        .clipShape(Capsule())
    }

    private func iconName(for kind: String) -> String {
        switch kind {
        case "imaging":      return "camera.viewfinder"
        case "lab":          return "drop.fill"
        case "referral":     return "person.crop.circle.badge.plus"
        case "prescription": return "pills.fill"
        default:             return "doc"
        }
    }

    private func localizedKindLabel(_ kind: String) -> String {
        L("orders.kind.\(kind)")
    }

    /// One-line summary of the per-kind details. Mirrors the portal's
    /// summarizeDetails helper in components/portal/OrdersCard.tsx.
    private func summarize(_ order: NoteOrderResponse) -> String {
        let d = order.details
        switch order.kind {
        case "imaging":
            let modality = d["modality"] ?? "?"
            let bodyPart = d["body_part"] ?? "?"
            let laterality = d["laterality"]
            let indication = d["indication"]
            var s = "\(modality) of \(bodyPart)"
            if let lat = laterality, !lat.isEmpty, lat != "null" {
                s += " (\(lat))"
            }
            if let ind = indication, !ind.isEmpty {
                s += " — \(ind)"
            }
            return s
        case "lab":
            let panel = d["panel"] ?? "?"
            if let ind = d["indication"], !ind.isEmpty {
                return "\(panel) — \(ind)"
            }
            return panel
        case "referral":
            var parts: [String] = []
            if let s = d["specialty"], !s.isEmpty { parts.append(s) }
            if let u = d["urgency"], !u.isEmpty, u != "routine" { parts.append("(\(u))") }
            if let r = d["reason"], !r.isEmpty { parts.append("— \(r)") }
            return parts.joined(separator: " ")
        case "prescription":
            var parts: [String] = []
            if let v = d["drug"], !v.isEmpty { parts.append(v) }
            if let v = d["dose"], !v.isEmpty { parts.append(v) }
            if let v = d["frequency"], !v.isEmpty { parts.append(v) }
            if let v = d["duration"], !v.isEmpty { parts.append("for \(v)") }
            if let v = d["indication"], !v.isEmpty { parts.append("— \(v)") }
            return parts.joined(separator: " ")
        default:
            return ""
        }
    }

    // MARK: Actions

    private func loadIfNeeded() async {
        guard isApproved else { isLoading = false; return }
        isLoading = true
        do {
            orders = try await APIClient.shared.listOrders(sessionId: sessionId)
            errorMessage = nil
        } catch {
            errorMessage = L("orders.extractFailed")
        }
        isLoading = false
    }

    private func extract() async {
        isExtracting = true
        errorMessage = nil
        defer { isExtracting = false }
        do {
            let created = try await APIClient.shared.extractOrders(sessionId: sessionId)
            // Re-fetch the full list so existing drafts merge in
            // (server returns only the new batch).
            await loadIfNeeded()
            if created.isEmpty {
                errorMessage = L("orders.extractEmpty")
            }
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("orders.extractFailed")
        }
    }

    private func confirmOrder(_ order: NoteOrderResponse) async {
        busyOrderId = order.id
        errorMessage = nil
        defer { busyOrderId = nil }
        do {
            let updated = try await APIClient.shared.confirmOrder(
                sessionId: sessionId,
                orderId: order.id
            )
            orders = orders.map { $0.id == updated.id ? updated : $0 }
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("orders.confirmFailed")
        }
    }

    private func cancelOrder(_ order: NoteOrderResponse) async {
        busyOrderId = order.id
        cancelTarget = nil
        errorMessage = nil
        defer { busyOrderId = nil }
        do {
            let updated = try await APIClient.shared.cancelOrder(
                sessionId: sessionId,
                orderId: order.id
            )
            orders = orders.map { $0.id == updated.id ? updated : $0 }
            AurionHaptics.notification(.success)
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("orders.cancelFailed")
        }
    }
}
