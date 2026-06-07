//
//  DashboardQuickStartTests.swift
//  AurionTests
//
//  #278 — Quick Start cards must derive from the physician profile and
//  NEVER fall back to GENERAL when the profile is missing (the regression
//  that hid ortho/plastics visit types and risked starting a
//  "general"-template session for the wrong specialty).
//
//  Locked behavior of DashboardView.quickStartCards(for:):
//    - nil profile  → [] (caller shows a skeleton, not GENERAL defaults)
//    - real profile → cards carry the profile's specialty, never "general"
//    - empty consultationTypes → 2 default *types* but the real specialty
//    - custom visit types (PR #266) survive
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct DashboardQuickStartTests {

    // AC-1 — the fix: no cards (→ skeleton) when the profile hasn't loaded.
    @Test func nilProfileYieldsNoCards() {
        #expect(DashboardView.quickStartCards(for: nil).isEmpty)
    }

    // AC-2 — an ortho profile keeps its specialty on every card.
    @Test func orthoProfileKeepsSpecialty() {
        let cards = DashboardView.quickStartCards(
            for: profile(specialty: "orthopedic_surgery", types: ["new_patient", "follow_up"])
        )
        #expect(cards.count == 2)
        #expect(cards.allSatisfy { $0.specialty == "orthopedic_surgery" })
        #expect(!cards.contains { $0.specialty == "general" })
    }

    // AC-3 — empty types fall back to default TYPES but the real specialty.
    @Test func emptyTypesUsesRealSpecialtyNotGeneral() {
        let cards = DashboardView.quickStartCards(
            for: profile(specialty: "plastic_surgery", types: [])
        )
        #expect(cards.count == 2)
        #expect(cards.allSatisfy { $0.specialty == "plastic_surgery" })
        #expect(Set(cards.map(\.type)) == ["new_patient", "follow_up"])
    }

    // AC-4 — PR #266 custom visit types survive the derivation.
    @Test func customVisitTypePreserved() {
        let cards = DashboardView.quickStartCards(
            for: profile(specialty: "orthopedic_surgery", types: ["new_patient", "ll_knee_pain"])
        )
        #expect(cards.contains { $0.type == "ll_knee_pain" })
        #expect(cards.allSatisfy { $0.specialty == "orthopedic_surgery" })
    }

    // MARK: - Helper

    /// Build a profile via JSON decode (the memberwise init is internal and
    /// could change) — same pattern as TeamMemberEditorViewTests.
    private func profile(specialty: String, types: [String]) -> PhysicianProfileResponse {
        let typesJSON = types.map { "\"\($0)\"" }.joined(separator: ", ")
        let json = """
        {
            "clinician_id": "00000000-0000-0000-0000-000000000001",
            "display_name": "Dr. Test",
            "practice_type": "clinic",
            "primary_specialty": "\(specialty)",
            "preferred_templates": ["\(specialty)"],
            "consultation_types": [\(typesJSON)],
            "allied_health_team": [],
            "output_language": "en",
            "auto_upload": true,
            "retention_days": 7,
            "consent_reprompt": "every_session"
        }
        """.data(using: .utf8)!
        // swiftlint:disable:next force_try
        return try! JSONDecoder().decode(PhysicianProfileResponse.self, from: json)
    }
}
