import SwiftUI

/// Step-by-step guide for connecting and using Ray-Ban Meta glasses with
/// PeriTwin. Presented as a sheet from the Devices tab (and from the
/// not-connected hint after a failed Meta AI handoff).
///
/// The connection handoff spans two apps and fails opaquely on the Meta
/// side — most commonly because the Meta AI sheet disables its Connect
/// button while glasses firmware installs. Pilot clinicians hit this the
/// evening before clinic, so the guide leads with the happy path and calls
/// the update-in-progress trap out explicitly in troubleshooting.
struct GlassesGuideView: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    header

                    VStack(spacing: 12) {
                        step(1, icon: "link",
                             title: L("glassesGuide.step1.title"),
                             body: L("glassesGuide.step1.body"))
                        step(2, icon: "arrow.down.circle",
                             title: L("glassesGuide.step2.title"),
                             body: L("glassesGuide.step2.body"))
                        step(3, icon: "checkmark.shield",
                             title: L("glassesGuide.step3.title"),
                             body: L("glassesGuide.step3.body"))
                        step(4, icon: "video",
                             title: L("glassesGuide.step4.title"),
                             body: L("glassesGuide.step4.body"))
                        step(5, icon: "record.circle",
                             title: L("glassesGuide.step5.title"),
                             body: L("glassesGuide.step5.body"))
                    }

                    troubleshooting
                }
                .aurionScreenEdge()
                .padding(.vertical, 12)
            }
            .background(Color.aurionBackground)
            .navigationTitle(L("glassesGuide.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(L("common.done")) { dismiss() }
                }
            }
        }
    }

    private var header: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                Image(systemName: "eyeglasses")
                    .font(.system(size: 28))
                    .foregroundColor(.aurionGold)
                Text(L("glassesGuide.heading"))
                    .aurionFont(22, weight: .bold, relativeTo: .title2)
                    .foregroundColor(.aurionTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(L("glassesGuide.intro"))
                .aurionFont(14, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    /// One numbered step card. The number is decorative (the order is in the
    /// layout); VoiceOver reads title + body.
    private func step(_ number: Int, icon: String, title: String, body: String) -> some View {
        AurionCard(padding: 14) {
            HStack(alignment: .top, spacing: 12) {
                ZStack {
                    Circle()
                        .fill(Color.aurionGoldBg)
                        .frame(width: 32, height: 32)
                    Text("\(number)")
                        .aurionFont(15, weight: .bold, relativeTo: .subheadline)
                        .foregroundColor(.aurionGoldDark)
                }
                .accessibilityHidden(true)

                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Image(systemName: icon)
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundColor(.aurionGold)
                            .accessibilityHidden(true)
                        Text(title)
                            .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                            .foregroundColor(.aurionTextPrimary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    Text(body)
                        .aurionFont(13, relativeTo: .footnote)
                        .foregroundColor(.aurionTextSecondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Spacer(minLength: 0)
            }
        }
    }

    private var troubleshooting: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(L("glassesGuide.troubleshooting.title").uppercased())
                .aurionFont(11, weight: .semibold, relativeTo: .caption2)
                .tracking(1.0)
                .foregroundColor(.aurionTextSecondary)

            AurionCard(padding: 14) {
                VStack(alignment: .leading, spacing: 14) {
                    trouble(L("glassesGuide.trouble1.symptom"), L("glassesGuide.trouble1.fix"))
                    Divider()
                    trouble(L("glassesGuide.trouble2.symptom"), L("glassesGuide.trouble2.fix"))
                    Divider()
                    trouble(L("glassesGuide.trouble3.symptom"), L("glassesGuide.trouble3.fix"))
                    Divider()
                    trouble(L("glassesGuide.trouble4.symptom"), L("glassesGuide.trouble4.fix"))
                }
            }
        }
    }

    private func trouble(_ symptom: String, _ fix: String) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack(alignment: .top, spacing: 6) {
                Image(systemName: "wrench.and.screwdriver")
                    .font(.system(size: 11))
                    .foregroundColor(.aurionGold)
                    .padding(.top, 2)
                    .accessibilityHidden(true)
                Text(symptom)
                    .aurionFont(13, weight: .semibold, relativeTo: .footnote)
                    .foregroundColor(.aurionTextPrimary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Text(fix)
                .aurionFont(13, relativeTo: .footnote)
                .foregroundColor(.aurionTextSecondary)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.leading, 17)
        }
    }
}
