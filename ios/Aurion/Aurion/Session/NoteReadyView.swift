import SwiftUI

/// Shown after processing completes — physician chooses to review now or save for later.
/// Design: centered icon with gold bg + shadow, "Note ready" title, two buttons.
struct NoteReadyView: View {
    @EnvironmentObject var sessionManager: SessionManager

    /// One-line note summary built from the already-fetched Stage 1 note.
    /// `fetchNote()` runs before `uiState` flips to `.noteReady`, so
    /// `sessionManager.note` is populated by the time this screen shows; nil
    /// only on the rare path where the note never loaded — we hide the line.
    private var noteSummary: String? {
        guard let note = sessionManager.note else { return nil }
        let sectionCount = note.sections.count
        guard sectionCount > 0 else { return nil }

        let sectionsText = Lplural("noteReady.sectionCount", sectionCount)

        // Unresolved Stage 2 conflicts use the same definition as
        // NoteReviewView: a "conflict_"-prefixed claim the physician hasn't
        // yet edited. These block approval, so they lead the summary.
        let conflictCount = note.sections.reduce(0) { acc, section in
            acc + section.claims.filter {
                $0.id.hasPrefix("conflict_") && !$0.physicianEdited
            }.count
        }

        let detail: String
        if conflictCount > 0 {
            detail = Lplural("noteReady.needsReview", conflictCount)
        } else {
            let pct = Int((note.completenessScore * 100).rounded())
            detail = L("noteReady.completePct", pct)
        }
        return "\(sectionsText) \u{00B7} \(detail)"
    }

    var body: some View {
        ZStack {
            Color.aurionBackground.ignoresSafeArea()

            // Wrap the centered layout in a ScrollView pinned to at least the
            // container height: it stays vertically centered when everything
            // fits, but at larger Dynamic Type the content grows past the
            // screen and the Review-now / Save-for-later buttons would clip
            // off the bottom — scrolling keeps both reachable (#271 DT).
            GeometryReader { proxy in
                ScrollView {
                    VStack(spacing: 0) {
                        Spacer(minLength: 0)

                        // Icon with gold background and shadow
                        ZStack {
                    RoundedRectangle(cornerRadius: 24)
                        .fill(Color.aurionGoldBg)
                        .frame(width: 96, height: 96)
                        .shadow(
                            color: Color.aurionGold.opacity(0.20),
                            radius: 16, x: 0, y: 6
                        )
                    Image(systemName: "doc.text.fill")
                        .font(.system(size: 44))
                        .foregroundColor(.aurionGoldDark)
                }

                Text(L("noteReady.title"))
                    .aurionFont(28, weight: .semibold, relativeTo: .title)
                    .tracking(-0.3)
                    .foregroundColor(.aurionTextPrimary)
                    .padding(.top, 18)

                Text(L("noteReady.subtitle"))
                    .aurionFont(15, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
                    .frame(maxWidth: 280)
                    .padding(.top, 8)

                // One-line summary of the generated note so the review-now vs
                // save-for-later choice has context (#300). Surfaces conflicts
                // when present (they need attention), else completeness.
                if let summary = noteSummary {
                    Text(summary)
                        .aurionFont(13, weight: .medium, relativeTo: .footnote)
                        .foregroundColor(.aurionTextSecondary)
                        .multilineTextAlignment(.center)
                        .frame(maxWidth: 280)
                        .padding(.top, 8)
                        .accessibilityLabel(summary)
                }

                        Spacer(minLength: 0)

                        // Buttons
                        VStack(spacing: 10) {
                            AurionGoldButton(label: L("noteReady.reviewNow"), full: true) {
                                sessionManager.beginReview()
                            }
                            AurionGhostButton(label: L("noteReady.saveLater"), full: true) {
                                sessionManager.saveForLater()
                            }
                        }
                        .padding(.horizontal, 24)
                        .padding(.bottom, 28)
                    }
                    // Pin to at least the container height so the content stays
                    // vertically centered when it fits and the ScrollView only
                    // engages once it overflows at larger Dynamic Type (#271 DT).
                    .frame(maxWidth: .infinity, minHeight: proxy.size.height)
                }
            }
        }
    }
}
