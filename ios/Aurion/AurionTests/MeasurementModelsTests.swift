//
//  MeasurementModelsTests.swift
//  AurionTests
//
//  #63 — pure value-type logic for the in-encounter measurement instrument:
//  kind↔unit invariants, descriptive display formatting, and the exact POST
//  body the client sends (numbers + provenance only; masking_status is
//  not_applicable because no frame ever leaves the device, and the payload
//  never asserts a certified measurement). The ARKit capture path needs a
//  device and is excluded here.
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct MeasurementModelsTests {

    // MARK: - Kind ↔ unit

    @Test func kindUnitsMatchBackendInvariant() {
        #expect(MeasurementKind.woundLength.unit == "mm")
        #expect(MeasurementKind.woundWidth.unit == "mm")
        #expect(MeasurementKind.woundArea.unit == "cm2")
        #expect(MeasurementKind.romAngle.unit == "deg")
    }

    @Test func onlyRomIsAngle() {
        #expect(MeasurementKind.romAngle.isAngle)
        #expect(!MeasurementKind.woundLength.isAngle)
        #expect(!MeasurementKind.woundArea.isAngle)
    }

    // MARK: - Display

    @Test func displayValueDropsTrailingZeroKeepsDecimals() {
        let whole = MeasurementResult(kind: .woundLength, value: 42.0, method: .arkitLidar,
                                      confidence: .high, confidenceReason: "", scaleSource: nil)
        #expect(whole.displayValue == "42")
        let frac = MeasurementResult(kind: .woundWidth, value: 18.5, method: .arkitLidar,
                                     confidence: .high, confidenceReason: "", scaleSource: nil)
        #expect(frac.displayValue == "18.5")
    }

    @Test func displayUnitHumanizesGlyphs() {
        let area = MeasurementResult(kind: .woundArea, value: 3.2, method: .arkitLidar,
                                     confidence: .medium, confidenceReason: "", scaleSource: nil)
        #expect(area.displayUnit == "cm²")
        let rom = MeasurementResult(kind: .romAngle, value: 35, method: .arGoniometer,
                                    confidence: .medium, confidenceReason: "", scaleSource: nil)
        #expect(rom.displayUnit == "°")
        let len = MeasurementResult(kind: .woundLength, value: 10, method: .arkitWorld,
                                    confidence: .low, confidenceReason: "", scaleSource: nil)
        #expect(len.displayUnit == "mm")
    }

    // MARK: - Confidence ordering

    @Test func confidenceIsOrdered() {
        #expect(MeasurementConfidence.low < .medium)
        #expect(MeasurementConfidence.medium < .high)
    }

    // MARK: - POST payload

    @Test func jsonBodyMatchesBackendSchemaAndIsConfirmed() {
        let result = MeasurementResult(
            kind: .woundLength, value: 42.0, method: .arkitLidar,
            confidence: .high, confidenceReason: "stable tracking",
            scaleSource: "lidar_depth", id: "meas_001"
        )
        let body = MeasurementCitationPayload(
            sessionId: "sess-1", result: result, physicianConfirmed: true
        ).jsonBody

        #expect(body["measurement_id"] as? String == "meas_001")
        #expect(body["session_id"] as? String == "sess-1")
        #expect(body["kind"] as? String == "wound_length")
        #expect(body["value"] as? Double == 42.0)
        #expect(body["unit"] as? String == "mm")
        #expect(body["method"] as? String == "arkit_lidar")
        #expect(body["confidence"] as? String == "high")
        #expect(body["confidence_reason"] as? String == "stable tracking")
        #expect(body["scale_source"] as? String == "lidar_depth")
        #expect(body["physician_confirmed"] as? Bool == true)
        #expect(body["provider_used"] as? String == "on_device")
        #expect(body["model_version"] as? String == "meas-1.0")
        // No frame leaves the device → nothing to mask.
        #expect(body["masking_status"] as? String == "not_applicable")
        // The client never asserts a certified measurement; the server forces
        // it false regardless, so we don't send the key at all.
        #expect(body["certified_measurement"] == nil)
    }

    @Test func jsonBodyOmitsScaleSourceForAngle() {
        let rom = MeasurementResult(
            kind: .romAngle, value: 35, method: .arGoniometer,
            confidence: .medium, confidenceReason: "", scaleSource: nil, id: "meas_002"
        )
        let body = MeasurementCitationPayload(
            sessionId: "s", result: rom, physicianConfirmed: true
        ).jsonBody
        #expect(body["scale_source"] == nil)
        #expect(body["unit"] as? String == "deg")
    }

    // MARK: - Localization parity

    @Test func disclaimerResolvesInBothLanguages() {
        Localization.setLanguage("en")
        defer { Localization.setLanguage("en") }
        let en = L("measurement.disclaimer")
        #expect(en.contains("not a certified"))

        Localization.setLanguage("fr")
        let fr = L("measurement.disclaimer")
        #expect(fr.contains("non certifi"))
        // Both must actually resolve (not echo the key back).
        #expect(en != "measurement.disclaimer")
        #expect(fr != "measurement.disclaimer")
    }
}
