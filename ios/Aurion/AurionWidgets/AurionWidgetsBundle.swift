import SwiftUI
import WidgetKit

/// Widget bundle entry point. iOS instantiates this when it needs to
/// render any Aurion-owned widget surface (Lock Screen Live Activity,
/// Dynamic Island, home-screen widget). Currently registers a single
/// Live Activity for in-flight capture sessions — home-screen Start
/// Session widget is a follow-up under UI-P4b-followup.
@main
struct AurionWidgetsBundle: WidgetBundle {
    var body: some Widget {
        AurionCaptureActivityWidget()
    }
}
