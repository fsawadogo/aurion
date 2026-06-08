import SwiftUI

/// A 6-cell TOTP code input used by both ``MfaChallengeView`` and the
/// confirm phase of ``MfaSetupView``. One component so the validation rule
/// ("exactly six ASCII digits") and the visual treatment live in a single
/// place — bumping the cell count or the keyboard type only ever touches
/// one file.
///
/// The actual editing surface is a hidden numeric text field underneath
/// six tap targets; SwiftUI focus state pushes the keyboard up when any
/// cell is tapped. This mirrors the iOS system 2FA-code prompt and works
/// cleanly with Dynamic Type and VoiceOver (the field has its own label).
struct TotpCodeField: View {
    @Binding var code: String
    /// Fires the moment the user enters the sixth digit. Caller submits
    /// — no separate "verify" button required when the form is just this
    /// + a primary action.
    var onComplete: (() -> Void)? = nil
    /// Light/dark text contrast — challenge view ships on the navy
    /// gradient (white digits), setup view ships in the same context.
    var tint: Color = .aurionGold
    var digitColor: Color = .white
    /// Bump this from the caller (e.g. after clearing the code on a bad-code
    /// error) to re-assert keyboard focus. `onAppear` only fires once, so a
    /// still-mounted field whose keyboard was dismissed needs an explicit
    /// nudge — changing this value drives `onChange` below.
    var resetToken: Int = 0

    @FocusState private var focused: Bool

    /// #271 DT: the cell box grows vertically with Dynamic Type so a larger
    /// digit has room. Width stays fixed (see `cell(at:)`) so all six cells
    /// always fit on one row on the narrowest supported device; the digit's
    /// `minimumScaleFactor` keeps it legible within that fixed width.
    @ScaledMetric(relativeTo: .title3) private var cellHeight: CGFloat = 54

    /// Cognito TOTP codes are always 6 ASCII digits. Centralizing the
    /// rule keeps the verify button enablement, the auto-submit trigger,
    /// and the input filter consistent.
    static let codeLength = 6

    /// Normalize incoming input — strip non-digits and clamp length so
    /// pasted Authenticator-app suggestions ("123 456") just work.
    static func sanitize(_ raw: String) -> String {
        let digits = raw.unicodeScalars.filter { CharacterSet.decimalDigits.contains($0) }
        let trimmed = String(String.UnicodeScalarView(digits.prefix(codeLength)))
        return trimmed
    }

    static func isComplete(_ code: String) -> Bool {
        code.count == codeLength && code.allSatisfy { $0.isASCII && $0.isNumber }
    }

    var body: some View {
        ZStack {
            // Hidden editor — receives focus, takes keyboard input.
            TextField("", text: Binding(
                get: { code },
                set: { newValue in
                    let cleaned = Self.sanitize(newValue)
                    code = cleaned
                    if cleaned.count == Self.codeLength {
                        onComplete?()
                    }
                }
            ))
            .keyboardType(.numberPad)
            .textContentType(.oneTimeCode)
            .focused($focused)
            .opacity(0.001)   // present but invisible — keeps the keyboard wired
            .frame(width: 1, height: 1)
            .accessibilityLabel(L("login.mfa.challenge.codeLabel"))
            // The six visible cells are decorative duplicates of this
            // field's value — report progress here so VoiceOver lands on a
            // single meaningful element instead of six empty cells.
            .accessibilityValue(L("login.mfa.challenge.codeProgress", code.count, Self.codeLength))

            HStack(spacing: 10) {
                ForEach(0..<Self.codeLength, id: \.self) { idx in
                    cell(at: idx)
                }
            }
            .accessibilityHidden(true)
        }
        .contentShape(Rectangle())
        .onTapGesture { focused = true }
        .onAppear { focused = true }
        .onChange(of: resetToken) { _ in
            // Toggle through `false` so SwiftUI registers the change even if
            // `focused` is already true in its own state but the keyboard was
            // dismissed — re-presents the keypad without a manual tap.
            focused = false
            DispatchQueue.main.async { focused = true }
        }
    }

    private func cell(at index: Int) -> some View {
        let chars = Array(code)
        let char = index < chars.count ? String(chars[index]) : ""
        let isCursor = (index == chars.count) && focused
        return Text(char.isEmpty ? " " : char)
            .aurionFont(22, weight: .semibold, relativeTo: .title3)
            .lineLimit(1)
            .minimumScaleFactor(0.6)
            .frame(width: 44, height: cellHeight)
            .foregroundColor(digitColor)
            .background(Color.white.opacity(0.08))
            .cornerRadius(10)
            .overlay(
                RoundedRectangle(cornerRadius: 10)
                    .stroke(
                        isCursor ? tint : Color.white.opacity(char.isEmpty ? 0.10 : 0.25),
                        lineWidth: isCursor ? 1.6 : 1
                    )
            )
            .animation(AurionAnimation.micro, value: code)
            .animation(AurionAnimation.micro, value: focused)
    }
}
