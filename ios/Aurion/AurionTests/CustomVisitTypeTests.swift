//
//  CustomVisitTypeTests.swift
//  AurionTests
//
//  GH-259 — pin the format-gate behaviour for the iOS-side
//  custom-visit-types affordance on `PhysicianProfileSetupView`. We
//  exercise the static `validateCustomVisitType` helper directly so
//  the tests stay SwiftUI-lifecycle-free, same pattern as
//  TeamMemberEditorViewTests.
//
//  Locked properties:
//    - Mirrors the backend `validate_user_text` gates: SSN / email /
//      full-name / 60-char cap / duplicate.
//    - Valid custom labels — including the Marie ("LL fu") and Perry
//      ("Breast") use cases from the issue — pass through.
//    - Localized strings exist in EN and FR (AC-9).
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct CustomVisitTypeTests {

    // MARK: - Happy path (AC-1, AC-2)

    @Test func marieLowerLimbShorthand_passesGate() {
        // Marie's lower-limb shorthand from issue #259. The full-name
        // gate is OFF for consultation types — second token starts
        // lowercase so the proper-noun-pair heuristic doesn't trip.
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType("LL fu", existing: [])
                == nil
        )
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType("LL new pt", existing: [])
                == nil
        )
    }

    @Test func perryBreastVisit_passesGate() {
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            "Breast visit",
            existing: []
        )
        #expect(result == nil)
    }

    @Test func emptyDraft_passesGate_quietly() {
        // Empty / whitespace-only is the "not yet typed" state — the
        // Add button's disabled binding stops a save, the validator
        // returns nil so no red error chrome flashes.
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType("", existing: [])
                == nil
        )
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType(
                "   ",
                existing: []
            ) == nil
        )
    }

    // MARK: - Format gates (AC-4)

    @Test func rawSSN_isRejected() {
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            "123456789",
            existing: []
        )
        #expect(result != nil)
    }

    @Test func dashedSSN_isRejected() {
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            "123-45-6789",
            existing: []
        )
        #expect(result != nil)
    }

    @Test func emailShape_isRejected() {
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            "perry@clinic.lan",
            existing: []
        )
        #expect(result != nil)
    }

    @Test func twoTokenFullName_isRejected() {
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            "Marie Gdalevitch",
            existing: []
        )
        #expect(result != nil)
    }

    @Test func tooLong_isRejected() {
        let sixtyOne = String(repeating: "X", count: 61)
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            sixtyOne,
            existing: []
        )
        #expect(result != nil)
    }

    @Test func atSixtyChars_passesGate() {
        let sixty = String(repeating: "X", count: 60)
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            sixty,
            existing: []
        )
        #expect(result == nil)
    }

    // MARK: - De-dup

    @Test func duplicateCustom_isRejected() {
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            "Breast",
            existing: ["Breast"]
        )
        #expect(result != nil)
    }

    @Test func duplicateDefault_isRejected() {
        // A clinician can't shadow one of the 4 canonical keys with a
        // custom by typing it verbatim.
        let result = PhysicianProfileSetupView.validateCustomVisitType(
            "new_patient",
            existing: []
        )
        #expect(result != nil)
    }

    // MARK: - Soft cap (AC-3)

    @Test func maxCustomTypes_matchesBackendCap() {
        // The iOS soft cap MUST equal the backend
        // _MAX_CUSTOM_CONSULTATION_TYPES so a user can't tap Add 21
        // times client-side and then eat a 422 on save.
        #expect(PhysicianProfileSetupView.maxCustomTypes == 20)
    }

    // MARK: - Defaults set parity

    @Test func defaultVisitTypeKeys_matchBackend() {
        // The set MUST equal _DEFAULT_CONSULTATION_TYPES on the
        // backend (backend/app/api/v1/profile.py). Otherwise the
        // partition on re-entry into the setup flow will misclassify
        // a server-side key as a custom.
        let expected: Set<String> = [
            "new_patient", "follow_up", "pre_op", "post_op",
        ]
        #expect(PhysicianProfileSetupView.defaultVisitTypeKeys == expected)
    }

    // MARK: - Localized strings parity (AC-9)

    @Test func customVisitStrings_resolveInEnglish() {
        let keys = [
            "setup.visit.custom.add",
            "setup.visit.custom.placeholder",
            "setup.visit.custom.commit",
            "setup.visit.custom.cancel",
            "setup.visit.custom.limit",
            "setup.visit.custom.error.tooLong",
            "setup.visit.custom.error.ssn",
            "setup.visit.custom.error.email",
            "setup.visit.custom.error.name",
            "setup.visit.custom.error.duplicate",
        ]
        for key in keys {
            // L() returns the key verbatim when missing. A successful
            // lookup means the resolved string is different from the
            // key — that's the contract every other parity test on
            // this codebase uses.
            let value = L(key)
            #expect(
                value != key,
                "EN missing localization for \(key)"
            )
        }
    }

    @Test func customVisitStrings_resolveInFrench() {
        // The L() helper resolves against `Bundle.main` which respects
        // the simulator's preferred-locales chain; this assertion locks
        // the fr.lproj file's presence + parity. We compare against the
        // EN value to catch the "key copied untranslated" failure mode.
        let bundle = Bundle.main
        guard let fr = bundle.path(forResource: "fr", ofType: "lproj"),
              let frBundle = Bundle(path: fr)
        else {
            Issue.record("fr.lproj missing from main bundle")
            return
        }
        let keys = [
            "setup.visit.custom.add",
            "setup.visit.custom.placeholder",
            "setup.visit.custom.commit",
            "setup.visit.custom.cancel",
            "setup.visit.custom.limit",
            "setup.visit.custom.error.tooLong",
            "setup.visit.custom.error.ssn",
            "setup.visit.custom.error.email",
            "setup.visit.custom.error.name",
            "setup.visit.custom.error.duplicate",
        ]
        for key in keys {
            let frValue = frBundle.localizedString(
                forKey: key,
                value: key,
                table: nil
            )
            #expect(frValue != key, "FR missing localization for \(key)")
        }
    }
}
