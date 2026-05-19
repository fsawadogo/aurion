import AppIntents
import SwiftUI

/// "Hey Siri, start an Aurion {specialty} session" — opens the app on the
/// dashboard with the encounter-type sheet pre-loaded for the requested
/// specialty. The same downstream code that handles a Quick Start card tap
/// picks it up — we publish a ``PendingQuickStart`` to ``AppNavigation``
/// and let SwiftUI react.
///
/// Deliberately stops at the encounter-type sheet rather than auto-starting
/// recording: clinical consent + encounter context still need a human gate.
/// The intent's job is to shave off the dashboard-card tap; the privacy gates
/// remain in the SwiftUI flow.
struct StartSessionIntent: AppIntent {
    static var title: LocalizedStringResource = "Start Aurion Session"

    static var description: IntentDescription =
        "Open Aurion and prepare a new session for the chosen specialty. Recording still requires confirming the patient consent gate."

    /// Bring the app to the foreground when run from Siri / Shortcuts /
    /// home-screen widget. The session can't be configured behind the
    /// scenes — encounter type and context are required UI gates.
    static var openAppWhenRun: Bool = true

    @Parameter(
        title: "Specialty",
        description: "Which clinical template should the session use?",
        default: .orthopedic
    )
    var specialty: AurionSpecialty

    @Parameter(
        title: "Consultation type",
        description: "New patient or follow-up.",
        default: .newPatient
    )
    var consultationType: AurionConsultationType

    static var parameterSummary: some ParameterSummary {
        Summary("Start an Aurion \(\.$specialty) session for a \(\.$consultationType)")
    }

    @MainActor
    func perform() async throws -> some IntentResult {
        AppNavigation.shared.requestQuickStart(
            specialty: specialty.rawValue,
            consultationType: consultationType.rawValue
        )
        return .result()
    }
}

/// Echoes the dashboard's `quickstart.newPatient` / `quickstart.followUp`
/// strings. Kept as a separate AppEnum so the Shortcuts UI can offer it
/// as a picker rather than a free-text field.
enum AurionConsultationType: String, AppEnum {
    case newPatient = "new_patient"
    case followUp = "follow_up"
    case preOp = "pre_op"
    case postOp = "post_op"

    static var typeDisplayRepresentation: TypeDisplayRepresentation =
        TypeDisplayRepresentation(name: "Consultation Type")

    static var caseDisplayRepresentations: [AurionConsultationType: DisplayRepresentation] = [
        .newPatient: "new patient",
        .followUp: "follow-up",
        .preOp: "pre-op",
        .postOp: "post-op",
    ]
}
