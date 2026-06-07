import SwiftUI

/// EMR write-back card (#57) — outbound terminal step.
///
/// Lives on `SessionNoteView` below the coding card. Approval-gated.
/// Pilot deployments register only the `stub` connector (records the
/// attempt locally; never transmits to a real EMR); the card surfaces
/// a "Pilot mode" banner in that state so the physician doesn't think
/// the note actually went to a chart system.
///
/// Mirrors the portal's `<EmrWriteBackCard />` from #169 + #175.
///
/// ## Three retry states (#174 + #175)
///
/// The latest write-back row's `(status, scheduledAt)` pair tells the
/// physician what's happening:
///
///   * `sent` → green check + "Sent <timestamp>" in the header.
///     Send-again is available (creates a brand-new attempt row).
///   * `failed` + `scheduledAt != nil` → amber banner "Auto-retry
///     scheduled for HH:MM"; the primary action degrades to a
///     ghost-style "Send fresh now (skip wait)" so the physician
///     doesn't reflex-tap a duplicate
///   * `failed` + `scheduledAt == nil` → red "No more auto-retries"
///     banner; Send-again is primary again
///
/// History list below the action bar shows every attempt row with
/// status icon + connector + (if set) external EMR id + (if failed)
/// sanitized error message + fingerprint prefix + retry status.
struct EmrWriteBackCard: View {
    let sessionId: String
    let sessionState: String

    @State private var rows: [EmrWriteBackResponse] = []
    @State private var connectors: EmrConnectorsResponse?
    @State private var selectedConnector: String = "stub"

    @State private var isLoading = true
    @State private var isSending = false
    @State private var errorMessage: String?
    /// `true` when the initial parallel GETs (history + connector
    /// catalog) errored. Replaces the Send CTA with a Retry —
    /// Send would 403 the same way.
    @State private var loadFailed = false

    private static let approvedStates: Set<String> = [
        "REVIEW_COMPLETE", "EXPORTED", "PURGED",
    ]

    private var isApproved: Bool {
        Self.approvedStates.contains(sessionState)
    }

    /// Pilot deployments register only `stub`. When that's the only
    /// option, the card surfaces an amber banner explaining that
    /// sends don't actually transmit.
    private var isPilotMode: Bool {
        connectors?.available == ["stub"]
    }

    /// Latest (newest) row drives the action-bar state.
    private var latest: EmrWriteBackResponse? { rows.first }
    private var isAutoRetryPending: Bool {
        latest?.status == "failed" && (latest?.scheduledAt?.isEmpty == false)
    }
    private var isTerminalFailure: Bool {
        latest?.status == "failed" && (latest?.scheduledAt == nil)
    }
    private var lastSent: EmrWriteBackResponse? {
        rows.first(where: { $0.status == "sent" })
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
            } else if loadFailed && rows.isEmpty && connectors == nil {
                // GET errored AND we have nothing cached — suppress
                // the Send CTA (would 403 the same) in favor of Retry.
                retryState(message: L("emr.loadFailed"))
            } else {
                if isPilotMode {
                    pilotBanner
                }
                if isAutoRetryPending, let scheduled = latest?.scheduledAt {
                    autoRetryBanner(scheduled: scheduled)
                }
                if isTerminalFailure {
                    terminalFailureBanner
                }

                actionBar

                if !rows.isEmpty {
                    Divider().background(Color.aurionBorder)
                    historyList
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
                .stroke(Color.aurionBorder, lineWidth: 1)
        )
        .task { await loadIfNeeded() }
        .onChange(of: sessionState) { newValue in
            if Self.approvedStates.contains(newValue) {
                Task { await loadIfNeeded() }
            }
        }
    }

    // MARK: Subviews

    private var header: some View {
        HStack(spacing: 8) {
            Image(systemName: "server.rack")
                .font(.system(size: 16))
                .foregroundColor(.aurionGold)
            Text(L("emr.title"))
                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.aurionTextPrimary)
            Spacer()
            if let sent = lastSent {
                Text(L("emr.lastSent", relativeTime(sent.createdAt)))
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(.aurionGreen)
            }
        }
    }

    private var gateNotice: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lock.fill")
                .font(.system(size: 12))
                .foregroundColor(.aurionTextSecondary)
            Text(L("emr.gateMessage"))
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
            Spacer()
        }
    }

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
                    Text(L("emr.retry"))
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

    private var pilotBanner: some View {
        amberBanner(
            icon: "exclamationmark.triangle.fill",
            title: L("emr.pilotMode"),
            detail: L("emr.pilotDetail")
        )
    }

    private func autoRetryBanner(scheduled: String) -> some View {
        amberBanner(
            icon: "arrow.up.circle.fill",
            title: L("emr.autoRetryHeader", relativeTime(scheduled)),
            detail: L("emr.autoRetryDetail")
        )
    }

    private var terminalFailureBanner: some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 13))
                .foregroundColor(.red)
            VStack(alignment: .leading, spacing: 2) {
                Text(L("emr.terminalHeader"))
                    .aurionFont(12, weight: .semibold, relativeTo: .caption)
                    .foregroundColor(.aurionTextPrimary)
                Text(L("emr.terminalDetail"))
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
        }
        .padding(10)
        .background(Color.red.opacity(0.08))
        .clipShape(RoundedRectangle(cornerRadius: 10))
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(Color.red.opacity(0.3), lineWidth: 1)
        )
    }

    private func amberBanner(
        icon: String,
        title: String,
        detail: String
    ) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Image(systemName: icon)
                .font(.system(size: 13))
                .foregroundColor(.aurionAmber)
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .aurionFont(12, weight: .semibold, relativeTo: .caption)
                    .foregroundColor(.aurionTextPrimary)
                Text(detail)
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

    private var actionBar: some View {
        HStack(spacing: 10) {
            if let connectors, connectors.available.count > 1 {
                connectorPicker(connectors: connectors)
            }
            sendButton
            Spacer()
        }
    }

    private func connectorPicker(connectors: EmrConnectorsResponse) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(L("emr.connectorLabel"))
                .aurionFont(10, weight: .semibold, relativeTo: .caption2)
                .foregroundColor(.aurionTextSecondary)
            Menu {
                ForEach(connectors.available, id: \.self) { key in
                    Button(key) { selectedConnector = key }
                }
            } label: {
                HStack(spacing: 4) {
                    Text(selectedConnector)
                        .aurionFont(12, weight: .medium, relativeTo: .caption)
                        .foregroundColor(.aurionTextPrimary)
                    Image(systemName: "chevron.down")
                        .font(.system(size: 9))
                        .foregroundColor(.aurionTextSecondary)
                }
                .padding(.horizontal, 10)
                .padding(.vertical, 6)
                .background(Color.aurionSurfaceAlt)
                .clipShape(Capsule())
            }
            .disabled(isSending)
        }
    }

    private var sendButton: some View {
        // Send is always enabled (clinician escape hatch). When an
        // auto-retry is queued, we degrade the variant to a ghost so
        // the primary visual affordance shifts to "wait for the
        // retry" — but allow the user to override with a brand-new
        // attempt row.
        Button {
            Task { await send() }
        } label: {
            HStack(spacing: 6) {
                if isSending {
                    ProgressView().tint(isAutoRetryPending ? .aurionTextPrimary : .aurionNavy)
                } else {
                    Image(systemName: "paperplane.fill")
                        .font(.system(size: 12, weight: .semibold))
                }
                Text(sendButtonLabel)
                    .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                    .foregroundColor(isAutoRetryPending ? .aurionTextPrimary : .aurionNavy)
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 8)
            .background(isAutoRetryPending ? Color.aurionSurfaceAlt : Color.aurionGold)
            .clipShape(Capsule())
        }
        .disabled(isSending)
    }

    private var sendButtonLabel: String {
        if isSending { return L("emr.sending") }
        if rows.isEmpty { return L("emr.send") }
        if isAutoRetryPending { return L("emr.sendFreshNow") }
        return L("emr.sendAgain")
    }

    private var historyList: some View {
        VStack(alignment: .leading, spacing: 6) {
            ForEach(rows) { row in
                writeBackRow(row)
                if row.id != rows.last?.id {
                    Divider().background(Color.aurionBorder)
                }
            }
        }
    }

    private func writeBackRow(_ row: EmrWriteBackResponse) -> some View {
        let isQueued = row.status == "failed" && (row.scheduledAt?.isEmpty == false)
        let isTerminal = row.status == "failed" && (row.scheduledAt == nil)

        return HStack(alignment: .top, spacing: 10) {
            statusIcon(for: row.status)
                .frame(width: 22)

            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    statusBadge(for: row.status)
                    Text(L("emr.viaConnector", row.connector))
                        .aurionFont(11, relativeTo: .caption2)
                        .foregroundColor(.aurionTextSecondary)
                    if row.attemptCount > 1 {
                        Text("\u{00B7}").foregroundColor(.aurionTextSecondary.opacity(0.4))
                        Text(L("emr.attemptCount", row.attemptCount))
                            .aurionFont(11, relativeTo: .caption2)
                            .foregroundColor(.aurionTextSecondary)
                    }
                    if isQueued {
                        retryQueuedPill
                    }
                    if isTerminal {
                        noMoreRetriesPill
                    }
                }

                if let externalId = row.externalId, !externalId.isEmpty,
                   externalId != "unknown-\(row.sessionId)" {
                    Text(L("emr.externalIdLabel", externalId))
                        .monospaced()
                        .aurionFont(11, relativeTo: .caption2)
                        .foregroundColor(.aurionTextPrimary)
                        .lineLimit(2)
                }

                if let reason = row.errorReason, !reason.isEmpty {
                    Text(reason)
                        .aurionFont(11, relativeTo: .caption2)
                        .foregroundColor(.aurionAmber)
                        .fixedSize(horizontal: false, vertical: true)
                }

                if isQueued, let scheduled = row.scheduledAt {
                    Text(L("emr.nextAttempt", relativeTime(scheduled)))
                        .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                        .foregroundColor(.aurionAmber)
                }

                HStack(spacing: 6) {
                    Text(relativeTime(row.createdAt))
                    Text("\u{00B7}").foregroundColor(.aurionTextSecondary.opacity(0.4))
                    // Fingerprint is a hex digest — monospace it (scales
                    // with the row via the HStack's aurionFont).
                    Text(L("emr.fingerprintLabel",
                            String(row.payloadFingerprint.prefix(12))))
                        .monospaced()
                }
                .aurionFont(10, relativeTo: .caption2)
                .foregroundColor(.aurionTextSecondary)
            }

            Spacer()
        }
        .padding(.vertical, 4)
    }

    // MARK: Chips + icons

    @ViewBuilder
    private func statusIcon(for status: String) -> some View {
        switch status {
        case "sent":
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 18))
                .foregroundColor(.aurionGreen)
        case "failed":
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 18))
                .foregroundColor(.aurionAmber)
        default:
            Image(systemName: "arrow.up.circle")
                .font(.system(size: 18))
                .foregroundColor(.aurionTextSecondary)
        }
    }

    @ViewBuilder
    private func statusBadge(for status: String) -> some View {
        switch status {
        case "queued":
            badge(text: L("emr.status.queued"), color: .aurionTextSecondary, filled: false)
        case "sending":
            badge(text: L("emr.status.sending"), color: .clinicalInfo, filled: true)
        case "sent":
            badge(text: L("emr.status.sent"), color: .aurionGreen, filled: true)
        case "failed":
            badge(text: L("emr.status.failed"), color: .aurionAmber, filled: false)
        default:
            EmptyView()
        }
    }

    private var retryQueuedPill: some View {
        Text(L("emr.retryQueued"))
            .aurionFont(9, weight: .semibold, relativeTo: .caption2)
            .foregroundColor(.aurionAmber)
            .padding(.horizontal, 5)
            .padding(.vertical, 2)
            .background(Color.aurionAmber.opacity(0.15))
            .clipShape(Capsule())
    }

    private var noMoreRetriesPill: some View {
        Text(L("emr.noMoreRetries"))
            .aurionFont(9, weight: .semibold, relativeTo: .caption2)
            .foregroundColor(.aurionTextSecondary)
            .padding(.horizontal, 5)
            .padding(.vertical, 2)
            .background(Color.aurionSurfaceAlt)
            .clipShape(Capsule())
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

    // MARK: Time helper

    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let isoPlain = ISO8601DateFormatter()
    private static let display: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .none
        f.timeStyle = .short
        return f
    }()
    private static let displayWithDate: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .short
        f.timeStyle = .short
        return f
    }()

    private func relativeTime(_ iso: String) -> String {
        guard let date = Self.isoFractional.date(from: iso)
            ?? Self.isoPlain.date(from: iso) else { return iso }
        // Same calendar day → just the time; else date + time.
        if Calendar.current.isDateInToday(date) {
            return Self.display.string(from: date)
        }
        return Self.displayWithDate.string(from: date)
    }

    // MARK: Actions

    private func loadIfNeeded() async {
        guard isApproved else { isLoading = false; return }
        isLoading = true
        async let history = APIClient.shared.listEmrWriteBacks(sessionId: sessionId)
        async let catalog = APIClient.shared.listEmrConnectors()
        do {
            let (h, c) = try await (history, catalog)
            rows = h
            connectors = c
            if !c.available.contains(selectedConnector) {
                selectedConnector = c.default
            }
            errorMessage = nil
            loadFailed = false
        } catch {
            loadFailed = true
            errorMessage = nil
        }
        isLoading = false
    }

    private func send() async {
        isSending = true
        errorMessage = nil
        defer { isSending = false }
        do {
            let row = try await APIClient.shared.sendEmrWriteBack(
                sessionId: sessionId,
                connector: selectedConnector
            )
            // Prepend for newest-first ordering — matches backend
            withAnimation(AurionAnimation.smooth) {
                rows = [row] + rows
            }
            if row.status == "failed" {
                AurionHaptics.notification(.warning)
                if let reason = row.errorReason, !reason.isEmpty {
                    errorMessage = reason
                } else {
                    errorMessage = L("emr.sendFailed")
                }
            } else {
                AurionHaptics.notification(.success)
            }
        } catch {
            AurionHaptics.notification(.error)
            errorMessage = L("emr.sendFailed")
        }
    }
}
