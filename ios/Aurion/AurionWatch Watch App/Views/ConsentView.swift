import SwiftUI

/// #65 — consent confirmation from the wrist. Three large tap targets,
/// one per `ConsentMethod` (raw values MUST match the iOS enum:
/// `verbal` / `paper_form` / `digital_form`). Tapping sends a
/// `.confirmConsent` command; the PHONE writes the consent audit event —
/// the watch never bypasses the gate.
struct ConsentView: View {
    @EnvironmentObject private var client: WatchConnectivityClient

    /// (rawValue, label, SF Symbol) — mirrors the iOS `ConsentMethod`
    /// cases + icons so the wrist and phone read the same.
    private let methods: [(raw: String, label: String, icon: String)] = [
        ("verbal", WL("watch.consent.verbal", "Verbal"), "mic.fill"),
        ("paper_form", WL("watch.consent.paper", "Paper form"), "doc.text.fill"),
        ("digital_form", WL("watch.consent.digital", "Digital form"), "iphone.gen3"),
    ]

    var body: some View {
        ScrollView {
            VStack(spacing: 10) {
                VStack(spacing: 2) {
                    Image(systemName: "checkmark.shield.fill")
                        .font(.system(size: 22, weight: .semibold))
                        .foregroundStyle(WatchTheme.gold)
                    Text(WL("watch.consent.title", "Confirm consent"))
                        .font(.system(size: 15, weight: .semibold))
                        .multilineTextAlignment(.center)
                }
                .padding(.bottom, 2)

                ForEach(methods, id: \.raw) { method in
                    Button {
                        client.send(.confirmConsent, consentMethod: method.raw)
                    } label: {
                        HStack(spacing: 8) {
                            Image(systemName: method.icon)
                            Text(method.label)
                                .font(.system(size: 15, weight: .medium))
                            Spacer()
                        }
                        .padding(.vertical, 4)
                    }
                    .tint(WatchTheme.gold)
                }
            }
            .padding(.horizontal, 4)
        }
    }
}
