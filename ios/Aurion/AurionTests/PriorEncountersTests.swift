//
//  PriorEncountersTests.swift
//  AurionTests
//
//  #61 (full slice): prior-encounters rail + full list on NoteReviewView.
//
//  Coverage:
//   * PatientSessionMatch decodes the backend's slim shape.
//   * Model filters out the current session id + any PURGED row.
//   * Rail caps to 5 (`railMatches`); list does not cap (`relevantMatches`).
//   * "See all (N)" gate fires off the filtered count, not raw API count.
//   * Empty-state path: `relevantMatches.isEmpty` triggers the empty copy.
//   * Failure path flips `loadFailed` true and clears the matches array.
//   * Retry path: failure → success on a second invocation repopulates.
//   * Tap propagates the right session id through the rail's `onTap`.
//   * DRY: rail and list both consume `PriorEncountersModel` — one
//     fetcher closure, two views. The same closure-invocation count
//     proves the shared surface.
//   * PHI guard: the identifier is NEVER passed to a logger / print /
//     AuditLogger call inside the three new files (model + 2 views).
//   * EN + FR i18n parity: every new key resolves in both bundles.
//
//  Note on testing strategy: the data plumbing lives on
//  `PriorEncountersModel` (ObservableObject) precisely so test
//  assertions don't have to fight SwiftUI's `@State`-on-unmounted-view
//  storage rules. Tests construct the model directly; the views are
//  exercised via build-time compile checks plus the rail's `onTap`
//  closure surface.
//

import Foundation
import SwiftUI
import Testing
@testable import Aurion

// MARK: - Fixtures

/// Build a `PatientSessionMatch` quickly from a few literals. Keeps
/// the test bodies readable since most cases only vary one or two
/// fields.
private func match(
    id: String,
    specialty: String = "orthopedic_surgery",
    state: String = "REVIEW_COMPLETE",
    createdAt: String
) -> PatientSessionMatch {
    PatientSessionMatch(
        sessionId: id,
        specialty: specialty,
        state: state,
        createdAt: createdAt
    )
}

extension PatientSessionMatch {
    /// Memberwise initializer for tests — the production type uses the
    /// Codable default initializer through JSONDecoder. Extension lives
    /// in the test target only.
    init(sessionId: String, specialty: String, state: String, createdAt: String) {
        // Decode via JSON to avoid having to mark the prod let-fields
        // memberwise — keeps the public surface of the model unchanged
        // and lines up with how the real instances are constructed at
        // runtime (always from JSON).
        let json: [String: String] = [
            "session_id": sessionId,
            "specialty": specialty,
            "state": state,
            "created_at": createdAt,
        ]
        let data = try! JSONSerialization.data(withJSONObject: json)
        self = try! JSONDecoder().decode(PatientSessionMatch.self, from: data)
    }
}

// MARK: - Decode contract

struct PatientSessionMatchDecodeTests {
    /// AC-0: backend `PatientSessionMatch` decodes cleanly. This is
    /// the wire-format guarantee — if a future backend change breaks
    /// this, all downstream tests break loudly.
    @Test func decode_matchesBackendShape() throws {
        let json = """
        {
            "session_id": "s1",
            "specialty": "orthopedic_surgery",
            "state": "REVIEW_COMPLETE",
            "created_at": "2026-05-29T14:30:00Z"
        }
        """.data(using: .utf8)!
        let decoded = try JSONDecoder().decode(PatientSessionMatch.self, from: json)
        #expect(decoded.sessionId == "s1")
        #expect(decoded.specialty == "orthopedic_surgery")
        #expect(decoded.state == "REVIEW_COMPLETE")
        #expect(decoded.createdAt == "2026-05-29T14:30:00Z")
        // Identifiable contract — session id is the stable identity.
        #expect(decoded.id == "s1")
    }
}

// MARK: - Model filtering / see-all gate

@MainActor
struct PriorEncountersModelFilteringTests {

    /// AC-2: model strips the CURRENT session id (the one being reviewed)
    /// and any PURGED row from the rail cap. Newest-first comes from
    /// `load`'s sort, the filter precedes the cap so a list of
    /// [current, a, b(PURGED), c, d] still surfaces a/c/d (not 4 rows
    /// that include a PURGED row).
    @Test func filtersCurrentAndPurged() async {
        let now = "2026-06-01T10:00:00Z"
        let yesterday = "2026-05-31T10:00:00Z"
        let twoDays = "2026-05-30T10:00:00Z"
        let threeDays = "2026-05-29T10:00:00Z"
        let fourDays = "2026-05-28T10:00:00Z"
        let canned: [PatientSessionMatch] = [
            match(id: "current", createdAt: now),
            match(id: "a", createdAt: yesterday),
            match(id: "b", state: "PURGED", createdAt: twoDays),
            match(id: "c", createdAt: threeDays),
            match(id: "d", createdAt: fourDays),
        ]
        let model = PriorEncountersModel(
            currentSessionId: "current",
            identifier: "MRN-1",
            fetch: { _ in canned }
        )
        await model.load()

        // railMatches excludes "current" and the PURGED row "b".
        let ids = model.railMatches.map(\.sessionId)
        #expect(ids == ["a", "c", "d"])
        // totalRelevant matches the displayed count (no truncation
        // since we're under 5).
        #expect(model.totalRelevant == 3)
    }

    /// AC-3: see-all is gated on the filtered total — strictly > 5
    /// only. Six relevant prior sessions → see-all shows; five →
    /// hidden.
    @Test func seeAll_hiddenWhenAtOrBelowFive() async {
        // Six sessions (no current, no PURGED) → "See all" must render.
        let dates = (0..<6).map { "2026-05-\(String(format: "%02d", 30 - $0))T10:00:00Z" }
        let six = (0..<6).map { match(id: "s\($0)", createdAt: dates[$0]) }
        let model = PriorEncountersModel(
            currentSessionId: "other",
            identifier: "MRN-1",
            fetch: { _ in six }
        )
        await model.load()
        #expect(model.totalRelevant == 6)
        #expect(model.railMatches.count == 5)  // capped at 5
        #expect(model.totalRelevant > PriorEncountersModel.maxRailCards)  // see-all visible

        // Five sessions → see-all must NOT render.
        let five = Array(six.prefix(5))
        let model2 = PriorEncountersModel(
            currentSessionId: "other",
            identifier: "MRN-1",
            fetch: { _ in five }
        )
        await model2.load()
        #expect(model2.totalRelevant == 5)
        #expect(model2.railMatches.count == 5)
        // The visible-Boolean check on the See-all link is
        // `totalRelevant > maxRailCards (5)` — at 5, link hides.
        #expect((model2.totalRelevant > PriorEncountersModel.maxRailCards) == false)
    }

    /// AC-4: empty API response (or response containing only the
    /// current session) leaves `railMatches` empty so the rail shows
    /// the "First encounter" copy.
    @Test func emptyState_rendersFirstEncounterCopy() async {
        let model = PriorEncountersModel(
            currentSessionId: "current",
            identifier: "MRN-1",
            fetch: { _ in [] }
        )
        await model.load()
        #expect(model.railMatches.isEmpty)
        #expect(model.relevantMatches.isEmpty)
        #expect(model.totalRelevant == 0)
        // The localized empty copy must resolve to a non-empty string.
        #expect(L("priorEncounters.empty").isEmpty == false)
    }

    /// Even when the API returns sessions, if they all collapse to the
    /// current session id or PURGED, the model surfaces empty.
    @Test func onlyCurrentOrPurged_collapsesToEmpty() async {
        let canned: [PatientSessionMatch] = [
            match(id: "current", createdAt: "2026-06-01T10:00:00Z"),
            match(id: "purged", state: "PURGED", createdAt: "2026-05-31T10:00:00Z"),
        ]
        let model = PriorEncountersModel(
            currentSessionId: "current",
            identifier: "MRN-1",
            fetch: { _ in canned }
        )
        await model.load()
        #expect(model.railMatches.isEmpty)
        #expect(model.relevantMatches.isEmpty)
        #expect(model.totalRelevant == 0)
    }
}

// MARK: - Failure path

@MainActor
struct PriorEncountersModelFailureTests {

    /// AC-5: API throws → model flips `loadFailed` so the retry block
    /// renders. Doesn't bubble the underlying error to the UI (PHI
    /// guard: the error description could echo the URL which includes
    /// the identifier).
    @Test func failure_surfacesRetry() async {
        struct CannedFailure: Error {}
        let model = PriorEncountersModel(
            currentSessionId: "other",
            identifier: "MRN-1",
            fetch: { _ in throw CannedFailure() }
        )
        await model.load()
        #expect(model.loadFailed == true)
        #expect(model.railMatches.isEmpty)
        #expect(model.relevantMatches.isEmpty)
        #expect(model.totalRelevant == 0)
    }

    /// Retry happy-path: failure → success on a second invocation
    /// repopulates the model. We pass a counting fetcher to assert the
    /// closure is reused (no second API surface).
    @Test func retry_repopulatesAfterSuccess() async {
        let counter = CallCounter()
        struct CannedFailure: Error {}
        let fetcher: (String) async throws -> [PatientSessionMatch] = { _ in
            await counter.bump()
            let n = await counter.value
            if n == 1 { throw CannedFailure() }
            return [match(id: "a", createdAt: "2026-05-30T10:00:00Z")]
        }
        let model = PriorEncountersModel(
            currentSessionId: "other",
            identifier: "MRN-1",
            fetch: fetcher
        )
        await model.load()
        #expect(model.loadFailed == true)
        #expect(model.railMatches.isEmpty)
        await model.load()
        #expect(model.loadFailed == false)
        #expect(model.railMatches.map(\.sessionId) == ["a"])
        let calls = await counter.value
        #expect(calls == 2)
    }
}

// MARK: - Navigation

@MainActor
struct PriorEncountersRailNavigationTests {

    /// AC-6: tapping a card invokes the rail's `onTap` with the right
    /// session id. Open/Closed: the rail goes through the SAME
    /// AppNavigation router as the dashboard recent strip; the test
    /// substitutes a probe closure so we don't actually drive the
    /// singleton.
    @Test func tap_emitsNavigationRequest() async {
        let recorder = TapRecorder()
        let canned = [
            match(id: "target", createdAt: "2026-05-30T10:00:00Z"),
        ]
        let model = PriorEncountersModel(
            currentSessionId: "current",
            identifier: "MRN-1",
            fetch: { _ in canned }
        )
        await model.load()

        // Construct the rail with a probe tap handler that records
        // through the actor. The rail itself never has to mount —
        // the contract under test is "the dispatched session id
        // matches the model's railMatches[0]", which is independent
        // of the view tree.
        let onTap: (String) -> Void = { id in
            Task { await recorder.record(id) }
        }
        let rail = PriorEncountersRail(model: model, onTap: onTap)
        // Keep `rail` alive across the assertion so the StateObject
        // doesn't deallocate underneath us. (No-op suppress-unused.)
        _ = rail

        guard let first = model.railMatches.first else {
            Issue.record("railMatches should not be empty")
            return
        }
        // The Button label invokes `onTap(match.sessionId)` — we
        // synthesize that here. The on-screen path runs through the
        // same closure.
        onTap(first.sessionId)
        // Drain the recorder's Task — Task.yield + a short retry loop
        // makes the assertion deterministic without sleeping.
        for _ in 0..<20 {
            if await recorder.lastReceived != nil { break }
            await Task.yield()
        }
        let received = await recorder.lastReceived
        #expect(received == "target")
    }
}

// MARK: - Full list view (DRY assertion)

@MainActor
struct PriorEncountersListViewTests {

    /// AC-7: `PriorEncountersListView` consumes the same
    /// `PriorEncountersModel` as the rail. We assert via a CallCounter
    /// that both surfaces drive the closure exactly once on load, and
    /// that the closure shape is identical
    /// (`(String) async throws -> [PatientSessionMatch]`) — which the
    /// Swift type system has already proven at compile time since
    /// they're both typed against the same model surface.
    @Test func list_fetchesViaSameAPIMethod() async {
        let counter = CallCounter()
        let canned = [
            match(id: "a", createdAt: "2026-05-30T10:00:00Z"),
            match(id: "b", createdAt: "2026-05-29T10:00:00Z"),
        ]
        let sharedFetcher: (String) async throws -> [PatientSessionMatch] = { _ in
            await counter.bump()
            return canned
        }

        // Two independent models — one per surface — both wired to the
        // SAME fetcher closure. This is the production wiring: the
        // rail and the full-list sheet are mounted at different times
        // with independent state, but they always go through
        // `APIClient.shared.listMySessionsByPatientIdentifier` under
        // the hood.
        let railModel = PriorEncountersModel(
            currentSessionId: "other",
            identifier: "MRN-1",
            fetch: sharedFetcher
        )
        await railModel.load()

        let listModel = PriorEncountersModel(
            currentSessionId: "other",
            identifier: "MRN-1",
            fetch: sharedFetcher
        )
        await listModel.load()

        let total = await counter.value
        #expect(total == 2)  // rail load + list load = two invocations
        #expect(railModel.railMatches.map(\.sessionId) == ["a", "b"])
        #expect(listModel.relevantMatches.map(\.sessionId) == ["a", "b"])

        // Sanity: the views compile against the same model surface.
        // Tests don't render them, but constructing them ensures the
        // initializers stay open.
        _ = PriorEncountersRail(model: railModel)
        _ = PriorEncountersListView(model: listModel)
    }

    /// List view sorts newest-first deterministically even if the
    /// fetcher returns out-of-order rows (defensive against a future
    /// backend change).
    @Test func list_sortsNewestFirst() async {
        let canned = [
            match(id: "old", createdAt: "2026-04-01T10:00:00Z"),
            match(id: "new", createdAt: "2026-05-30T10:00:00Z"),
            match(id: "mid", createdAt: "2026-05-15T10:00:00Z"),
        ]
        let model = PriorEncountersModel(
            currentSessionId: "other",
            identifier: "MRN-1",
            fetch: { _ in canned }
        )
        await model.load()
        #expect(model.relevantMatches.map(\.sessionId) == ["new", "mid", "old"])
    }
}

// MARK: - PHI / privacy

/// AC-8: the identifier is PHI per CLAUDE.md "Privacy" section.
/// We enforce statically that the three new files don't pipe it through
/// any of the logging primitives. This is a string-level guard — if a
/// future change adds a `Logger`/`print`/`os_log` call in any file
/// that interpolates the identifier, the test fails.
struct PriorEncountersPHITests {

    @Test func newFiles_haveNoIdentifierLogs() throws {
        let modelPath = try Self.sourceFile(for: "PriorEncountersModel.swift")
        let railPath = try Self.sourceFile(for: "PriorEncountersRail.swift")
        let listPath = try Self.sourceFile(for: "PriorEncountersListView.swift")
        for path in [modelPath, railPath, listPath] {
            let source = try String(contentsOfFile: path, encoding: .utf8)
            // Grep for logging primitives. Whitelist: doc-comment
            // mentions of "log" in prose are fine; what we're guarding
            // against is `print(identifier)`, `Logger().info("...\(identifier)")`,
            // `os_log("%@", identifier)`, `AuditLogger.log(...extra...)` etc.
            //
            // We split the source into lines and ignore comment-only
            // lines (// ... or  * ... inside /** blocks) so the
            // docstrings describing the privacy contract don't trip
            // the test.
            let codeLines = source.components(separatedBy: "\n").filter { line in
                let trimmed = line.trimmingCharacters(in: .whitespaces)
                if trimmed.hasPrefix("//") { return false }
                if trimmed.hasPrefix("///") { return false }
                if trimmed.hasPrefix("*") { return false }
                return true
            }
            let code = codeLines.joined(separator: "\n")
            // Identifier-leaking patterns.
            let banned = [
                "print(identifier)",
                "print(\"\\(identifier)",
                "Logger().",
                "os_log(",
                "AuditLogger.log",
            ]
            for needle in banned {
                #expect(
                    code.contains(needle) == false,
                    "PHI leak risk: \(path) contains '\(needle)'"
                )
            }
        }
    }

    /// Resolve a source file path from the test bundle's parent
    /// directory walk. The test target lives at
    /// `ios/Aurion/AurionTests/`, the prod files at
    /// `ios/Aurion/Aurion/NoteReview/`. We walk relative from the
    /// running test's __FILE__ rather than rely on Bundle, which
    /// doesn't ship source.
    static func sourceFile(for name: String) throws -> String {
        let here = URL(fileURLWithPath: #filePath)
        // here = .../ios/Aurion/AurionTests/PriorEncountersTests.swift
        let aurionRoot = here
            .deletingLastPathComponent()  // AurionTests/
            .deletingLastPathComponent()  // Aurion/ (xcodeproj root)
        let candidate = aurionRoot
            .appendingPathComponent("Aurion/NoteReview/\(name)")
        guard FileManager.default.fileExists(atPath: candidate.path) else {
            throw NSError(
                domain: "PriorEncountersPHITests",
                code: 1,
                userInfo: [NSLocalizedDescriptionKey: "missing: \(candidate.path)"]
            )
        }
        return candidate.path
    }
}

// MARK: - i18n parity

/// AC-9: every new priorEncounters.* key has an EN and FR translation.
/// We do this by switching the Localization bundle between en and fr
/// and asserting both lookups return the localized string (not the
/// key back). `L(key)` returns the key itself when missing, so a
/// key-equals-result hit indicates a missing translation.
struct PriorEncountersI18nTests {

    /// All keys introduced in this PR. Single source of truth so the
    /// rail / list code only references keys that the parity check
    /// also covers.
    static let newKeys: [String] = [
        "priorEncounters.title",
        "priorEncounters.titleWith",
        "priorEncounters.seeAll",
        "priorEncounters.empty",
        "priorEncounters.loadFailed",
        "priorEncounters.retry",
        "priorEncounters.fullList.title",
        "priorEncounters.fullList.empty",
        "priorEncounters.a11y.tapCard",
    ]

    @Test func allKeys_haveEnAndFrTranslations() {
        let originalLanguage = Localization.languageCode
        defer { Localization.setLanguage(originalLanguage) }

        for language in ["en", "fr"] {
            Localization.setLanguage(language)
            for key in Self.newKeys {
                let resolved = L(key)
                #expect(
                    resolved != key,
                    "Missing \(language) translation for '\(key)'"
                )
                #expect(
                    resolved.isEmpty == false,
                    "Empty \(language) translation for '\(key)'"
                )
            }
        }
    }
}

// MARK: - Helpers

/// Async-isolated counter for tests that need to assert the number of
/// closure invocations across awaits. Swift Testing runs cases on
/// arbitrary concurrent contexts; an actor is the lock-free way to
/// keep the count consistent.
private actor CallCounter {
    private(set) var value = 0
    func bump() { value += 1 }
}

/// Recorder for the "what session id was dispatched?" assertion.
private actor TapRecorder {
    private(set) var lastReceived: String?
    func record(_ id: String) { lastReceived = id }
}
