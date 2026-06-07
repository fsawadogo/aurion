//
//  ParseISODateTests.swift
//  AurionTests
//
//  #279 — the shared fractional-tolerant ISO-8601 parser
//  (`Theme.parseISODate`) that the dashboard count, the sessions inbox
//  date filter, the note-detail header, and the relative-time formatter
//  all route backend `created_at` strings through.
//
//  Locked behavior:
//    - parses the backend's fractional-seconds format (the regression
//      that made "0 sessions today" always read 0)
//    - still parses legacy plain (no-fractional) timestamps
//    - returns nil on garbage (callers treat nil as "don't hide / don't
//      count", never a crash)
//    - the dashboard's today-count logic (parse + isDateInToday) counts a
//      fractional-timestamp session created today
//

import Foundation
import Testing
@testable import Aurion

struct ParseISODateTests {

    // AC-1 — the regression: fractional seconds must parse.
    @Test func parsesFractionalSeconds() {
        let d = parseISODate("2026-06-06T17:04:21.690+00:00")
        #expect(d != nil, "fractional-seconds backend timestamp must parse")
    }

    @Test func parsesFractionalSecondsZulu() {
        // The `...629Z` shape Theme's own comment documents.
        #expect(parseISODate("2026-05-31T02:26:51.629Z") != nil)
    }

    // AC-2 — legacy plain timestamps still parse.
    @Test func parsesPlain() {
        #expect(parseISODate("2026-06-06T17:04:21Z") != nil)
        #expect(parseISODate("2026-06-06T17:04:21+00:00") != nil)
    }

    // AC-3 — garbage returns nil (callers must not crash).
    @Test func rejectsGarbage() {
        #expect(parseISODate("not-a-date") == nil)
        #expect(parseISODate("") == nil)
    }

    // AC-4 — the dashboard count logic over a fractional "today" timestamp.
    @Test func countsTodayWithFractionalSeconds() {
        let cal = Calendar.current
        // Build a fractional-seconds ISO string for "now" the same way the
        // backend serializes created_at, then assert the shared parser +
        // isDateInToday (the exact todayCount predicate) counts it.
        let fmt = ISO8601DateFormatter()
        fmt.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let iso = fmt.string(from: Date())
        guard let parsed = parseISODate(iso) else {
            Issue.record("fractional 'now' must parse")
            return
        }
        #expect(cal.isDateInToday(parsed), "a fractional timestamp for now must count as today")
    }

    @Test func plainAndFractionalResolveToSameInstant() {
        // The two formats for the same wall-clock instant must agree, so
        // routing legacy + modern rows through one parser is consistent.
        let frac = parseISODate("2026-06-06T17:04:21.000Z")
        let plain = parseISODate("2026-06-06T17:04:21Z")
        #expect(frac == plain)
    }
}
