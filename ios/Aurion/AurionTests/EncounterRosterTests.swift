//
//  EncounterRosterTests.swift
//  AurionTests
//
//  #275 (PR #348 backend contract) — iOS-side contracts for encounter
//  participants + the per-day roster.
//
//  Locked properties:
//    - AlliedHealthMember round-trips the per-day presence keys
//      (present_today / present_today_date) and decodes the backend's
//      derived present_today_effective; older rows decode unchanged.
//    - isWorkingToday prefers the backend effective flag, falling back to
//      a local stale-date recompute.
//    - settingWorkingToday stamps today's date on / drops it off.
//    - encodeMember emits the two raw presence keys but NEVER the derived
//      present_today_effective.
//    - contentEqual trips on a presence-only change (toggle persists).
//    - SessionParticipant.displayLabel falls back to the role label for an
//      anonymous (name-less) role chip.
//    - SessionResponse decodes the round-trippable participants list,
//      including an anonymous chip with a null name.
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct EncounterRosterTests {

    // MARK: - AlliedHealthMember presence round-trip (I2)

    @Test func member_decodesPresenceKeysAndEffectiveFlag() throws {
        let json = """
        {"name": "Sarah Chen", "role": "RN",
         "present_today": true, "present_today_date": "2026-06-07",
         "present_today_effective": true}
        """.data(using: .utf8)!
        let m = try JSONDecoder().decode(AlliedHealthMember.self, from: json)
        #expect(m.presentToday == true)
        #expect(m.presentTodayDate == "2026-06-07")
        #expect(m.presentTodayEffective == true)
    }

    @Test func member_decodesLegacyRowWithoutPresence() throws {
        // Pre-#275 rows carry no presence keys — they must decode with
        // all three optional fields nil and read as absent.
        let json = """
        {"name": "Alex Wu", "role": "scribe"}
        """.data(using: .utf8)!
        let m = try JSONDecoder().decode(AlliedHealthMember.self, from: json)
        #expect(m.presentToday == nil)
        #expect(m.presentTodayDate == nil)
        #expect(m.presentTodayEffective == nil)
        #expect(m.isWorkingToday == false)
    }

    @Test func isWorkingToday_prefersBackendEffectiveFlag() {
        // Effective flag wins even when the raw date looks stale — the
        // backend is the source of truth on read.
        let present = AlliedHealthMember(
            name: "A", role: "RN",
            presentToday: true, presentTodayDate: "1999-01-01",
            presentTodayEffective: true
        )
        #expect(present.isWorkingToday)

        let absent = AlliedHealthMember(
            name: "B", role: "RN",
            presentToday: true, presentTodayDate: AlliedHealthMember.todayString,
            presentTodayEffective: false
        )
        #expect(!absent.isWorkingToday)
    }

    @Test func isWorkingToday_fallsBackToLocalRecomputeWhenNoEffective() {
        // No backend-derived flag (older payload) → recompute locally:
        // present AND date == today.
        let today = AlliedHealthMember(
            name: "A", role: "RN",
            presentToday: true, presentTodayDate: AlliedHealthMember.todayString,
            presentTodayEffective: nil
        )
        #expect(today.isWorkingToday)

        let stale = AlliedHealthMember(
            name: "B", role: "RN",
            presentToday: true, presentTodayDate: "2000-01-01",
            presentTodayEffective: nil
        )
        #expect(!stale.isWorkingToday)
    }

    @Test func settingWorkingToday_stampsAndClearsDate() {
        let base = AlliedHealthMember(name: "Sarah Chen", role: "RN")

        let on = base.settingWorkingToday(true)
        #expect(on.presentToday == true)
        #expect(on.presentTodayDate == AlliedHealthMember.todayString)
        #expect(on.presentTodayEffective == true)
        #expect(on.id == base.id, "id must be preserved for list-identity stability")

        let off = on.settingWorkingToday(false)
        #expect(off.presentToday == false)
        #expect(off.presentTodayDate == nil)
        #expect(off.id == base.id)
    }

    // MARK: - encodeMember presence keys (I2)

    @Test func encodeMember_emitsPresenceKeysButNotEffective() {
        let m = AlliedHealthMember(
            name: "Sarah Chen", role: "RN",
            presentToday: true, presentTodayDate: "2026-06-07",
            presentTodayEffective: true
        )
        let encoded = TeamMemberEditorView.encodeMember(m)
        #expect(encoded["present_today"] as? Bool == true)
        #expect(encoded["present_today_date"] as? String == "2026-06-07")
        // Derived flag is recomputed server-side — never written back.
        #expect(encoded["present_today_effective"] == nil)
    }

    @Test func encodeMember_omitsPresenceKeysWhenUnset() {
        let m = AlliedHealthMember(name: "Sarah Chen", role: "RN")
        let encoded = TeamMemberEditorView.encodeMember(m)
        #expect(encoded["present_today"] == nil)
        #expect(encoded["present_today_date"] == nil)
    }

    // MARK: - contentEqual presence diff (I2)

    @Test func contentEqual_falseOnPresenceOnlyChange() {
        let a = [AlliedHealthMember(name: "Sarah Chen", role: "RN")]
        let b = [AlliedHealthMember(name: "Sarah Chen", role: "RN").settingWorkingToday(true)]
        #expect(!TeamMemberEditorView.contentEqual(a, b),
                "a working-today toggle must trip the diff so the change persists")
    }

    @Test func contentEqual_trueWhenPresenceMatches() {
        let a = [
            AlliedHealthMember(
                name: "Sarah Chen", role: "RN",
                presentToday: true, presentTodayDate: "2026-06-07"
            )
        ]
        // Different local id, different (read-only) effective flag — neither
        // is wire-meaningful, so the rows must still compare equal.
        let b = [
            AlliedHealthMember(
                name: "Sarah Chen", role: "RN",
                presentToday: true, presentTodayDate: "2026-06-07",
                presentTodayEffective: true
            )
        ]
        #expect(TeamMemberEditorView.contentEqual(a, b))
    }

    // MARK: - SessionParticipant display (I1)

    @Test func participant_displayLabelUsesNameWhenPresent() {
        let p = SessionParticipant(name: "J. Lee", role: "resident", source: "adhoc_named")
        #expect(p.displayLabel == "J. Lee")
    }

    @Test func participant_displayLabelFallsBackToRoleForAnonymousChip() {
        let p = SessionParticipant(name: nil, role: "medical_student", source: "adhoc_role")
        #expect(p.displayLabel == "Medical Student")
    }

    @Test func participant_anonymousAndNamedSameRoleHaveDistinctIds() {
        let anon = SessionParticipant(name: nil, role: "nurse", source: "adhoc_role")
        let named = SessionParticipant(name: "Pat", role: "nurse", source: "adhoc_named")
        #expect(anon.id != named.id)
    }

    // MARK: - SessionResponse participants round-trip (I4)

    @Test func sessionResponse_decodesParticipantsIncludingAnonymous() throws {
        let json = """
        {
            "id": "00000000-0000-0000-0000-0000000000aa",
            "clinician_id": "00000000-0000-0000-0000-000000000001",
            "specialty": "orthopedic_surgery",
            "state": "RECORDING",
            "encounter_type": "doctor_team_patient",
            "capture_mode": "multimodal",
            "participants": [
                {"name": "Sarah Chen", "role": "RN", "source": "profile", "is_persistent": true},
                {"name": null, "role": "nurse", "source": "adhoc_role", "is_persistent": false}
            ],
            "created_at": "2026-06-07T10:00:00Z",
            "updated_at": "2026-06-07T10:00:00Z"
        }
        """.data(using: .utf8)!
        let resp = try JSONDecoder().decode(SessionResponse.self, from: json)
        #expect(resp.participants?.count == 2)
        #expect(resp.participants?[0].name == "Sarah Chen")
        #expect(resp.participants?[0].source == "profile")
        #expect(resp.participants?[0].isPersistent == true)
        // Anonymous role chip — null name, zero PHI.
        #expect(resp.participants?[1].name == nil)
        #expect(resp.participants?[1].role == "nurse")
        #expect(resp.participants?[1].source == "adhoc_role")
    }

    @Test func sessionResponse_decodesWithoutParticipants() throws {
        // Older backend payloads omit the key entirely — must decode to nil,
        // not crash.
        let json = """
        {
            "id": "00000000-0000-0000-0000-0000000000bb",
            "clinician_id": "00000000-0000-0000-0000-000000000001",
            "specialty": "general",
            "state": "IDLE",
            "created_at": "2026-06-07T10:00:00Z",
            "updated_at": "2026-06-07T10:00:00Z"
        }
        """.data(using: .utf8)!
        let resp = try JSONDecoder().decode(SessionResponse.self, from: json)
        #expect(resp.participants == nil)
        #expect(resp.encounterType == "doctor_patient")
    }
}
