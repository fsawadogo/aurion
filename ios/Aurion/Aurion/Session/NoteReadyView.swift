import SwiftUI

/// Shown after processing completes — physician chooses to review now or save for later.
/// Design: centered icon with gold bg + shadow, "Note ready" title, two buttons.
struct NoteReadyView: View {
    @EnvironmentObject var sessionManager: SessionManager

    var body: some View {
        ZStack {
            Color.aurionBackground.ignoresSafeArea()

            VStack(spacing: 0) {
                Spacer()

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
                    .font(.system(size: 28, weight: .semibold))
                    .tracking(-0.3)
                    .foregroundColor(.aurionTextPrimary)
                    .padding(.top, 18)

                Text(L("noteReady.subtitle"))
                    .font(.system(size: 15))
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .lineSpacing(3)
                    .frame(maxWidth: 280)
                    .padding(.top, 8)

                Spacer()

                // Buttons
                VStack(spacing: 10) {
                    AurionGoldButton(label: L("noteReady.reviewNow"), full: true) {
                        sessionManager.showingReview = true
                    }
                    AurionGhostButton(label: L("noteReady.saveLater"), full: true) {
                        sessionManager.saveForLater()
                    }
                }
                .padding(.horizontal, 24)
                .padding(.bottom, 28)
            }
        }
    }
}
