import SwiftUI

/// Reusable citation chip surfaced under each prose paragraph in the
/// reviewer's `sourcesPanel`. Replaces the prior hand-rolled HStack so
/// every per-claim source row gets identical visual treatment — and so
/// the dual-mode clip indicator has a single owner instead of being
/// scattered across the sources panel + (eventual) other surfaces.
///
/// ## Anatomy
///
/// ```
///   ┌──┐ seg_001  EDITED
///   │T │
///   └──┘
///   "tender medial joint line"
/// ```
///
/// For clip-kind evidence, a small `play.triangle.fill` overlay sits at
/// the trailing-bottom of the source-type badge. The overlay is
/// `aurionNavy` on the `aurionGold`/`aurionTextSecondary` badge — the
/// "navy on gold" pattern documented in the design memory as the
/// pilot's safe-contrast default for adaptive surfaces.
///
/// ## Design system tokens
///
/// All colours come from `Theme.swift`. Typography uses `.aurionFont`
/// so Dynamic Type honours the user's text-size preference (per memory
/// `reference_dynamic_type_aurionfont`); the icon overlay stays on
/// `.system(size:)` so it doesn't bloat the badge at AX text sizes
/// (icons stay fixed by policy).
///
/// ## Tap behaviour
///
/// `onTap` fires for chips whose backing evidence supports a tap-through.
/// Today that's `.clip` only — frame chips render the indicator-free
/// design and remain non-tappable, matching the reviewer's current
/// behaviour (no still-image viewer in the note review surface yet).
/// The button styling is `.plain` so tappability is signalled by the
/// chip itself, not by a system button frame.
struct CitationChip: View {
    let claim: NoteClaimResponse
    /// Called when the chip is tapped AND the chip is tappable
    /// (`.clip` kind on a `visual`-sourced claim). nil = no-op.
    var onTap: (() -> Void)?

    /// True only when the backing evidence is a playable clip AND the
    /// source claim is a visual citation. Guards against malformed
    /// payloads where evidence_kind=clip somehow lands on a transcript
    /// or screen row.
    private var isClipKind: Bool {
        claim.evidenceKind == .clip && claim.sourceType == "visual"
    }

    /// One-letter source-type code (T/V/S/E/?). Lifted verbatim from
    /// the prior inline implementation in `NoteReviewView.swift` so the
    /// chip swap is a pure refactor on the existing fixtures.
    private var sourceBadge: String {
        switch claim.sourceType {
        case "transcript":     return "T"
        case "visual":         return "V"
        case "screen":         return "S"
        case "physician_edit": return "E"
        default:               return "?"
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            HStack(spacing: 6) {
                badge
                Text(claim.sourceId)
                    .font(.system(size: 10, weight: .semibold))
                    .tracking(0.4)
                    .foregroundColor(.aurionTextSecondary)
                if claim.physicianEdited {
                    Text(L("noteReview.editedBadge"))
                        .font(.system(size: 9, weight: .bold))
                        .tracking(0.5)
                        .foregroundColor(.aurionGold)
                }
            }
            if !claim.sourceQuote.isEmpty {
                Text("\u{201C}\(claim.sourceQuote)\u{201D}")
                    .aurionFont(13, relativeTo: .footnote).italic()
                    .foregroundColor(.aurionTextSecondary)
                    .lineSpacing(2)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            // Only tappable when there's a tap target; frame chips are
            // a no-op visually + behaviourally so the user gets no
            // misleading affordance.
            guard isClipKind, let onTap else { return }
            AurionHaptics.selection()
            onTap()
        }
    }

    /// The 14-pt rounded square that carries the source-type letter,
    /// plus a play-triangle overlay for clip-kind evidence.
    @ViewBuilder
    private var badge: some View {
        ZStack(alignment: .bottomTrailing) {
            Text(sourceBadge)
                .font(.system(size: 9, weight: .bold))
                // On the fixed-gold clip badge use fixed navy (crisp in both
                // modes); the neutral-grey badge keeps the adaptive letter.
                // Was always .aurionBackground, which washed out on gold (#293).
                .foregroundColor(isClipKind ? .aurionNavy : .aurionBackground)
                .frame(width: 14, height: 14)
                .background(badgeFill)
                .clipShape(RoundedRectangle(cornerRadius: 3))
            if isClipKind {
                clipIndicator
                    // Sit it half-off the badge so the triangle is
                    // visible but doesn't crowd the letter underneath.
                    .offset(x: 3, y: 3)
            }
        }
        // Lift the badge accessibility into a single value so VoiceOver
        // doesn't read "T... clip indicator..." as two siblings.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(badgeAccessibilityLabel)
    }

    /// Clip chips use the gold treatment to signal "richer evidence";
    /// frame and other chips keep the neutral grey backdrop they've had
    /// since the reviewer shipped.
    private var badgeFill: Color {
        isClipKind ? .aurionGold : .aurionTextSecondary
    }

    /// 10-pt play triangle. Fixed-size per policy: SF Symbol overlays
    /// don't scale with Dynamic Type, and a play indicator that grows
    /// at AX5 swamps the chip it's anchored to.
    private var clipIndicator: some View {
        Image(systemName: "play.triangle.fill")
            .font(.system(size: 10, weight: .semibold))
            .foregroundColor(.aurionNavy)
            // White rim so the triangle reads on both navy-and-gold
            // (dark mode card backgrounds) and white-and-gold (light
            // mode). Without the rim the navy triangle can blur into
            // the navy card border on dark mode.
            .padding(1)
            .background(
                Circle().fill(Color.white.opacity(0.9))
            )
            .accessibilityHidden(true)
    }

    private var badgeAccessibilityLabel: String {
        let baseLabel: String
        switch claim.sourceType {
        case "transcript":     baseLabel = L("citation.sourceType.transcript")
        case "visual":         baseLabel = L("citation.sourceType.visual")
        case "screen":         baseLabel = L("citation.sourceType.screen")
        case "physician_edit": baseLabel = L("citation.sourceType.physicianEdit")
        default:               baseLabel = L("citation.sourceType.unknown")
        }
        if isClipKind {
            return "\(baseLabel) \u{00B7} \(L("clip.indicator.accessibility"))"
        }
        return baseLabel
    }
}
