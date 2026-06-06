//
//  TeamMemberEditorViewTests.swift
//  AurionTests
//
//  GH-260 — view-side contracts for the allied-health team editor
//  sheet. We exercise the persist closure surface directly (same
//  pattern as ForgotPasswordViewTests) so the unit tests stay
//  network-free and don't drag SwiftUI lifecycle into the loop.
//
//  Locked properties:
//    - localized strings parity (EN + FR keys both resolve)
//    - encodeMember strips local-only `id` and omits `email = nil`
//    - contentEqual diffs by wire fields, not by local UUIDs
//    - AlliedHealthMember decodes pre-existing rows (no email field)
//      AND new rows (with email) round-trip cleanly
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct TeamMemberEditorViewTests {

    // MARK: - Strings parity (AC-7)

    @Test func editorStrings_resolveInEnglish() {
        let keys = [
            "profile.teamEditor.title",
            "profile.teamEditor.sectionMembers",
            "profile.teamEditor.addMember",
            "profile.teamEditor.cancelAdd",
            "profile.teamEditor.confirmAdd",
            "profile.teamEditor.nameLabel",
            "profile.teamEditor.namePlaceholder",
            "profile.teamEditor.roleLabel",
            "profile.teamEditor.rolePlaceholder",
            "profile.teamEditor.emailLabel",
            "profile.teamEditor.emailPlaceholder",
            "profile.teamEditor.done",
            "profile.teamEditor.cancel",
            "profile.teamEditor.footer",
            "profile.teamEditor.saveFailed",
        ]
        for key in keys {
            #expect(L(key) != key, "missing English string for key \(key)")
        }
    }

    @Test func editorStrings_resolveInFrench() {
        // Use the FR bundle directly — the `L()` helper reads from
        // the active language, which the test harness can't easily
        // pivot mid-run. Walk the keys against the FR bundle to
        // assert parity.
        guard let path = Bundle.main.path(forResource: "fr", ofType: "lproj"),
              let bundle = Bundle(path: path)
        else {
            Issue.record("fr.lproj bundle not found in test runtime")
            return
        }
        let keys = [
            "profile.teamEditor.title",
            "profile.teamEditor.sectionMembers",
            "profile.teamEditor.addMember",
            "profile.teamEditor.cancelAdd",
            "profile.teamEditor.confirmAdd",
            "profile.teamEditor.nameLabel",
            "profile.teamEditor.namePlaceholder",
            "profile.teamEditor.roleLabel",
            "profile.teamEditor.rolePlaceholder",
            "profile.teamEditor.emailLabel",
            "profile.teamEditor.emailPlaceholder",
            "profile.teamEditor.done",
            "profile.teamEditor.cancel",
            "profile.teamEditor.footer",
            "profile.teamEditor.saveFailed",
        ]
        for key in keys {
            let value = bundle.localizedString(forKey: key, value: nil, table: nil)
            #expect(value != key, "missing French string for key \(key)")
        }
    }

    // MARK: - encodeMember (AC-4 wire shape)

    @Test func encodeMember_stripsLocalIdAndOmitsNilEmail() {
        let member = AlliedHealthMember(
            id: UUID(),
            name: "Sarah Chen",
            role: "RN",
            email: nil
        )
        let encoded = TeamMemberEditorView.encodeMember(member)
        #expect(encoded["name"] as? String == "Sarah Chen")
        #expect(encoded["role"] as? String == "RN")
        #expect(encoded["email"] == nil, "nil email must be omitted from the wire payload")
        // The local-only id never crosses the wire.
        #expect(encoded["id"] == nil)
    }

    @Test func encodeMember_includesEmailWhenPresent() {
        let member = AlliedHealthMember(
            name: "Sarah Chen",
            role: "RN",
            email: "sarah@example.com"
        )
        let encoded = TeamMemberEditorView.encodeMember(member)
        #expect(encoded["email"] as? String == "sarah@example.com")
    }

    @Test func encodeMember_omitsEmptyEmailString() {
        // Empty string after trimming should still be omitted — the
        // backend's JSON column treats present-but-empty keys as
        // populated, which would muddy any future "do they have an
        // email?" query.
        let member = AlliedHealthMember(
            name: "Sarah Chen",
            role: "RN",
            email: ""
        )
        let encoded = TeamMemberEditorView.encodeMember(member)
        #expect(encoded["email"] == nil)
    }

    // MARK: - contentEqual (AC-4 no-op dismiss)

    @Test func contentEqual_returnsTrueForIdenticalRows() {
        let a = [
            AlliedHealthMember(name: "Sarah Chen", role: "RN", email: nil),
            AlliedHealthMember(name: "Alex Wu", role: "scribe", email: "alex@example.com"),
        ]
        // Different UUIDs — the contentEqual check must ignore the
        // local id so two equivalent buffers compare equal even when
        // SwiftUI re-decoded them mid-flight.
        let b = [
            AlliedHealthMember(name: "Sarah Chen", role: "RN", email: nil),
            AlliedHealthMember(name: "Alex Wu", role: "scribe", email: "alex@example.com"),
        ]
        #expect(TeamMemberEditorView.contentEqual(a, b))
    }

    @Test func contentEqual_returnsFalseOnAddition() {
        let a: [AlliedHealthMember] = []
        let b = [AlliedHealthMember(name: "Sarah Chen", role: "RN", email: nil)]
        #expect(!TeamMemberEditorView.contentEqual(a, b))
    }

    @Test func contentEqual_returnsFalseOnEmailChange() {
        let a = [AlliedHealthMember(name: "Sarah Chen", role: "RN", email: nil)]
        let b = [AlliedHealthMember(name: "Sarah Chen", role: "RN", email: "sarah@example.com")]
        #expect(!TeamMemberEditorView.contentEqual(a, b))
    }

    @Test func contentEqual_returnsFalseOnRoleChange() {
        let a = [AlliedHealthMember(name: "Sarah Chen", role: "RN", email: nil)]
        let b = [AlliedHealthMember(name: "Sarah Chen", role: "PA", email: nil)]
        #expect(!TeamMemberEditorView.contentEqual(a, b))
    }

    // MARK: - AlliedHealthMember round-trip (back-compat)

    @Test func alliedHealthMember_decodesPreExistingRowWithoutEmail() throws {
        // The wire shape pre-#260 was `{name, role}` only — those
        // rows must keep decoding cleanly with `email = nil`.
        let json = """
        {"name": "Sarah Chen", "role": "RN"}
        """.data(using: .utf8)!
        let member = try JSONDecoder().decode(AlliedHealthMember.self, from: json)
        #expect(member.name == "Sarah Chen")
        #expect(member.role == "RN")
        #expect(member.email == nil)
        // The local id is synthesized on decode so the view can
        // render the row stably.
        _ = member.id
    }

    @Test func alliedHealthMember_decodesNewRowWithEmail() throws {
        let json = """
        {"name": "Alex Wu", "role": "scribe", "email": "alex@example.com"}
        """.data(using: .utf8)!
        let member = try JSONDecoder().decode(AlliedHealthMember.self, from: json)
        #expect(member.email == "alex@example.com")
    }

    @Test func alliedHealthMember_encodesWithoutLocalId() throws {
        let member = AlliedHealthMember(name: "Sarah Chen", role: "RN", email: nil)
        let data = try JSONEncoder().encode(member)
        let decoded = try JSONSerialization.jsonObject(with: data) as? [String: Any]
        #expect(decoded?["id"] == nil)
        #expect(decoded?["name"] as? String == "Sarah Chen")
        #expect(decoded?["role"] as? String == "RN")
        // email must not be in the payload at all (encodeIfPresent)
        #expect(decoded?["email"] == nil)
    }

    // MARK: - View constructs (AC-1 smoke)

    @Test func view_constructsWithDefaultPersist() {
        // The default initializer wires `persist` to
        // `APIClient.shared.updateProfile` — verify that the view
        // builds without exercising the network. The closure isn't
        // called at init time.
        let view = TeamMemberEditorView()
        _ = view  // touching the value forces init.
    }

    @Test func view_acceptsCustomPersistClosure() async throws {
        // Test seam — the test initializer accepts a stub closure so
        // the persistence path stays network-free. We don't actually
        // drive the body here (SwiftUI lifecycle would need a host),
        // we just confirm the closure swap takes effect on direct
        // invocation.
        actor Counter {
            var count = 0
            var lastTeam: [AlliedHealthMember] = []
            func record(_ team: [AlliedHealthMember]) {
                count += 1
                lastTeam = team
            }
            func snapshot() -> (Int, [AlliedHealthMember]) { (count, lastTeam) }
        }
        let counter = Counter()
        let stubProfile = stubProfile()
        let view = TeamMemberEditorView { team in
            await counter.record(team)
            return stubProfile
        }
        let buffer = [AlliedHealthMember(name: "Sarah Chen", role: "RN", email: nil)]
        let returned = try await view.persist(buffer)
        let (calls, lastTeam) = await counter.snapshot()
        #expect(calls == 1)
        #expect(lastTeam.count == 1)
        #expect(lastTeam.first?.name == "Sarah Chen")
        #expect(returned.clinicianId == stubProfile.clinicianId)
    }

    // MARK: - Helpers

    private func stubProfile() -> PhysicianProfileResponse {
        // Construct via JSON decode so we don't depend on the
        // memberwise init (which is `internal` and could change).
        let json = """
        {
            "clinician_id": "00000000-0000-0000-0000-000000000001",
            "display_name": "Dr. Test",
            "practice_type": "clinic",
            "primary_specialty": "general",
            "preferred_templates": ["general"],
            "consultation_types": ["follow_up"],
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
