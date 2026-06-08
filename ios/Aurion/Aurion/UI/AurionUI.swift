import SwiftUI
import UIKit

// MARK: - Card
//
// Mirrors components.jsx Card: 16pt radius, 1px hairline border, two-layer
// soft shadow. Optional `accent` paints a 3pt gold left bar (used for the
// "Pending Review" card on the dashboard and the Active Device card).

struct AurionCard<Content: View>: View {
    var padding: CGFloat = 18
    var accent: Bool = false
    @ViewBuilder let content: () -> Content

    var body: some View {
        ZStack(alignment: .leading) {
            if accent {
                RoundedRectangle(cornerRadius: AurionRadius.lg)
                    .fill(Color.aurionGold)
                    .frame(width: 6)
                    .offset(x: -1.5)
            }
            content()
                .padding(padding)
                .frame(maxWidth: .infinity, alignment: .leading)
                .background(Color.aurionCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: AurionRadius.lg)
                        .stroke(Color.aurionBorder, lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: AurionRadius.lg))
        }
        .shadow(color: Color.aurionNavy.opacity(0.04), radius: 1, x: 0, y: 1)
        .shadow(color: Color.aurionNavy.opacity(0.06), radius: 16, x: 0, y: 4)
    }
}

// MARK: - Auth glass card + back bar
//
// Shared chrome for the auth gate screens (login, forgot-password,
// reset-password). `AuthGlassCard` is the frosted panel — white@6% fill,
// 18pt radius, white@10% hairline — that floats on the navy gradient those
// screens use as their *background* (the gradient is NOT part of the card).
// `AuthBackBar` is the leading chevron + "back to login" row above it; the
// label key is passed in so each screen keeps its own localized string.

struct AuthGlassCard<Content: View>: View {
    var padding: CGFloat = 24
    @ViewBuilder let content: () -> Content

    var body: some View {
        content()
            .padding(padding)
            .background(Color.white.opacity(0.06))
            .cornerRadius(18)
            .overlay(
                RoundedRectangle(cornerRadius: 18)
                    .stroke(Color.white.opacity(0.10), lineWidth: 1)
            )
    }
}

struct AuthBackBar: View {
    let label: String
    let onDismiss: () -> Void

    var body: some View {
        HStack {
            Button {
                AurionHaptics.selection()
                onDismiss()
            } label: {
                HStack(spacing: 6) {
                    Image(systemName: "chevron.left")
                    Text(label)
                }
                .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.white.opacity(0.8))
            }
            Spacer()
        }
        .padding(.horizontal, 24)
        .padding(.top, 20)
    }
}

// MARK: - Icon bubble
//
// Tinted circular halo behind an SF Symbol. Used everywhere we want a
// 36-64pt "status atom" — dashboard tiles, profile rows, export
// completion, the approved-note toast. The opacity (0.16) matches the
// tokens table; callers pass any aurion* color and a glyph name.

struct AurionIconBubble: View {
    let symbol: String
    let tint: Color
    var size: CGFloat = 44
    var symbolWeight: Font.Weight = .semibold

    var body: some View {
        ZStack {
            Circle().fill(tint.opacity(0.16))
            Image(systemName: symbol)
                .font(.system(size: size * 0.4, weight: symbolWeight))
                .foregroundColor(tint)
        }
        .frame(width: size, height: size)
    }
}

// MARK: - Buttons
//
// Three sizes per components.jsx GoldBtn (sm 8/16, md 14/22, lg 16/24).
// Optional leading icon (SF Symbol). `full` stretches to container width.

enum AurionButtonSize { case sm, md, lg }

struct AurionGoldButton: View {
    let label: String
    var icon: String? = nil
    var size: AurionButtonSize = .md
    var full: Bool = false
    var disabled: Bool = false
    let action: () -> Void

    @State private var pressed = false

    private var hPad: CGFloat { size == .lg ? 24 : (size == .sm ? 16 : 22) }
    private var vPad: CGFloat { size == .lg ? 16 : (size == .sm ? 8 : 14) }
    private var fontSize: CGFloat { size == .lg ? 17 : (size == .sm ? 14 : 16) }

    var body: some View {
        Button {
            guard !disabled else { return }
            AurionHaptics.impact(.medium)
            action()
        } label: {
            HStack(spacing: 8) {
                if let icon { Image(systemName: icon).font(.system(size: 18, weight: .semibold)) }
                Text(label).aurionFont(fontSize, weight: .semibold, relativeTo: .body)
            }
            // Brand-navy on gold — must stay fixed in both modes.
            // `aurionTextPrimary` (off-white on dark) would lose contrast.
            .foregroundColor(.aurionNavy)
            .padding(.horizontal, hPad)
            .padding(.vertical, vPad)
            .frame(maxWidth: full ? .infinity : nil)
            .background(Color.aurionGold)
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
            .shadow(color: Color.aurionNavy.opacity(0.04), radius: 1, x: 0, y: 1)
            .shadow(color: Color.aurionGold.opacity(0.24), radius: 16, x: 0, y: 4)
            .opacity(disabled ? 0.4 : 1)
            .scaleEffect(pressed ? 0.97 : 1)
            .animation(.easeOut(duration: AurionDuration.micro), value: pressed)
        }
        .buttonStyle(.plain)
        .pressEvents(onPress: { pressed = true }, onRelease: { pressed = false })
    }
}

struct AurionGhostButton: View {
    let label: String
    var full: Bool = false
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .aurionFont(16, weight: .semibold, relativeTo: .body)
                .foregroundColor(.aurionTextPrimary)
                .padding(.horizontal, 22)
                .padding(.vertical, 14)
                .frame(maxWidth: full ? .infinity : nil)
                .background(Color.aurionCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: AurionRadius.md)
                        // Adaptive border — was .aurionNavy.opacity(0.18), a
                        // fixed-dark hairline invisible on the dark card in
                        // dark mode (#293).
                        .stroke(Color.aurionBorder, lineWidth: 1)
                )
                .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
        }
        .buttonStyle(.plain)
    }
}

struct AurionTextButton: View {
    let label: String
    // Adaptive by default so nav-bar text buttons (Cancel/Back/Done) stay
    // visible in dark mode — was .aurionNavy, which rendered dark-on-dark
    // (#293). Callers on a navy/gold surface still pass an explicit color.
    var color: Color = .aurionTextPrimary
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(label)
                .aurionFont(16, weight: .medium, relativeTo: .body)
                .foregroundColor(color)
                // Nav-bar buttons (Cancel / Back / Done) must stay on one
                // line — at larger Dynamic Type "Cancel" was wrapping to
                // "Canc\nel" inside the fixed-width nav slot (#321). One line
                // at its natural width; AurionNavBar's minWidth slot grows to
                // fit instead of clipping.
                .lineLimit(1)
                .fixedSize(horizontal: true, vertical: false)
                .padding(.horizontal, 14)
                .padding(.vertical, 12)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Status Pill
//
// Mirrors components.jsx StatusBadge with the 6 documented kinds.
// Recording variant uses solid red background with white tracked-caps "REC" text.

enum AurionStatusKind {
    case done, pending, recording, archived, exported, conflict

    var label: String {
        switch self {
        case .done: return "Completed"
        case .pending: return "Pending"
        case .recording: return "REC"
        case .archived: return "Archived"
        case .exported: return "Exported"
        case .conflict: return "Review"
        }
    }

    var background: Color {
        switch self {
        case .done: return .aurionGreenBg
        case .pending: return .aurionGoldBg
        case .recording: return .aurionRed
        case .archived: return .aurionSurfaceAlt
        case .exported: return .aurionBlueBg
        case .conflict: return .aurionAmberBg
        }
    }

    var foreground: Color {
        switch self {
        case .done: return .aurionStatusDone
        case .pending: return .aurionStatusPending
        case .recording: return .white
        case .archived: return .aurionStatusArchived
        case .exported: return .aurionStatusExported
        case .conflict: return .aurionStatusConflict
        }
    }

    var dot: Color {
        switch self {
        case .done: return .aurionGreen
        case .pending: return .aurionGold
        case .recording: return .white
        case .archived: return Color.aurionMutedGray
        case .exported: return .aurionBlue
        case .conflict: return .aurionAmber
        }
    }

    var tracking: CGFloat { self == .recording ? 1.1 : 0.4 }
    var weight: Font.Weight { self == .recording ? .bold : .semibold }
}

struct AurionStatusPill: View {
    let kind: AurionStatusKind
    var labelOverride: String? = nil

    var body: some View {
        HStack(spacing: 6) {
            Circle().fill(kind.dot).frame(width: 6, height: 6)
            Text(labelOverride ?? kind.label)
                .aurionFont(11, weight: kind.weight, relativeTo: .caption2)
                .tracking(kind.tracking)
                // Single line + slight scale so the capsule caps its own width
                // at larger Dynamic Type — host rows lay it out as a fixed-ish
                // trailing badge and overflow would push siblings off (#271).
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .foregroundColor(kind.foreground)
        .padding(.horizontal, 10)
        .padding(.vertical, 4)
        .background(kind.background)
        .clipShape(Capsule())
    }
}

// MARK: - Avatar
//
// Initials on the gold radial gradient (#E5C97A → #B5953D, off-center
// highlight at 30% 30%). Initials sized to ~36% of the circle diameter.

struct AurionAvatar: View {
    let initials: String
    var size: CGFloat = 44

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    RadialGradient(
                        colors: [Color(red: 229/255, green: 201/255, blue: 122/255), .aurionGoldDark],
                        center: UnitPoint(x: 0.3, y: 0.3),
                        startRadius: 2,
                        endRadius: size * 0.7
                    )
                )
            Text(initials)
                .font(.system(size: size * 0.36, weight: .semibold))
                .tracking(-0.2)
                .foregroundColor(.white)
        }
        .frame(width: size, height: size)
        // Initials read as letters by default ("F. S."); the image trait
        // + descriptive label gives VoiceOver "Profile avatar" instead.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(L("a11y.profileAvatar"))
        .accessibilityAddTraits(.isImage)
    }
}

// MARK: - Progress bar (4pt rail, gold fill, ease-ios animation)

struct AurionProgressBar: View {
    let value: Double               // 0 ... 1
    var color: Color = .aurionGold
    var height: CGFloat = 4

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule().fill(Color.aurionSurfaceAlt)
                Capsule()
                    .fill(color)
                    .frame(width: geo.size.width * CGFloat(min(max(value, 0), 1)))
                    .animation(.aurionIOS, value: value)
            }
        }
        .frame(height: height)
    }
}

// MARK: - List Item (settings row)
//
// Used in Profile + Devices "Other Devices" cards. Optional leading SF
// Symbol, optional trailing value text, optional chevron when tappable.

struct AurionListItem: View {
    let title: String
    var icon: String? = nil
    var value: String? = nil
    var showChevron: Bool = true
    var last: Bool = false
    var action: (() -> Void)? = nil

    var body: some View {
        Button {
            action?()
        } label: {
            VStack(spacing: 0) {
                HStack(spacing: 12) {
                    if let icon {
                        Image(systemName: icon)
                            .font(.system(size: 18, weight: .regular))
                            .foregroundColor(.aurionTextPrimary)
                            .frame(width: 24)
                    }
                    // Title + value sit side-by-side at normal sizes; at larger
                    // Dynamic Type the one-line pair no longer fits, so they
                    // stack (title over value) instead of the value being
                    // squeezed flat and truncated (#271). The chevron lives
                    // inside both candidates so it stays pinned trailing.
                    ViewThatFits(in: .horizontal) {
                        HStack(spacing: 12) {
                            titleText
                            Spacer(minLength: 8)
                            valueText
                            trailingChevron
                        }
                        HStack(spacing: 12) {
                            VStack(alignment: .leading, spacing: 3) {
                                titleText
                                valueText
                            }
                            Spacer(minLength: 8)
                            trailingChevron
                        }
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 12)
                if !last {
                    Rectangle()
                        .fill(Color.aurionBorder)
                        .frame(height: 1)
                        .padding(.leading, 16)
                }
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(action == nil)
    }

    @ViewBuilder private var titleText: some View {
        Text(title)
            .aurionFont(16, relativeTo: .body)
            .foregroundColor(.aurionTextPrimary)
    }

    // Value keeps its single line and wins the layout tug-of-war (priority 1)
    // so the title yields space first within the side-by-side candidate (#271).
    @ViewBuilder private var valueText: some View {
        if let value {
            Text(value)
                .aurionFont(15, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)
                .lineLimit(1)
                .layoutPriority(1)
        }
    }

    @ViewBuilder private var trailingChevron: some View {
        if showChevron && action != nil {
            Image(systemName: "chevron.right")
                .font(.system(size: 14, weight: .semibold))
                .foregroundColor(Color.aurionMutedGray)
        }
    }
}

// MARK: - Field (text input with focused gold ring)
//
// Mirrors components.jsx Field. When focused, draws a 1pt gold border with
// a 30%-opacity gold halo. Multiline pushes min-height to 96pt.

struct AurionField: View {
    var label: String? = nil
    var placeholder: String = ""
    @Binding var text: String
    var multiline: Bool = false
    var contentType: UITextContentType? = nil
    var capitalization: TextInputAutocapitalization = .sentences
    var isSecure: Bool = false

    @FocusState private var focused: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            if let label {
                Text(label)
                    .aurionFont(13, weight: .medium, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
            }
            Group {
                if multiline {
                    TextEditor(text: $text)
                        .frame(minHeight: 96)
                        .scrollContentBackground(.hidden)
                        .padding(.vertical, 4)
                } else if isSecure {
                    SecureField(placeholder, text: $text)
                } else {
                    TextField(placeholder, text: $text)
                }
            }
            .focused($focused)
            .aurionFont(16, relativeTo: .body)
            .foregroundColor(.aurionTextPrimary)
            .padding(.horizontal, 14)
            .padding(.vertical, multiline ? 8 : 12)
            .background(Color.aurionCardBackground)
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.sm))
            .overlay(
                RoundedRectangle(cornerRadius: AurionRadius.sm)
                    // Adaptive unfocused border (was .aurionNavy.opacity(0.18),
                    // an invisible field outline in dark mode); gold focus
                    // ring unchanged (#293).
                    .stroke(focused ? Color.aurionGold : Color.aurionInputBorder, lineWidth: 1)
            )
            .overlay(
                RoundedRectangle(cornerRadius: AurionRadius.sm)
                    .stroke(focused ? Color.aurionGold.opacity(0.30) : .clear, lineWidth: 2)
                    .padding(-1)
            )
            .textInputAutocapitalization(capitalization)
            .textContentType(contentType)
        }
    }
}

// MARK: - Nav bar (in-app, not iOS chrome)
//
// 44pt min-height, centered title, leading + trailing slots. Used on every
// non-tab screen (Encounter Type, Pre-Encounter, Post-Encounter, Note Review).

struct AurionNavBar<Leading: View, Trailing: View>: View {
    let title: String
    @ViewBuilder let leading: () -> Leading
    @ViewBuilder let trailing: () -> Trailing

    var body: some View {
        // Side buttons take their natural width and never clip — the title is
        // overlaid centered across the whole bar so it no longer competes with
        // the buttons for horizontal space in the HStack flow at larger Dynamic
        // Type (#271, builds on the #321 minWidth fix). The buttons own the
        // flow (leading | Spacer | trailing); the title floats on top.
        HStack(spacing: AurionSpacing.xs) {
            leading()
            Spacer(minLength: AurionSpacing.xs)
            trailing()
        }
        .overlay(alignment: .center) {
            Text(title)
                .aurionFont(17, weight: .semibold, relativeTo: .headline)
                .foregroundColor(.aurionTextPrimary)
                // One line, scaled down (never overlapping the side buttons)
                // before it would ever truncate. The horizontal inset keeps a
                // long title clear of the leading/trailing buttons (#271).
                .lineLimit(1)
                .minimumScaleFactor(0.7)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 76)
                .allowsHitTesting(false)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 6)
        .frame(minHeight: AurionSpacing.topBar)
    }
}

extension AurionNavBar where Trailing == EmptyView {
    init(title: String, @ViewBuilder leading: @escaping () -> Leading) {
        self.title = title
        self.leading = leading
        self.trailing = { EmptyView() }
    }
}

// MARK: - Flow layout (wrapping chip rows)
//
// Lays children left-to-right, wrapping to a new row when the next child
// would overflow the proposed width. Used for chip rows (e.g. the encounter
// role chips) so the chips wrap onto a second row at larger Dynamic Type
// instead of being squeezed flat and truncated inside a single HStack (#271).
// iOS 16+ `Layout`.
struct AurionFlowLayout: Layout {
    var spacing: CGFloat = 8
    var lineSpacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout Void) -> CGSize {
        let maxWidth = proposal.width ?? .infinity
        let sizes = subviews.map { $0.sizeThatFits(.unspecified) }
        var rowWidth: CGFloat = 0
        var rowHeight: CGFloat = 0
        var totalHeight: CGFloat = 0
        var maxRowWidth: CGFloat = 0
        for size in sizes {
            if rowWidth > 0, rowWidth + spacing + size.width > maxWidth {
                totalHeight += rowHeight + lineSpacing
                maxRowWidth = max(maxRowWidth, rowWidth)
                rowWidth = size.width
                rowHeight = size.height
            } else {
                rowWidth += (rowWidth > 0 ? spacing : 0) + size.width
                rowHeight = max(rowHeight, size.height)
            }
        }
        totalHeight += rowHeight
        maxRowWidth = max(maxRowWidth, rowWidth)
        let width = maxWidth == .infinity ? maxRowWidth : maxWidth
        return CGSize(width: width, height: totalHeight)
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout Void) {
        let maxWidth = bounds.width
        var x = bounds.minX
        var y = bounds.minY
        var rowHeight: CGFloat = 0
        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)
            if x > bounds.minX, x + size.width > bounds.minX + maxWidth {
                x = bounds.minX
                y += rowHeight + lineSpacing
                rowHeight = 0
            }
            subview.place(at: CGPoint(x: x, y: y), anchor: .topLeading, proposal: ProposedViewSize(size))
            x += size.width + spacing
            rowHeight = max(rowHeight, size.height)
        }
    }
}

// MARK: - Filter chip (Sessions screen)

struct AurionFilterChip: View {
    let label: String
    let count: Int
    let active: Bool
    let action: () -> Void

    var body: some View {
        Button {
            AurionHaptics.selection()
            action()
        } label: {
            // Label + count badge sit on one line; if a long localized label
            // can't fit the count beside it (large Dynamic Type), the count
            // drops below instead of clipping. The chip rows that host this
            // already wrap/scroll (#358's AurionFlowLayout / the inbox's
            // horizontal scroll), so this is the within-chip safety net (#271).
            ViewThatFits(in: .horizontal) {
                HStack(spacing: 6) {
                    chipLabel
                    chipCountBadge
                }
                VStack(alignment: .leading, spacing: 2) {
                    chipLabel
                    chipCountBadge
                }
            }
            // Inactive: aurionTextPrimary (adaptive — navy in light, off-white in
            // dark) so the label reads against the dark card background. Hard-
            // coding .aurionNavy here meant dark-blue text on a dark-gray
            // card in dark mode — effectively invisible.
            .foregroundColor(active ? .white : .aurionTextPrimary)
            .padding(.horizontal, 14)
            .padding(.vertical, 7)
            .background(active ? Color.aurionNavy : Color.aurionCardBackground)
            .clipShape(Capsule())
            .overlay(
                Capsule().stroke(active ? .clear : Color.aurionBorder, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
        // Without this, VoiceOver reads the count badge as a separate
        // element ("12, button") with no relation to the filter label.
        // Combining flattens it to "Pending, 12 sessions, button".
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label), \(count) sessions")
        .accessibilityAddTraits(active ? [.isSelected, .isButton] : .isButton)
    }

    @ViewBuilder private var chipLabel: some View {
        Text(label)
            .aurionFont(13, weight: .semibold, relativeTo: .footnote)
            .lineLimit(1)
    }

    @ViewBuilder private var chipCountBadge: some View {
        Text("\(count)")
            .aurionFont(11, weight: .semibold, relativeTo: .caption2)
            .padding(.horizontal, 7)
            .padding(.vertical, 1)
            .background(active ? Color.white.opacity(0.18) : Color.aurionSurfaceAlt)
            .clipShape(Capsule())
    }
}

// MARK: - Soft-background icon tile (44/48pt rounded square — used in
// every selectable row card with an icon: Encounter Type, Profile Setup
// step 1, Devices "Active" card).

struct AurionIconTile: View {
    let systemName: String
    var size: CGFloat = 44
    var active: Bool = false

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: AurionRadius.md)
                .fill(active ? Color.aurionGoldBg : Color.aurionSurfaceAlt)
                .frame(width: size, height: size)
            Image(systemName: systemName)
                .font(.system(size: size * 0.5, weight: .regular))
                // Inactive uses .aurionTextPrimary (adaptive). Hardcoding
                // .aurionNavy made the icon invisible in dark mode against
                // the .aurionSurfaceAlt tile — same pattern as the filter
                // chip we just fixed.
                .foregroundColor(active ? .aurionGoldDark : .aurionTextPrimary)
        }
    }
}

// MARK: - Record button
//
// 78pt gold disc with navy square icon centered, surrounded by a 1.6s
// breathing halo (radial gold @ 30%/0%, scale 1 → 1.18, opacity 0.9 → 0.4).
// Tapping fires the supplied action; long-press fires the optional secondary.

struct AurionRecordButton: View {
    var diameter: CGFloat = 78
    var stopped: Bool = false
    let action: () -> Void

    @State private var pulsing = false

    var body: some View {
        ZStack {
            Circle()
                .fill(
                    RadialGradient(
                        colors: [Color.aurionGold.opacity(0.30), Color.aurionGold.opacity(0)],
                        center: .center,
                        startRadius: 0,
                        endRadius: diameter * 0.9
                    )
                )
                .frame(width: diameter * 1.6, height: diameter * 1.6)
                .scaleEffect(pulsing ? 1.18 : 1.0)
                .opacity(pulsing ? 0.4 : 0.9)

            Button(action: {
                AurionHaptics.impact(.heavy)
                action()
            }) {
                ZStack {
                    Circle()
                        .fill(Color.aurionGold)
                        .frame(width: diameter, height: diameter)
                        .shadow(color: Color.aurionGold.opacity(0.36), radius: 16, x: 0, y: 12)
                    if stopped {
                        Circle().fill(Color.aurionNavy).frame(width: diameter * 0.45, height: diameter * 0.45)
                    } else {
                        RoundedRectangle(cornerRadius: 6)
                            .fill(Color.aurionNavy)
                            .frame(width: diameter * 0.38, height: diameter * 0.38)
                    }
                }
            }
            .buttonStyle(.plain)
            .overlay(
                Circle()
                    .stroke(Color.aurionGold.opacity(0.18), lineWidth: 8)
                    .frame(width: diameter, height: diameter)
            )
        }
        .onAppear {
            withAnimation(.easeInOut(duration: 1.6).repeatForever(autoreverses: true)) {
                pulsing = true
            }
        }
    }
}

// MARK: - Bottom Sheet
//
// Lightweight wrapper for the design's draggable bottom sheet — adds the
// 36×5pt grabber, top-only 20pt corners, top-shadow. Use as a manual
// overlay; for system-driven sheets, prefer SwiftUI's `.presentationDetents`.

struct AurionBottomSheet<Content: View>: View {
    @ViewBuilder let content: () -> Content

    var body: some View {
        VStack(spacing: 14) {
            Capsule()
                // Adaptive grabber — was .aurionNavy.opacity(0.18), invisible
                // on the dark sheet in dark mode (#293).
                .fill(Color.aurionMutedGray.opacity(0.5))
                .frame(width: 36, height: 5)
                .padding(.top, 12)
            content()
                .padding(.horizontal, 20)
                .padding(.bottom, 28)
        }
        .frame(maxWidth: .infinity)
        .background(Color.aurionCardBackground)
        .clipShape(
            UnevenRoundedRectangle(
                topLeadingRadius: AurionRadius.xl,
                bottomLeadingRadius: 0,
                bottomTrailingRadius: 0,
                topTrailingRadius: AurionRadius.xl
            )
        )
        .shadow(color: Color.aurionNavy.opacity(0.12), radius: 32, x: 0, y: -8)
    }
}

// MARK: - Selectable Card Row
//
// Two-line option card with leading icon tile and optional trailing checkmark.
// Used for Encounter Type, Practice Type, and Language picker rows.

/// Selected-state indicator for ``AurionSelectableCard``.
enum AurionSelectionIndicator {
    /// Trailing gold check-circle — the icon-led cards (encounter type,
    /// practice type, capture mode).
    case circle
    /// Leading gold-fill + navy checkmark square — the label-only option
    /// lists (specialty, visit types, templates).
    case checkbox
}

struct AurionSelectableCard<Trailing: View>: View {
    // `icon` / `subtitle` are optional so the same card serves both the
    // icon-led two-line cards (icon + title + subtitle) and the label-only
    // option rows (title only). `indicator` picks the selected-state glyph.
    var icon: String? = nil
    let title: String
    var subtitle: String? = nil
    let selected: Bool
    var indicator: AurionSelectionIndicator = .circle
    @ViewBuilder let trailing: () -> Trailing
    let action: () -> Void

    var body: some View {
        Button {
            AurionHaptics.selection()
            action()
        } label: {
            HStack(spacing: 14) {
                if let icon {
                    AurionIconTile(systemName: icon, active: selected)
                }
                if indicator == .checkbox {
                    selectionCheckbox
                }
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .aurionFont(17, weight: .semibold, relativeTo: .headline)
                        .foregroundColor(.aurionTextPrimary)
                    if let subtitle {
                        Text(subtitle)
                            .aurionFont(13, relativeTo: .footnote)
                            .foregroundColor(.aurionTextSecondary)
                    }
                }
                Spacer(minLength: 0)
                if indicator == .circle, selected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 22))
                        .foregroundColor(.aurionGold)
                }
                trailing()
            }
            .padding(18)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.aurionCardBackground)
            .overlay(
                RoundedRectangle(cornerRadius: AurionRadius.lg)
                    .stroke(selected ? Color.aurionGold : Color.aurionBorder, lineWidth: selected ? 2 : 1)
            )
            .clipShape(RoundedRectangle(cornerRadius: AurionRadius.lg))
            .shadow(color: Color.aurionNavy.opacity(0.04), radius: 1, x: 0, y: 1)
            .shadow(color: Color.aurionNavy.opacity(0.06), radius: 16, x: 0, y: 4)
        }
        .buttonStyle(.plain)
    }

    /// Gold-fill + navy checkmark square — the leading indicator for
    /// `.checkbox` rows. Navy-on-gold is the brand pairing that stays
    /// high-contrast in both light and dark modes (an adaptive foreground
    /// washed out to white-on-gold in dark mode).
    private var selectionCheckbox: some View {
        ZStack {
            RoundedRectangle(cornerRadius: AurionRadius.xs)
                .fill(selected ? Color.aurionGold : Color.clear)
                .frame(width: 22, height: 22)
                .overlay(
                    RoundedRectangle(cornerRadius: AurionRadius.xs)
                        .stroke(selected ? Color.aurionGold : Color.aurionInputBorder, lineWidth: 2)
                )
            if selected {
                Image(systemName: "checkmark")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundColor(.aurionNavy)
            }
        }
    }
}

extension AurionSelectableCard where Trailing == EmptyView {
    init(
        icon: String? = nil,
        title: String,
        subtitle: String? = nil,
        selected: Bool,
        indicator: AurionSelectionIndicator = .circle,
        action: @escaping () -> Void
    ) {
        self.init(
            icon: icon,
            title: title,
            subtitle: subtitle,
            selected: selected,
            indicator: indicator,
            trailing: { EmptyView() },
            action: action
        )
    }
}

// MARK: - Press-event helper
//
// SwiftUI's Button doesn't surface press state on the standard plain style.
// This view modifier mimics components.jsx's onMouseDown/onMouseLeave pair
// using a DragGesture with min distance 0.

private struct PressActions: ViewModifier {
    let onPress: () -> Void
    let onRelease: () -> Void

    func body(content: Content) -> some View {
        content.simultaneousGesture(
            DragGesture(minimumDistance: 0)
                .onChanged { _ in onPress() }
                .onEnded { _ in onRelease() }
        )
    }
}

extension View {
    func pressEvents(onPress: @escaping () -> Void, onRelease: @escaping () -> Void) -> some View {
        modifier(PressActions(onPress: onPress, onRelease: onRelease))
    }
}

// MARK: - Motion primitives
//
// Premium, intentional motion for onboarding and key transitions. All
// honour the design rule "no bounces, no spring overshoots" — only the
// iOS cubic-bezier(0.32, 0.72, 0, 1) and ease-in-out for ambient loops.

/// Staggered fade + slight upward translate for sequential reveal of a
/// view's children. Order 0 fires first; each subsequent child is paced
/// `stride` seconds later. Used on every onboarding hero stack so titles,
/// body copy, and CTAs settle in calmly instead of all at once.
struct AurionStaggerModifier: ViewModifier {
    let order: Int
    var baseDelay: Double = 0.10
    var stride: Double = 0.12
    var travel: CGFloat = 14

    @State private var appeared = false

    func body(content: Content) -> some View {
        content
            .opacity(appeared ? 1 : 0)
            .offset(y: appeared ? 0 : travel)
            .animation(
                .timingCurve(0.32, 0.72, 0, 1, duration: 0.55)
                    .delay(baseDelay + Double(order) * stride),
                value: appeared
            )
            .onAppear { appeared = true }
    }
}

extension View {
    /// Stagger a child into view. `order` 0 first, increase per sibling.
    func aurionStagger(order: Int, baseDelay: Double = 0.10, stride: Double = 0.12) -> some View {
        modifier(AurionStaggerModifier(order: order, baseDelay: baseDelay, stride: stride))
    }
}

/// A slow gold halo that breathes behind a hero glyph. 2.4s cycle, soft
/// blur — should feel ambient, not insistent. Use on icons that anchor
/// an onboarding screen (mic, glasses, hex mark).
struct AurionBreathingGlow: ViewModifier {
    var color: Color = .aurionGold
    var radius: CGFloat = 28
    @State private var pulse = false

    func body(content: Content) -> some View {
        content
            .background(
                Circle()
                    .fill(color.opacity(0.22))
                    .blur(radius: radius)
                    .scaleEffect(pulse ? 1.18 : 0.92)
                    .opacity(pulse ? 0.85 : 0.45)
                    .animation(.easeInOut(duration: 2.4).repeatForever(autoreverses: true), value: pulse)
            )
            .onAppear { pulse = true }
    }
}

extension View {
    func aurionBreathingGlow(color: Color = .aurionGold, radius: CGFloat = 28) -> some View {
        modifier(AurionBreathingGlow(color: color, radius: radius))
    }
}

/// Three concentric rings that expand outward continuously. Used while
/// the wearable scanner is searching for a device — replaces the static
/// "scanning" UI with a felt sense of motion.
struct AurionRadarPulse<Content: View>: View {
    var color: Color = .aurionGold
    var maxScale: CGFloat = 2.2
    @ViewBuilder let core: () -> Content

    @State private var pulse = false

    var body: some View {
        ZStack {
            ForEach(0..<3, id: \.self) { i in
                Circle()
                    .stroke(color.opacity(0.35), lineWidth: 1.5)
                    .frame(width: 80, height: 80)
                    .scaleEffect(pulse ? maxScale : 0.6)
                    .opacity(pulse ? 0 : 0.85)
                    .animation(
                        .easeOut(duration: 2.0)
                            .repeatForever(autoreverses: false)
                            .delay(Double(i) * 0.5),
                        value: pulse
                    )
            }
            core()
        }
        .onAppear { pulse = true }
    }
}

/// A short rotating arc used as an "in-flight" indicator on top of a
/// progress ring. 1.6s rotation, single pass, repeats forever. Linear
/// easing reads as mechanical/precise rather than playful.
struct AurionOrbitArc: View {
    var size: CGFloat = 100
    var arcLength: Double = 0.16
    var color: Color = .aurionGold
    var lineWidth: CGFloat = 2.5

    @State private var rotation: Double = 0

    var body: some View {
        Circle()
            .trim(from: 0, to: arcLength)
            .stroke(color, style: StrokeStyle(lineWidth: lineWidth, lineCap: .round))
            .frame(width: size, height: size)
            .rotationEffect(.degrees(rotation))
            .onAppear {
                withAnimation(.linear(duration: 1.6).repeatForever(autoreverses: false)) {
                    rotation = 360
                }
            }
    }
}

/// Deterministic audio-reactive bar visualisation. Each bar's resting
/// height is a sine offset, scaled by the live audio level. Replaces the
/// per-render `CGFloat.random` jitter that was visually noisy.
struct AurionAudioBars: View {
    let level: Float                // 0 ... 1, linear
    var barCount: Int = 28
    var maxHeight: CGFloat = 40
    var minHeight: CGFloat = 4
    var spacing: CGFloat = 3
    var color: Color = .aurionGold

    @State private var phase: Double = 0

    var body: some View {
        HStack(alignment: .center, spacing: spacing) {
            ForEach(0..<barCount, id: \.self) { i in
                Capsule()
                    .fill(color)
                    .frame(width: 3, height: barHeight(i))
                    .opacity(0.85)
            }
        }
        .frame(height: maxHeight)
        .animation(.linear(duration: 0.08), value: level)
        .onAppear {
            // Phase drift gives a continuous "alive" feel even at low audio.
            withAnimation(.linear(duration: 8).repeatForever(autoreverses: false)) {
                phase = .pi * 6
            }
        }
    }

    private func barHeight(_ i: Int) -> CGFloat {
        // Soft envelope: edges shorter than middle.
        let t = Double(i) / Double(barCount - 1)
        let envelope = sin(t * .pi)
        let wave = (sin(phase + Double(i) * 0.45) + 1) / 2     // 0...1
        let liveLevel = max(0.05, Double(level))               // floor so something always shows
        let h = minHeight + CGFloat(envelope * wave * liveLevel) * (maxHeight - minHeight) * 1.6
        return min(maxHeight, max(minHeight, h))
    }
}

/// A checkmark that *draws itself* with a stroke trim on appear. Use on
/// success states (voice enrollment complete, etc.) instead of an instant
/// `checkmark.circle.fill` pop — feels earned rather than canned.
struct AurionAnimatedCheck: View {
    var size: CGFloat = 96
    var color: Color = .aurionGold

    @State private var ringTrim: CGFloat = 0
    @State private var checkTrim: CGFloat = 0

    var body: some View {
        ZStack {
            Circle()
                .fill(color.opacity(0.12))
                .frame(width: size, height: size)
            Circle()
                .trim(from: 0, to: ringTrim)
                .stroke(color, style: StrokeStyle(lineWidth: size * 0.06, lineCap: .round))
                .frame(width: size * 0.92, height: size * 0.92)
                .rotationEffect(.degrees(-90))

            // Checkmark path
            CheckShape()
                .trim(from: 0, to: checkTrim)
                .stroke(color, style: StrokeStyle(lineWidth: size * 0.08, lineCap: .round, lineJoin: .round))
                .frame(width: size * 0.46, height: size * 0.34)
        }
        .onAppear {
            withAnimation(.timingCurve(0.32, 0.72, 0, 1, duration: 0.55)) {
                ringTrim = 1
            }
            withAnimation(.timingCurve(0.32, 0.72, 0, 1, duration: 0.40).delay(0.30)) {
                checkTrim = 1
            }
        }
    }

    private struct CheckShape: Shape {
        func path(in rect: CGRect) -> Path {
            var p = Path()
            p.move(to: CGPoint(x: rect.minX, y: rect.midY))
            p.addLine(to: CGPoint(x: rect.minX + rect.width * 0.38, y: rect.maxY))
            p.addLine(to: CGPoint(x: rect.maxX, y: rect.minY + rect.height * 0.05))
            return p
        }
    }
}

// MARK: - Session state → status kind

/// Maps the backend session-state machine to the design system's six status
/// kinds. Used by Dashboard, Sessions inbox, and Note Review.
func sessionStateKind(_ state: String) -> AurionStatusKind {
    switch state {
    case "EXPORTED": return .exported
    case "REVIEW_COMPLETE": return .done
    case "PURGED": return .archived
    case "AWAITING_REVIEW", "PROCESSING_STAGE1", "PROCESSING_STAGE2": return .pending
    case "RECORDING": return .recording
    case "PAUSED", "CONSENT_PENDING": return .pending
    default: return .archived
    }
}

/// Human-readable label for a session-state kind, separate from the default
/// kind label so we can show "Awaiting review" rather than "Pending" etc.
func sessionStateLabel(_ state: String) -> String {
    switch state {
    case "EXPORTED": return L("state.exported")
    case "REVIEW_COMPLETE": return L("state.completed")
    case "PURGED": return L("state.archived")
    case "AWAITING_REVIEW": return L("state.pendingReview")
    case "PROCESSING_STAGE1", "PROCESSING_STAGE2": return L("state.processing")
    case "RECORDING": return L("state.rec")
    case "PAUSED": return L("state.paused")
    case "CONSENT_PENDING": return L("state.consent")
    default: return state.replacingOccurrences(of: "_", with: " ").capitalized
    }
}
