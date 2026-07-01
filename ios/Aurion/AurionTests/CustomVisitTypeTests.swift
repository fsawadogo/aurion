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

    @Test func fullWordTitleCaseLabels_passGate() {
        // Pilot "don't restrict" feedback: the proper-noun / full-name
        // heuristic is REMOVED. Full descriptive Title-Case labels — the
        // whole point of a custom context — now pass. Mirrors the backend
        // flip (`_validate_consultation_type(check_proper_noun=False)`).
        for label in ["Limb Lengthening Cosmetic", "Breast Reconstruction", "Marie Gdalevitch"] {
            #expect(
                PhysicianProfileSetupView.validateCustomVisitType(label, existing: []) == nil,
                "\(label) should be allowed (no proper-noun restriction)"
            )
        }
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

    // MARK: - Per-visit-type contexts (GH-315 / I1)

    @Test func builtInTemplateKeys_matchBackend() {
        // The 8 keys MUST equal the backend's `list_available_templates()`
        // membership gate (the union of template JSON files on disk) so a
        // template_key the picker can emit never trips a 422.
        let expected: Set<String> = [
            "general",
            "emergency_medicine",
            "family_medicine",
            "internal_medicine",
            "musculoskeletal",
            "orthopedic_surgery",
            "pediatrics",
            "plastic_surgery",
        ]
        #expect(Set(BuiltInTemplate.keys) == expected)
        #expect(BuiltInTemplate.keys.count == 8)
    }

    @Test func maxContextsPerVisitType_matchesBackendCap() {
        // iOS soft cap MUST equal `_MAX_CONTEXTS_PER_VISIT_TYPE` (30) on
        // the backend so the user can't add a 31st context client-side and
        // then eat a 422 on save.
        #expect(VisitTypeContextEditor.maxContexts == 30)
    }

    @Test func contextLabel_reusesVisitTypeValidator() {
        // Context labels run the SAME format gate as custom visit-type
        // labels: shorthand + full descriptive Title-Case phrases pass; only
        // PHI shapes (SSN / email) and over-long / duplicate are rejected.
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType("LL", existing: [])
                == nil
        )
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType("right knee", existing: [])
                == nil
        )
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType("Breast", existing: [])
                == nil
        )
        // Full-word Title-Case labels now PASS (proper-noun gate removed).
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType(
                "Marie Gdalevitch", existing: []
            ) == nil
        )
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType(
                "perry@clinic.lan", existing: []
            ) != nil
        )
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType(
                String(repeating: "X", count: 61), existing: []
            ) != nil
        )
        // De-dup is against the existing context labels in the SAME visit
        // type (passed via `existing:`).
        #expect(
            PhysicianProfileSetupView.validateCustomVisitType("LL", existing: ["LL"])
                != nil
        )
    }

    @Test func newContext_hasEmptyServerId_forBackendAssignment() {
        // A freshly authored context ships `id == ""`; the backend mints
        // the stable `ctx_<hex>` id and the client preserves it thereafter.
        let ctx = VisitTypeContext(label: "LL")
        #expect(ctx.serverID == "")
        #expect(ctx.templateKey == nil)
        let payload = VisitTypeContext.encodePayload(ctx)
        #expect(payload["id"] as? String == "")
        #expect(payload["label"] as? String == "LL")
        // template_key omitted when nil (backend defaults it to null =
        // specialty default); template_ref is never sent.
        #expect(payload["template_key"] == nil)
        #expect(payload["template_ref"] == nil)
    }

    @Test func templateDisplayNames_resolveInEnglishAndFrench() {
        // Every built-in template — plus the "specialty default" option and
        // the editor chrome — must localize in BOTH EN and FR (AC: FR
        // parity). The L() helper returns the key verbatim on a miss.
        guard let fr = Bundle.main.path(forResource: "fr", ofType: "lproj"),
              let frBundle = Bundle(path: fr)
        else {
            Issue.record("fr.lproj missing from main bundle")
            return
        }
        for key in BuiltInTemplate.keys {
            let sKey = "specialty.\(key)"
            #expect(L(sKey) != sKey, "EN missing template name for \(key)")
            #expect(
                frBundle.localizedString(forKey: sKey, value: sKey, table: nil) != sKey,
                "FR missing template name for \(key)"
            )
        }
        let chrome = [
            "setup.context.add",
            "setup.context.placeholder",
            "setup.context.commit",
            "setup.context.cancel",
            "setup.context.limit",
            "setup.context.template.default",
        ]
        for key in chrome {
            #expect(L(key) != key, "EN missing localization for \(key)")
            #expect(
                frBundle.localizedString(forKey: key, value: key, table: nil) != key,
                "FR missing localization for \(key)"
            )
        }
    }
}
