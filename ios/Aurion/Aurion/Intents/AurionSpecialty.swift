import AppIntents

/// AppEnum exposed to Siri/Shortcuts. The raw value matches the backend
/// `specialty` string so the same identifier flows from "Hey Siri, start
/// an orthopedic session" all the way into ``SessionStartRequest.specialty``.
///
/// Localized display strings drive the natural-phrase grammar Shortcuts
/// builds (e.g. "Start a plastic surgery session"), so they intentionally
/// read like noun phrases, not enum case names.
enum AurionSpecialty: String, AppEnum {
    case orthopedic = "orthopedic_surgery"
    case plastic = "plastic_surgery"
    case musculoskeletal = "musculoskeletal"
    case emergency = "emergency_medicine"
    case general = "general"

    static var typeDisplayRepresentation: TypeDisplayRepresentation =
        TypeDisplayRepresentation(name: "Aurion Specialty")

    static var caseDisplayRepresentations: [AurionSpecialty: DisplayRepresentation] = [
        .orthopedic: DisplayRepresentation(
            title: "orthopedic surgery",
            subtitle: "Bones, joints, and musculoskeletal procedures"
        ),
        .plastic: DisplayRepresentation(
            title: "plastic surgery",
            subtitle: "Reconstructive and aesthetic procedures"
        ),
        .musculoskeletal: DisplayRepresentation(
            title: "musculoskeletal",
            subtitle: "MSK assessment and rehabilitation"
        ),
        .emergency: DisplayRepresentation(
            title: "emergency medicine",
            subtitle: "Acute presentations and triage"
        ),
        .general: DisplayRepresentation(
            title: "general",
            subtitle: "General clinical encounter"
        ),
    ]
}
