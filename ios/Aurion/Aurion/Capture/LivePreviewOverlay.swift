import SwiftUI

/// Live preview overlay on CaptureView (#64) — surfaces the draft
/// note as it assembles mid-encounter.
///
/// Mounts during RECORDING and PAUSED states. iOS owns the cadence:
/// the overlay timer fires every `tickSeconds` (default 30s), pulls
/// the current partial transcript from the live transcriber, and
/// POSTs to `/me/sessions/{id}/preview`. Server returns a draft
/// snapshot; we render the populated sections.
///
/// Mirrors the portal's `<LivePreviewCard />` from #170 in
/// visual treatment + the safety properties that protect against
/// physicians mistaking the preview for the canonical note:
///
///   * Bright "DRAFT" badge at the top — every render reminds the
///     physician this is not the final note
///   * Amber-tinted card border so the surface reads as different
///     from the gold-accented finals
///   * Sections render only when `status == "populated"` — empty
///     / pending sections are misleading mid-recording
///   * Collapse / expand toggle for the physician who wants the
///     captioned interface back to its original layout
///
/// ## Cadence + lifecycle
///
/// The first preview only fires once we have at least
/// `minTranscriptChars` of partial transcript — generating off
/// nothing wastes an LLM call and produces an empty snapshot.
/// Subsequent ticks always fire on the timer; the server's
/// idempotency comes from per-call versioning (each request creates
/// a new row).
///
/// We don't auto-refresh on transcript change because the cadence
/// should be predictable for the physician (and predictable cost-
/// per-encounter for the operator). The Refresh button gives
/// manual override.
///
/// ## PHI
///
/// The preview body IS PHI. We never log it. The overlay's
/// rendering is on-screen only — same surface area as the existing
/// captionStrip which already shows partial transcript text in the
/// same context.
struct LivePreviewOverlay: View {
    let sessionId: String
    /// Live partial transcript text. Bind to `LiveTranscriber.transcript`
    /// or whatever surface produces the mid-encounter text the
    /// backend should preview against.
    let partialTranscript: String
    /// Language for the generated preview body. Defaults to "en"
    /// (matches PostEncounterView's default).
    let outputLanguage: String

    /// Polling cadence. Default 30s — short enough that the preview
    /// feels live, long enough that LLM cost stays bounded.
    var tickSeconds: Double = 30
    /// Defer first generation until we have at least this many
    /// transcript characters. Below this, the preview would emit
    /// an empty snapshot and waste an LLM call.
    var minTranscriptChars: Int = 200

    @State private var preview: LivePreviewResponse?
    @State private var isGenerating = false
    @State private var errorMessage: String?
    @State private var isCollapsed = true
    @State private var tickTask: Task<Void, Never>?

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            if !isCollapsed {
                content
            }
        }
        .padding(12)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color.aurionAmber.opacity(0.10))
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(Color.aurionAmber.opacity(0.45), lineWidth: 1)
        )
        .onAppear { startTickLoop() }
        .onDisappear { stopTickLoop() }
    }

    // MARK: Subviews

    private var header: some View {
        Button {
            withAnimation(AurionAnimation.smooth) { isCollapsed.toggle() }
        } label: {
            HStack(spacing: 8) {
                Image(systemName: "doc.text.below.ecg")
                    .font(.system(size: 14))
                    .foregroundColor(.aurionAmber)
                Text(L("preview.title"))
                    .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                    .foregroundColor(.aurionTextPrimary)
                draftBadge
                if let p = preview {
                    Text(L("preview.versionMeta", p.version, relativeTime(p.createdAt)))
                        .aurionFont(10, relativeTo: .caption2)
                        .foregroundColor(.aurionTextSecondary)
                }
                Spacer()
                if isGenerating {
                    ProgressView().tint(.aurionAmber)
                }
                Image(systemName: isCollapsed ? "chevron.down" : "chevron.up")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundColor(.aurionTextSecondary)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityLabel(Text(isCollapsed
                                  ? L("preview.expand")
                                  : L("preview.collapse")))
    }

    private var draftBadge: some View {
        Text(L("preview.draftBadge"))
            .font(.system(size: 9, weight: .bold))
            .tracking(0.8)
            .foregroundColor(.white)
            .padding(.horizontal, 5)
            .padding(.vertical, 2)
            .background(Color.aurionAmber)
            .clipShape(Capsule())
    }

    @ViewBuilder
    private var content: some View {
        // Always-visible disclaimer when expanded.
        HStack(alignment: .top, spacing: 6) {
            Image(systemName: "exclamationmark.triangle.fill")
                .font(.system(size: 10))
                .foregroundColor(.aurionAmber)
                .padding(.top, 2)
            Text(L("preview.disclaimer"))
                .aurionFont(10, relativeTo: .caption2)
                .foregroundColor(.aurionTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.bottom, 4)

        if let msg = errorMessage {
            Text(msg)
                .aurionFont(10, relativeTo: .caption2)
                .foregroundColor(.red)
                .padding(.vertical, 2)
        }

        if partialTranscript.count < minTranscriptChars && preview == nil {
            // First-tick waiting state. Once we have a preview, even
            // if the transcript later shrinks (shouldn't, but defensive),
            // we keep showing the last known body.
            Text(L("preview.noTranscript"))
                .aurionFont(11, relativeTo: .caption2)
                .foregroundColor(.aurionTextSecondary)
                .italic()
                .padding(.vertical, 4)
        } else if let p = preview {
            sections(for: p)
            HStack {
                Spacer()
                refreshButton
            }
            .padding(.top, 2)
        } else if isGenerating {
            Text(L("preview.refreshing"))
                .aurionFont(11, relativeTo: .caption2)
                .foregroundColor(.aurionTextSecondary)
        } else {
            Text(L("preview.waiting"))
                .aurionFont(11, relativeTo: .caption2)
                .foregroundColor(.aurionTextSecondary)
        }
    }

    private func sections(for p: LivePreviewResponse) -> some View {
        // Mid-recording, only `populated` sections are meaningful —
        // `not_captured` and `pending_video` are misleading because
        // the canonical pipeline hasn't tried yet.
        let visible = p.sections.filter {
            $0.status == "populated" && !$0.claims.isEmpty
        }
        return VStack(alignment: .leading, spacing: 10) {
            if visible.isEmpty {
                Text(L("preview.waiting"))
                    .aurionFont(11, relativeTo: .caption2)
                    .foregroundColor(.aurionTextSecondary)
                    .italic()
            } else {
                ForEach(visible, id: \.id) { section in
                    sectionBlock(section)
                }
            }
        }
    }

    private func sectionBlock(_ section: LivePreviewSectionPayload) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            Text((section.title ?? section.id.replacingOccurrences(of: "_", with: " "))
                    .capitalized)
                .aurionFont(11, weight: .semibold, relativeTo: .caption)
                .foregroundColor(.aurionTextPrimary)
                .textCase(.uppercase)
                .tracking(0.4)
            ForEach(section.claims, id: \.id) { claim in
                Text(claim.text)
                    .aurionFont(12, relativeTo: .caption)
                    .foregroundColor(.aurionTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
        }
        .padding(8)
        .background(
            RoundedRectangle(cornerRadius: 8, style: .continuous)
                .fill(Color.aurionCardBackground.opacity(0.85))
        )
    }

    private var refreshButton: some View {
        Button {
            Task { await runTick(force: true) }
        } label: {
            HStack(spacing: 4) {
                Image(systemName: "arrow.clockwise")
                    .font(.system(size: 10, weight: .semibold))
                Text(isGenerating ? L("preview.refreshing") : L("preview.refresh"))
                    .aurionFont(11, weight: .semibold, relativeTo: .caption2)
            }
            .foregroundColor(.aurionTextPrimary)
            .padding(.horizontal, 9)
            .padding(.vertical, 5)
            .background(Color.aurionSurfaceAlt)
            .clipShape(Capsule())
        }
        .disabled(isGenerating)
    }

    // MARK: Cadence

    private func startTickLoop() {
        tickTask?.cancel()
        tickTask = Task {
            // Kick off an immediate tick so the first preview lands as
            // soon as the transcript clears `minTranscriptChars`,
            // not 30s after the overlay appears.
            await runTick(force: false)
            while !Task.isCancelled {
                do {
                    try await Task.sleep(
                        nanoseconds: UInt64(tickSeconds * 1_000_000_000)
                    )
                } catch {
                    break
                }
                if Task.isCancelled { break }
                await runTick(force: false)
            }
        }
    }

    private func stopTickLoop() {
        tickTask?.cancel()
        tickTask = nil
    }

    private func runTick(force: Bool) async {
        // Below the minimum transcript threshold AND not a manual
        // refresh → skip. Manual refresh always fires (the physician
        // may want to force a preview against whatever's available).
        guard force || partialTranscript.count >= minTranscriptChars else {
            return
        }
        // Guard against overlapping LLM calls — a slow upstream
        // could otherwise stack ticks.
        guard !isGenerating else { return }
        // Snapshot the transcript so a later mutation doesn't change
        // the body between the call and the return.
        let snapshot = partialTranscript
        guard !snapshot.isEmpty else {
            errorMessage = L("preview.noTranscript")
            return
        }
        isGenerating = true
        defer { isGenerating = false }
        do {
            let p = try await APIClient.shared.generateLivePreview(
                sessionId: sessionId,
                partialTranscript: snapshot,
                outputLanguage: outputLanguage
            )
            preview = p
            errorMessage = nil
        } catch {
            // Errors here aren't user-actionable beyond "wait and
            // retry on next tick." Surface a small notice but keep
            // the last known preview visible if we had one.
            errorMessage = L("preview.failed")
        }
    }

    // MARK: Time helpers

    private static let isoFractional: ISO8601DateFormatter = {
        let f = ISO8601DateFormatter()
        f.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return f
    }()
    private static let isoPlain = ISO8601DateFormatter()
    private static let timeOnly: DateFormatter = {
        let f = DateFormatter()
        f.dateStyle = .none
        f.timeStyle = .short
        return f
    }()

    private func relativeTime(_ iso: String) -> String {
        guard let date = Self.isoFractional.date(from: iso)
            ?? Self.isoPlain.date(from: iso) else { return iso }
        return Self.timeOnly.string(from: date)
    }
}
