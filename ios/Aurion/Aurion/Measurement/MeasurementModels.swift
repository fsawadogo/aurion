import Foundation

/// Domain types for the in-encounter visual measurement instrument (#63).
///
/// Everything here is computed 100% on-device (ARKit/LiDAR for wound
/// dimensions, an AR goniometer for ROM). The backend only ever receives the
/// structured `MeasurementCitationPayload` — numbers + provenance, never raw
/// frames. Mirrors the backend `MeasurementCitation` schema.
///
/// Descriptive-mode + SaMD posture (CLAUDE.md §descriptive; design §6): a
/// measurement is reported as **"approximately"** with its method and
/// confidence, and it is **not a certified measurement** — `certified` is
/// structurally false (the server forces it too). No trends, no
/// interpretation, no diagnosis.

/// What is being measured. The unit is fixed per kind (the backend enforces
/// the same kind↔unit invariant), so it lives here as the single source.
enum MeasurementKind: String, CaseIterable, Identifiable, Sendable {
    case woundLength = "wound_length"
    case woundWidth = "wound_width"
    case woundArea = "wound_area"
    case romAngle = "rom_angle"

    var id: String { rawValue }

    /// API unit string (matches the backend `unit` literal).
    var unit: String {
        switch self {
        case .woundLength, .woundWidth: return "mm"
        case .woundArea: return "cm2"
        case .romAngle: return "deg"
        }
    }

    /// Localized human label key (resolved via `L(...)`).
    var titleKey: String {
        switch self {
        case .woundLength: return "measurement.kind.woundLength"
        case .woundWidth: return "measurement.kind.woundWidth"
        case .woundArea: return "measurement.kind.woundArea"
        case .romAngle: return "measurement.kind.romAngle"
        }
    }

    /// SF Symbol for the kind chip.
    var systemImage: String {
        switch self {
        case .woundLength, .woundWidth: return "ruler"
        case .woundArea: return "square.dashed"
        case .romAngle: return "angle"
        }
    }

    /// A linear distance (two points) vs. an angle (goniometer) — drives which
    /// capture mode the AR instrument runs.
    var isAngle: Bool { self == .romAngle }
}

/// How metric scale was recovered. The server validates this against the
/// AppConfig `methods_allowed` allowlist.
enum MeasurementMethod: String, Sendable {
    case arkitLidar = "arkit_lidar"
    case arkitWorld = "arkit_world"
    case arGoniometer = "ar_goniometer"
}

/// Confidence the instrument assigns to a capture, lowest-to-highest.
enum MeasurementConfidence: String, Comparable, Sendable {
    case low
    case medium
    case high

    private var rank: Int {
        switch self {
        case .low: return 0
        case .medium: return 1
        case .high: return 2
        }
    }

    static func < (lhs: MeasurementConfidence, rhs: MeasurementConfidence) -> Bool {
        lhs.rank < rhs.rank
    }
}

/// A captured-but-not-yet-confirmed measurement. The physician reviews this in
/// the confirm card and either confirms (→ POST with `physicianConfirmed`),
/// edits the value, or discards. Nothing reaches the backend until confirmed.
struct MeasurementResult: Identifiable, Equatable, Sendable {
    let id: String
    let kind: MeasurementKind
    var value: Double
    let method: MeasurementMethod
    let confidence: MeasurementConfidence
    let confidenceReason: String
    let scaleSource: String?

    init(
        kind: MeasurementKind,
        value: Double,
        method: MeasurementMethod,
        confidence: MeasurementConfidence,
        confidenceReason: String,
        scaleSource: String?,
        id: String = "meas_\(UUID().uuidString.prefix(12))"
    ) {
        self.id = id
        self.kind = kind
        self.value = value
        self.method = method
        self.confidence = confidence
        self.confidenceReason = confidenceReason
        self.scaleSource = scaleSource
    }

    /// Value rendered for display: drop a trailing ".0", keep real decimals.
    var displayValue: String {
        value == value.rounded() ? String(Int(value.rounded())) : String(format: "%.1f", value)
    }

    /// Human unit for the readout ("mm", "cm²", "°").
    var displayUnit: String {
        switch kind.unit {
        case "cm2": return "cm²"
        case "deg": return "°"
        default: return kind.unit
        }
    }
}

/// The exact JSON body POSTed to `/me/sessions/{id}/measurements`. Built from a
/// confirmed `MeasurementResult`. `certified_measurement` is never sent true —
/// the server forces it false regardless; the disclaimer is structural.
struct MeasurementCitationPayload: Sendable {
    let measurementId: String
    let sessionId: String
    let kind: String
    let value: Double
    let unit: String
    let method: String
    let confidence: String
    let confidenceReason: String
    let scaleSource: String?
    let maskingStatus: String
    let physicianConfirmed: Bool

    /// Build the confirmed-citation payload for a reviewed measurement.
    /// `maskingStatus` is `not_applicable`: the instrument transmits numbers
    /// only — no frame ever leaves the device — so there is nothing to mask.
    init(sessionId: String, result: MeasurementResult, physicianConfirmed: Bool) {
        self.measurementId = result.id
        self.sessionId = sessionId
        self.kind = result.kind.rawValue
        self.value = result.value
        self.unit = result.kind.unit
        self.method = result.method.rawValue
        self.confidence = result.confidence.rawValue
        self.confidenceReason = result.confidenceReason
        self.scaleSource = result.scaleSource
        self.maskingStatus = "not_applicable"
        self.physicianConfirmed = physicianConfirmed
    }

    var jsonBody: [String: Any] {
        var body: [String: Any] = [
            "measurement_id": measurementId,
            "session_id": sessionId,
            "kind": kind,
            "value": value,
            "unit": unit,
            "method": method,
            "confidence": confidence,
            "confidence_reason": confidenceReason,
            "masking_status": maskingStatus,
            "physician_confirmed": physicianConfirmed,
            "provider_used": "on_device",
            "model_version": "meas-1.0",
        ]
        if let scaleSource { body["scale_source"] = scaleSource }
        return body
    }
}
