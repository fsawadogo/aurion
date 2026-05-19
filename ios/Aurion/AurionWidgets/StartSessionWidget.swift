import SwiftUI
import WidgetKit

/// Home-screen widget that launches the app and primes a new capture
/// session. Tapping the widget is a deep-link into the encounter-type
/// sheet — the consent and context gates still apply, by design.
///
/// Lives on the home screen and the Lock Screen Stack. Driven by a
/// trivial timeline provider (no remote data, no refresh cadence) so
/// it's cheap to keep mounted.
struct StartSessionWidget: Widget {
    let kind: String = "app.aurion.widgets.start-session"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: Provider()) { _ in
            StartSessionWidgetView()
        }
        .configurationDisplayName("Start Session")
        .description("Quick-start a clinical capture session in Aurion.")
        // Small + medium look at home on every iPhone home screen.
        // Lock-screen rectangular surfaces the same affordance under
        // the clock — useful for grabbing a quick session between
        // patients.
        .supportedFamilies([.systemSmall, .systemMedium, .accessoryRectangular])
        .contentMarginsDisabled()
    }
}

// MARK: - Timeline Provider
//
// The widget renders the same content regardless of time — there's no
// remote data, no per-hour refresh cycle. The provider returns a single
// `.never`-refreshing entry so iOS doesn't burn the per-widget refresh
// budget on a static view.

private struct Provider: TimelineProvider {
    func placeholder(in context: Context) -> Entry { Entry(date: .now) }
    func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void) {
        completion(Entry(date: .now))
    }
    func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void) {
        completion(Timeline(entries: [Entry(date: .now)], policy: .never))
    }
}

private struct Entry: TimelineEntry { let date: Date }

// MARK: - View

private struct StartSessionWidgetView: View {
    @Environment(\.widgetFamily) private var family

    var body: some View {
        // The whole widget is one big tap target — single deep-link
        // URL. The main app's onOpenURL handler routes this through
        // ``AppNavigation`` so the existing encounter-type sheet flow
        // (consent + context gates) picks it up.
        Link(destination: URL(string: "aurion://start-session")!) {
            content
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(family == .accessoryRectangular ? 4 : 12)
                .containerBackground(for: .widget) {
                    if family == .accessoryRectangular {
                        Color.clear     // lock-screen vibrancy handles this
                    } else {
                        LinearGradient(
                            colors: [
                                Color(red: 12/255, green: 27/255, blue: 55/255),  // brand navy
                                Color(red: 22/255, green: 40/255, blue: 78/255),  // navy-light
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    }
                }
        }
    }

    @ViewBuilder
    private var content: some View {
        switch family {
        case .systemSmall:
            smallLayout
        case .systemMedium:
            mediumLayout
        case .accessoryRectangular:
            lockScreenLayout
        default:
            smallLayout
        }
    }

    /// 2×2 home-screen widget: gold record dot + label below.
    private var smallLayout: some View {
        VStack(alignment: .leading, spacing: 0) {
            Image(systemName: "record.circle")
                .font(.system(size: 32, weight: .regular))
                .foregroundStyle(StartSessionPalette.gold)
                .symbolEffect(.pulse, options: .repeating)
            Spacer()
            VStack(alignment: .leading, spacing: 2) {
                Text("Aurion")
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(0.6)
                    .textCase(.uppercase)
                    .foregroundStyle(.white.opacity(0.65))
                Text("Start Session")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.white)
                    .lineLimit(2)
                    .minimumScaleFactor(0.85)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    /// 4×2 home-screen widget: dot + multi-line affordance + chevron.
    private var mediumLayout: some View {
        HStack(spacing: 14) {
            ZStack {
                Circle()
                    .fill(StartSessionPalette.gold.opacity(0.18))
                    .frame(width: 56, height: 56)
                Image(systemName: "record.circle")
                    .font(.system(size: 28, weight: .regular))
                    .foregroundStyle(StartSessionPalette.gold)
                    .symbolEffect(.pulse, options: .repeating)
            }
            VStack(alignment: .leading, spacing: 3) {
                Text("Aurion")
                    .font(.system(size: 11, weight: .semibold))
                    .tracking(0.6)
                    .textCase(.uppercase)
                    .foregroundStyle(.white.opacity(0.65))
                Text("Start a clinical session")
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.white)
                Text("Tap to choose specialty, then record.")
                    .font(.system(size: 12))
                    .foregroundStyle(.white.opacity(0.7))
                    .lineLimit(2)
            }
            Spacer()
            Image(systemName: "chevron.forward")
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(.white.opacity(0.4))
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .leading)
    }

    /// Lock Screen rectangular accessory — terse, vibrancy-rendered.
    /// No background; iOS applies the lock-screen blur underneath.
    private var lockScreenLayout: some View {
        HStack(spacing: 8) {
            Image(systemName: "record.circle")
                .symbolRenderingMode(.hierarchical)
            VStack(alignment: .leading, spacing: 0) {
                Text("Aurion")
                    .font(.caption2.weight(.semibold))
                Text("Start session")
                    .font(.caption.weight(.semibold))
            }
            Spacer()
        }
    }
}

// MARK: - Palette (duplicated locally — widget target doesn't import Theme.swift)

private enum StartSessionPalette {
    static let gold = Color(red: 201/255, green: 168/255, blue: 76/255)  // brand gold #C9A84C
}
