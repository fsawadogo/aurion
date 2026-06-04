//
//  CognitoNativeAuthMfaTests.swift
//  AurionTests
//
//  AUR-COG-MFA — verify the Cognito MFA request shape, response parsing,
//  and the SUCCESS/ERROR/CodeMismatchException collapse into
//  TotpVerificationOutcome.
//

import Foundation
import Testing
@testable import Aurion

/// URLProtocol-based fake — captures the outgoing request and serves the
/// scripted response. One global recorder per test; reset in `setUp`.
final class CognitoMfaURLProtocol: URLProtocol {
    /// `(target, statusCode, jsonBody)` — keyed by `X-Amz-Target` so a
    /// single test can script multiple Cognito calls in order.
    nonisolated(unsafe) static var responses: [String: (Int, [String: Any])] = [:]
    /// Captured request bodies, keyed by target.
    nonisolated(unsafe) static var capturedBodies: [String: [String: Any]] = [:]
    /// Captured headers, keyed by target.
    nonisolated(unsafe) static var capturedHeaders: [String: [String: String]] = [:]

    static func reset() {
        responses = [:]
        capturedBodies = [:]
        capturedHeaders = [:]
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let target = (request.value(forHTTPHeaderField: "X-Amz-Target") ?? "")
            .replacingOccurrences(of: "AWSCognitoIdentityProviderService.", with: "")

        // URLProtocol strips the body off `request.httpBody` when it's
        // populated via a stream — read both, prefer body, fall back to stream.
        var bodyData = request.httpBody ?? Data()
        if bodyData.isEmpty, let stream = request.httpBodyStream {
            stream.open()
            let buffer = UnsafeMutablePointer<UInt8>.allocate(capacity: 4096)
            defer { buffer.deallocate(); stream.close() }
            while stream.hasBytesAvailable {
                let read = stream.read(buffer, maxLength: 4096)
                if read <= 0 { break }
                bodyData.append(buffer, count: read)
            }
        }
        if let json = try? JSONSerialization.jsonObject(with: bodyData) as? [String: Any] {
            Self.capturedBodies[target] = json
        }
        Self.capturedHeaders[target] = request.allHTTPHeaderFields ?? [:]

        let (status, json) = Self.responses[target] ?? (500, [:])
        let data = (try? JSONSerialization.data(withJSONObject: json)) ?? Data()
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/x-amz-json-1.1"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

/// The URLProtocol fake holds global request/response state; running the
/// suite serialized keeps the dispatch table single-tenanted. Cheap, no
/// concurrency benefit lost — each test takes < 100 ms.
@MainActor
@Suite(.serialized)
struct CognitoNativeAuthMfaTests {

    /// URLSession configured to route every request through the test
    /// protocol. One instance per test — cheaper than reinitializing in
    /// each method and isolated state lives in `CognitoMfaURLProtocol`.
    private static func makeAuthClient() -> CognitoNativeAuth {
        CognitoMfaURLProtocol.reset()
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [CognitoMfaURLProtocol.self]
        return CognitoNativeAuth(urlSession: URLSession(configuration: config))
    }

    // MARK: - respondToTotpChallenge — request shape

    @Test func respondToTotpChallenge_postsCorrectShape() async throws {
        let client = Self.makeAuthClient()
        // Scripted happy path — Cognito returns AuthenticationResult.
        CognitoMfaURLProtocol.responses["RespondToAuthChallenge"] = (200, [
            "AuthenticationResult": [
                "AccessToken": "access-1",
                "IdToken": "id-1",
                "RefreshToken": "refresh-1",
                "ExpiresIn": 3600,
            ],
        ])

        let outcome = try await client.respondToTotpChallenge(
            session: "session-abc",
            username: "physician@example.com",
            code: "123456"
        )

        // 1. Outcome is authenticated.
        guard case .authenticated(let auth) = outcome else {
            Issue.record("expected .authenticated, got \(outcome)"); return
        }
        #expect(auth.accessToken == "access-1")

        // 2. Request was sent with the expected envelope.
        let body = CognitoMfaURLProtocol.capturedBodies["RespondToAuthChallenge"]
        #expect(body?["ChallengeName"] as? String == "SOFTWARE_TOKEN_MFA")
        #expect(body?["Session"] as? String == "session-abc")
        let challengeResponses = body?["ChallengeResponses"] as? [String: String]
        #expect(challengeResponses?["USERNAME"] == "physician@example.com")
        #expect(challengeResponses?["SOFTWARE_TOKEN_MFA_CODE"] == "123456")

        // 3. The Cognito JSON 1.1 header conventions are honoured.
        let headers = CognitoMfaURLProtocol.capturedHeaders["RespondToAuthChallenge"] ?? [:]
        #expect(headers["Content-Type"] == "application/x-amz-json-1.1")
    }

    // MARK: - signInForMfaSetup — returns the next-step session

    @Test func signInForMfaSetup_returnsMfaSetupRequiredWithNewSession() async throws {
        let client = Self.makeAuthClient()
        CognitoMfaURLProtocol.responses["RespondToAuthChallenge"] = (200, [
            // No AuthenticationResult — Cognito just hands back a fresh
            // session for AssociateSoftwareToken.
            "Session": "next-session-xyz",
        ])

        let outcome = try await client.signInForMfaSetup(
            session: "initial-session",
            username: "physician@example.com"
        )

        guard case .mfaSetupRequired(let session, let username) = outcome else {
            Issue.record("expected .mfaSetupRequired, got \(outcome)"); return
        }
        #expect(session == "next-session-xyz")
        #expect(username == "physician@example.com")

        let body = CognitoMfaURLProtocol.capturedBodies["RespondToAuthChallenge"]
        #expect(body?["ChallengeName"] as? String == "MFA_SETUP")
        let cr = body?["ChallengeResponses"] as? [String: String]
        #expect(cr?["USERNAME"] == "physician@example.com")
    }

    // MARK: - beginTotpSetup — parses SecretCode + Session

    @Test func beginTotpSetup_session_parsesSecretAndSession() async throws {
        let client = Self.makeAuthClient()
        CognitoMfaURLProtocol.responses["AssociateSoftwareToken"] = (200, [
            "SecretCode": "JBSWY3DPEHPK3PXP",
            "Session": "associate-session-1",
        ])

        let setup = try await client.beginTotpSetup(session: "incoming-session")

        #expect(setup.secretCode == "JBSWY3DPEHPK3PXP")
        #expect(setup.session == "associate-session-1")

        // Request body should contain Session (not AccessToken).
        let body = CognitoMfaURLProtocol.capturedBodies["AssociateSoftwareToken"]
        #expect(body?["Session"] as? String == "incoming-session")
        #expect(body?["AccessToken"] == nil)
    }

    @Test func beginTotpSetup_accessToken_parsesSecretWithNoSession() async throws {
        let client = Self.makeAuthClient()
        CognitoMfaURLProtocol.responses["AssociateSoftwareToken"] = (200, [
            "SecretCode": "JBSWY3DPEHPK3PXP",
            // No Session in the access-token-based call.
        ])

        let setup = try await client.beginTotpSetup(accessToken: "access-1")

        #expect(setup.secretCode == "JBSWY3DPEHPK3PXP")
        #expect(setup.session == nil)
        let body = CognitoMfaURLProtocol.capturedBodies["AssociateSoftwareToken"]
        #expect(body?["AccessToken"] as? String == "access-1")
        #expect(body?["Session"] == nil)
    }

    @Test func beginTotpSetup_missingSecret_throwsMalformed() async throws {
        let client = Self.makeAuthClient()
        CognitoMfaURLProtocol.responses["AssociateSoftwareToken"] = (200, [:])

        do {
            _ = try await client.beginTotpSetup(session: "s")
            Issue.record("expected throw")
        } catch let error as NativeAuthError {
            // The exhaustive switch in errorDescription should pick the
            // .malformed case — comparing description text is the lightest
            // way to identify the case without exposing internals.
            #expect(error.errorDescription?.contains("couldn") == true ||
                    error.errorDescription?.contains("Cognito returned") == true)
        }
    }

    // MARK: - verifyTotpSetup — SUCCESS / ERROR / CodeMismatchException

    @Test func verifyTotpSetup_success_returnsSuccessWithSession() async throws {
        let client = Self.makeAuthClient()
        CognitoMfaURLProtocol.responses["VerifySoftwareToken"] = (200, [
            "Status": "SUCCESS",
            "Session": "post-verify-session",
        ])

        let outcome = try await client.verifyTotpSetup(
            session: "in-session",
            code: "987654",
            friendlyDeviceName: "Aurion iPhone"
        )

        guard case .success(let nextSession) = outcome else {
            Issue.record("expected .success"); return
        }
        #expect(nextSession == "post-verify-session")

        // Verify the request includes UserCode and FriendlyDeviceName.
        let body = CognitoMfaURLProtocol.capturedBodies["VerifySoftwareToken"]
        #expect(body?["UserCode"] as? String == "987654")
        #expect(body?["FriendlyDeviceName"] as? String == "Aurion iPhone")
        #expect(body?["Session"] as? String == "in-session")
    }

    @Test func verifyTotpSetup_status_ERROR_returnsCodeMismatch() async throws {
        let client = Self.makeAuthClient()
        CognitoMfaURLProtocol.responses["VerifySoftwareToken"] = (200, [
            "Status": "ERROR",
        ])

        let outcome = try await client.verifyTotpSetup(
            session: "s",
            code: "111111",
            friendlyDeviceName: "Aurion iPhone"
        )

        guard case .codeMismatch = outcome else {
            Issue.record("expected .codeMismatch on Status=ERROR"); return
        }
    }

    @Test func verifyTotpSetup_codeMismatchException_returnsCodeMismatch() async throws {
        let client = Self.makeAuthClient()
        // Non-200 with the canonical Cognito error envelope.
        CognitoMfaURLProtocol.responses["VerifySoftwareToken"] = (400, [
            "__type": "CodeMismatchException",
            "message": "Invalid code received for user",
        ])

        let outcome = try await client.verifyTotpSetup(
            session: "s",
            code: "222222",
            friendlyDeviceName: "Aurion iPhone"
        )

        guard case .codeMismatch = outcome else {
            Issue.record("expected .codeMismatch on CodeMismatchException"); return
        }
    }

    @Test func verifyTotpSetup_expiredCode_bubblesError() async throws {
        let client = Self.makeAuthClient()
        CognitoMfaURLProtocol.responses["VerifySoftwareToken"] = (400, [
            "__type": "ExpiredCodeException",
            "message": "Your code has expired",
        ])

        do {
            _ = try await client.verifyTotpSetup(
                session: "s",
                code: "333333",
                friendlyDeviceName: "Aurion iPhone"
            )
            Issue.record("expected throw — expired isn't a codeMismatch")
        } catch let error as NativeAuthError {
            #expect(error.errorDescription == "Code expired. Enter the current one.")
        }
    }

    // MARK: - NativeAuthError mapping for the new error types

    @Test func nativeAuthError_codeMismatch_isGeneric() {
        let err = NativeAuthError.cognito(
            type: "CodeMismatchException",
            message: "Invalid code 123456"   // Cognito sometimes echoes input.
        )
        let description = err.errorDescription ?? ""
        // Must not echo any digit the user typed.
        #expect(description == "Incorrect code. Try again.")
        #expect(!description.contains("123456"))
    }

    @Test func nativeAuthError_expiredCode_descriptionIsActionable() {
        let err = NativeAuthError.cognito(
            type: "ExpiredCodeException",
            message: "anything"
        )
        #expect(err.errorDescription == "Code expired. Enter the current one.")
    }

    @Test func nativeAuthError_enableSoftwareTokenMFA_rendersHumanString() {
        let err = NativeAuthError.cognito(
            type: "EnableSoftwareTokenMFAException",
            message: "raw cognito blob"
        )
        let description = err.errorDescription ?? ""
        // Generic, human-friendly, no Cognito jargon.
        #expect(description.lowercased().contains("two-factor"))
        #expect(!description.contains("raw cognito blob"))
    }

    @Test func nativeAuthError_softwareTokenMFANotFound_rendersHumanString() {
        let err = NativeAuthError.cognito(
            type: "SoftwareTokenMFANotFoundException",
            message: "raw cognito blob"
        )
        let description = err.errorDescription ?? ""
        #expect(description.lowercased().contains("two-factor"))
        #expect(!description.contains("raw cognito blob"))
    }

    // MARK: - Challenge dispatch — MFA_SETUP routes to .mfaSetupRequired

    @Test func signIn_initiateAuthMfaSetupChallenge_routesToSetupRequired() async throws {
        let client = Self.makeAuthClient()
        CognitoMfaURLProtocol.responses["InitiateAuth"] = (200, [
            "ChallengeName": "MFA_SETUP",
            "Session": "setup-session-1",
        ])

        let outcome = try await client.signIn(
            email: "physician@example.com",
            password: "pw"
        )
        guard case .mfaSetupRequired(let session, let username) = outcome else {
            Issue.record("expected .mfaSetupRequired, got \(outcome)"); return
        }
        #expect(session == "setup-session-1")
        #expect(username == "physician@example.com")
    }
}
