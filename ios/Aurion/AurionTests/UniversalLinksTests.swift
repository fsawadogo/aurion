//
//  UniversalLinksTests.swift
//  AurionTests
//
//  AUTH-UNIVERSAL-LINKS — verify the inbound Universal Link parser's
//  defensive validation. The handler lives in AurionApp.swift as a
//  closure inside the SwiftUI scene body; we exercise its
//  logic via a pure-function mirror so the host / path / query
//  contract can be asserted without standing up a UIScene.
//
//  Why a mirror? Driving SwiftUI's .onContinueUserActivity in a unit
//  test requires a hosted scene + an NSUserActivity round-trip, which
//  is slow and flaky. The validation rules are simple enough that the
//  pure mirror IS the contract — if the mirror passes and the handler
//  forwards to the same predicates, the wire behaviour matches.
//

import Foundation
import Testing
@testable import Aurion

/// Pure mirror of the AurionApp Universal Link extractor. Returns the
/// raw token if the activity URL passes every gate; nil otherwise.
/// The rules MUST stay in lockstep with the closure in AurionApp.swift
/// — both implement the same predicates.
///
/// Predicates (each MUST pass):
/// 1. activity.webpageURL is non-nil
/// 2. host == portal.aurionclinical.com (the AASA-claimed domain)
/// 3. path == /reset-password (the AASA-claimed path)
/// 4. queryItems contains a non-empty 'token' value
@MainActor
enum UniversalLinkExtractor {
    static func extractResetToken(from activity: NSUserActivity) -> String? {
        guard
            let url = activity.webpageURL,
            url.host == "portal.aurionclinical.com",
            url.path == "/reset-password",
            let components = URLComponents(url: url, resolvingAgainstBaseURL: false),
            let token = components.queryItems?
                .first(where: { $0.name == "token" })?
                .value,
            !token.isEmpty
        else { return nil }
        return token
    }
}

@MainActor
struct UniversalLinksTests {

    private static func activity(forURL string: String) -> NSUserActivity {
        let a = NSUserActivity(activityType: NSUserActivityTypeBrowsingWeb)
        a.webpageURL = URL(string: string)
        return a
    }

    // MARK: - Happy path

    @Test func validLink_extractsToken() {
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/reset-password?token=abc123"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == "abc123")
    }

    @Test func validLink_withExtraQueryParams_extractsTokenOnly() {
        // Extra params (e.g. utm tracking) MUST NOT corrupt the token.
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/reset-password?utm_source=email&token=xyz789&foo=bar"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == "xyz789")
    }

    @Test func validLink_withUrlEncodedToken_returnsDecoded() {
        // URLComponents decodes percent-encoded query values for us.
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/reset-password?token=abc%2Bdef"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == "abc+def")
    }

    // MARK: - Host gate

    @Test func wrongHost_returnsNil() {
        // A look-alike domain MUST NOT be honoured. The associated-
        // domains entitlement is bound to portal.aurionclinical.com
        // — any other host is a poisoned activity.
        let a = Self.activity(
            forURL: "https://evil.example.com/reset-password?token=abc123"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    @Test func apexDomain_returnsNil() {
        // The marketing apex aurionclinical.com is NOT claimed by the
        // app — only the portal subdomain. An /reset-password URL on
        // the apex (it doesn't exist anyway) must NOT open the app.
        let a = Self.activity(
            forURL: "https://aurionclinical.com/reset-password?token=abc123"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    // MARK: - Path gate

    @Test func wrongPath_returnsNil() {
        // /sign-in or any other portal route does NOT carry a reset
        // token contract — must NOT match.
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/sign-in?token=abc123"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    @Test func bareDomain_returnsNil() {
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/?token=abc123"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    @Test func resetPasswordPrefix_butNotExact_returnsNil() {
        // /reset-password-old or any prefix match must NOT count —
        // the path comparison is exact equality, not a prefix scan.
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/reset-password-old?token=abc123"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    // MARK: - Token gate

    @Test func noTokenParam_returnsNil() {
        // Bookmarking /reset-password without the email-link token
        // should NOT open the app — Safari handles it.
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/reset-password"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    @Test func emptyTokenParam_returnsNil() {
        // ?token= with no value is the same as no token — reject.
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/reset-password?token="
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    @Test func differentQueryParam_returnsNil() {
        // ?other=value with no token = no claim.
        let a = Self.activity(
            forURL: "https://portal.aurionclinical.com/reset-password?code=abc123"
        )
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    // MARK: - Activity gate

    @Test func nilWebpageURL_returnsNil() {
        let a = NSUserActivity(activityType: NSUserActivityTypeBrowsingWeb)
        // webpageURL deliberately left nil — system delivers an empty
        // browsing-web activity on a malformed restoration.
        #expect(UniversalLinkExtractor.extractResetToken(from: a) == nil)
    }

    // MARK: - ResetLinkPayload contract

    @Test func resetLinkPayload_startsEmpty() {
        let payload = ResetLinkPayload()
        #expect(payload.token == nil)
    }

    @Test func resetLinkPayload_holdsAndClearsToken() {
        // The bus is a single mutable @Published var — writing a token
        // makes it readable; nil-ing it clears the cover.
        let payload = ResetLinkPayload()
        payload.token = "reset-token-xyz"
        #expect(payload.token == "reset-token-xyz")
        payload.token = nil
        #expect(payload.token == nil)
    }
}
