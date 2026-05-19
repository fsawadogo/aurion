import ActivityKit
import SwiftUI
import WidgetKit

/// Live Activity for a capture session in progress. Visible on:
///   - Lock Screen (full-width pill below the alarm UI)
///   - Dynamic Island compact (gold record dot left, timer right)
///   - Dynamic Island expanded (specialty + elapsed timer + pause state)
///   - Dynamic Island minimal (single gold record dot)
///
/// Driven by ``AurionCaptureActivityAttributes`` — the main app calls
/// `Activity.request(...)` from ``SessionManager.startNewSession`` and
/// `activity.end(...)` from ``SessionManager.stopRecording``.
struct AurionCaptureActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: AurionCaptureActivityAttributes.self) { context in
            // Lock Screen — appears as a pill below the time/alarm.
            LockScreenView(context: context)
        } dynamicIsland: { context in
            DynamicIsland {
                // Expanded — tap-to-expand pill
                DynamicIslandExpandedRegion(.leading) {
                    Label {
                        Text(context.attributes.specialtyDisplay)
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.white)
                    } icon: {
                        Image(systemName: context.state.isPaused ? "pause.circle.fill" : "record.circle")
                            .foregroundStyle(context.state.isPaused ? .white.opacity(0.7) : Color.aurionGoldAccent)
                            .symbolEffect(.pulse, options: .repeating, isActive: !context.state.isPaused)
                    }
                }
                DynamicIslandExpandedRegion(.trailing) {
                    timerText(state: context.state)
                        .font(.system(.title3, design: .monospaced, weight: .semibold))
                        .foregroundStyle(.white)
                        .monospacedDigit()
                }
                DynamicIslandExpandedRegion(.bottom) {
                    Text(context.state.isPaused ? "Paused" : "Recording")
                        .font(.caption2.weight(.medium))
                        .foregroundStyle(.white.opacity(0.7))
                        .frame(maxWidth: .infinity, alignment: .leading)
                }
            } compactLeading: {
                Image(systemName: context.state.isPaused ? "pause.fill" : "record.circle")
                    .foregroundStyle(context.state.isPaused ? .white.opacity(0.7) : Color.aurionGoldAccent)
            } compactTrailing: {
                timerText(state: context.state)
                    .monospacedDigit()
                    .foregroundStyle(.white)
            } minimal: {
                Image(systemName: "record.circle")
                    .foregroundStyle(Color.aurionGoldAccent)
                    .symbolEffect(.pulse, options: .repeating, isActive: !context.state.isPaused)
            }
            // Deep-link back into the session note when the user taps
            // the Dynamic Island. The path is parsed in AurionApp's
            // .onOpenURL handler (to be added in a follow-up).
            .widgetURL(URL(string: "aurion://session/\(context.attributes.sessionID)"))
        }
    }

    /// Renders the running timer using `Text(timerInterval:)` — iOS
    /// drives the per-second update internally, so we don't have to
    /// push state updates every second from the main app.
    @ViewBuilder
    private func timerText(state: AurionCaptureActivityAttributes.ContentState) -> some View {
        if state.isPaused {
            Text("⏸")
        } else {
            Text(timerInterval: state.startedAt...Date.distantFuture, countsDown: false)
        }
    }
}

// MARK: - Lock Screen Layout

private struct LockScreenView: View {
    let context: ActivityViewContext<AurionCaptureActivityAttributes>

    var body: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(Color.aurionGoldAccent.opacity(0.18))
                    .frame(width: 44, height: 44)
                Image(systemName: context.state.isPaused ? "pause.fill" : "record.circle")
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(context.state.isPaused ? .secondary : Color.aurionGoldAccent)
                    .symbolEffect(
                        .pulse,
                        options: .repeating,
                        isActive: !context.state.isPaused
                    )
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(context.attributes.specialtyDisplay)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(.primary)
                Text(context.state.isPaused ? "Paused" : "Recording")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            if context.state.isPaused {
                Text("⏸")
                    .font(.title3.monospacedDigit().weight(.semibold))
                    .foregroundStyle(.secondary)
            } else {
                Text(timerInterval: context.state.startedAt...Date.distantFuture, countsDown: false)
                    .font(.title3.monospacedDigit().weight(.semibold))
                    .foregroundStyle(.primary)
                    .monospacedDigit()
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        // ActivityBackgroundTint uses .ultraThinMaterial under the hood
        // when no tint is set — fits the lock screen's vibrancy.
        .activityBackgroundTint(nil)
        .activitySystemActionForegroundColor(.primary)
    }
}

// MARK: - Helpers

private extension AurionCaptureActivityAttributes {
    /// Specialty slug → human-readable label. Self-contained so the
    /// widget doesn't depend on the main app's localization tables.
    var specialtyDisplay: String {
        switch specialty {
        case "orthopedic_surgery": return "Orthopedic Surgery"
        case "plastic_surgery":    return "Plastic Surgery"
        case "musculoskeletal":    return "Musculoskeletal"
        case "emergency_medicine": return "Emergency Medicine"
        case "general":            return "General"
        default:
            return specialty
                .replacingOccurrences(of: "_", with: " ")
                .capitalized
        }
    }
}

private extension Color {
    /// Aurion gold — duplicated locally so the widget target doesn't
    /// pull in the main app's full ``Theme.swift`` (which depends on
    /// UIKit + the entire design system). Matches `Color.aurionGold`
    /// in the main app exactly.
    static let aurionGoldAccent = Color(red: 201/255, green: 168/255, blue: 76/255)
}
