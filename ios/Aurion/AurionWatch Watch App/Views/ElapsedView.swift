import SwiftUI

/// #65 — live elapsed timer, computed locally from the phone's
/// `startedAtEpoch` anchor so it ticks smoothly without a message per
/// second. Freezes (no ticking) when paused; the anchor re-establishes
/// whenever a fresh context arrives.
struct ElapsedView: View {
    /// Wall-clock epoch the recording started at, from the phone.
    let startedAtEpoch: Double?
    /// When true the timer ticks; when false (paused) it shows the frozen
    /// elapsed at the moment of pause.
    let isRunning: Bool

    var body: some View {
        if let startedAtEpoch {
            if isRunning {
                TimelineView(.periodic(from: .now, by: 1)) { context in
                    label(for: context.date, since: startedAtEpoch)
                }
            } else {
                // Paused — render once, no ticking.
                label(for: Date(), since: startedAtEpoch)
            }
        } else {
            label(text: "00:00")
        }
    }

    private func label(for now: Date, since epoch: Double) -> some View {
        let elapsed = max(0, now.timeIntervalSince1970 - epoch)
        return label(text: Self.format(elapsed))
    }

    private func label(text: String) -> some View {
        Text(text)
            .font(.system(size: 34, weight: .semibold, design: .rounded))
            .monospacedDigit()
            .foregroundStyle(.primary)
    }

    /// mm:ss, or h:mm:ss past an hour. Pure + static for unit tests.
    static func format(_ seconds: TimeInterval) -> String {
        let total = Int(seconds)
        let h = total / 3600
        let m = (total % 3600) / 60
        let s = total % 60
        if h > 0 {
            return String(format: "%d:%02d:%02d", h, m, s)
        }
        return String(format: "%02d:%02d", m, s)
    }
}
