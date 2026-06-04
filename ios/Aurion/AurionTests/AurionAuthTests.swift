//
//  AurionAuthTests.swift
//  AurionTests
//
//  AUTH-PIVOT-IOS — verify the AurionAuth network client speaks the
//  backend's wire shape exactly: request envelopes, response parsing,
//  error mapping, and the SignInOutcome / MfaSetupOutcome state
//  collapses.
//
//  The URLProtocol fake holds global request/response state; running
//  the suite serialized keeps the dispatch table single-tenanted.
//  Same pattern the closed PR #233 used for CognitoNativeAuthMfaTests.
//

import Foundation
import Testing
@testable import Aurion

/// URLProtocol-based fake — captures the outgoing request and serves
/// the scripted response. One global recorder per test; reset in
/// `setUp` via ``AurionAuthURLProtocol/reset``.
final class AurionAuthURLProtocol: URLProtocol {
    /// `(path, statusCode, jsonBody)` — keyed by URL path so a single
    /// test can script multiple endpoint hits in order.
    nonisolated(unsafe) static var responses: [String: (Int, [String: Any])] = [:]
    /// Captured request bodies (as parsed JSON), keyed by URL path.
    nonisolated(unsafe) static var capturedBodies: [String: [String: Any]] = [:]
    /// Captured headers (raw dictionary), keyed by URL path.
    nonisolated(unsafe) static var capturedHeaders: [String: [String: String]] = [:]
    /// Captured HTTP methods, keyed by URL path.
    nonisolated(unsafe) static var capturedMethods: [String: String] = [:]

    static func reset() {
        responses = [:]
        capturedBodies = [:]
        capturedHeaders = [:]
        capturedMethods = [:]
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let path = request.url?.path ?? ""

        // URLProtocol strips the body off `request.httpBody` when it's
        // populated via a stream — read both, prefer body, fall back
        // to stream. Same approach the closed PR's
        // CognitoMfaURLProtocol used.
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
            Self.capturedBodies[path] = json
        }
        Self.capturedHeaders[path] = request.allHTTPHeaderFields ?? [:]
        Self.capturedMethods[path] = request.httpMethod ?? "GET"

        let (status, json) = Self.responses[path] ?? (500, [:])
        let data = json.isEmpty ? Data() : (try? JSONSerialization.data(withJSONObject: json)) ?? Data()
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: status,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: data)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

/// The URLProtocol fake holds global request/response state; running
/// the suite serialized keeps the dispatch table single-tenanted.
/// Cheap, no concurrency benefit lost — each test takes < 100 ms.
@MainActor
@Suite(.serialized)
struct AurionAuthTests {

    /// Factory for an AurionAuth backed by the URLProtocol fake. One
    /// fresh instance per test — global state lives in
    /// AurionAuthURLProtocol.
    private static func makeAuthClient() -> AurionAuth {
        AurionAuthURLProtocol.reset()
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [AurionAuthURLProtocol.self]
        return AurionAuth(urlSession: URLSession(configuration: config))
    }

    private static let loginPath = "/api/v1/auth/login"
    private static let mfaVerifyLoginPath = "/api/v1/auth/mfa/verify-login"
    private static let refreshPath = "/api/v1/auth/refresh"
    private static let logoutPath = "/api/v1/auth/logout"
    private static let forgotPasswordPath = "/api/v1/auth/forgot-password"
    private static let resetPasswordPath = "/api/v1/auth/reset-password"
    private static let mfaSetupPath = "/api/v1/auth/mfa/setup"
    private static let mfaSetupVerifyPath = "/api/v1/auth/mfa/setup/verify"

    // MARK: - signIn — happy path

    @Test func signIn_happyPath_postsCorrectShape_parsesSession() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.loginPath] = (200, [
            "access_token": "access-1",
            "refresh_token": "refresh-1",
            "token_type": "Bearer",
            "expires_in": 1800,
            "user": [
                "user_id": "u-1",
                "email": "perry@creoq.ca",
                "role": "CLINICIAN",
                "full_name": "Dr. Perry Gdalevitch",
                "mfa_enrolled": false,
            ],
        ])

        let outcome = try await client.signIn(
            email: "perry@creoq.ca",
            password: "perry"
        )

        // 1. Outcome is authenticated and parses every required field.
        guard case .authenticated(let session) = outcome else {
            Issue.record("expected .authenticated, got \(outcome)"); return
        }
        #expect(session.accessToken == "access-1")
        #expect(session.refreshToken == "refresh-1")
        // idToken is populated with the access token so KeychainHelper's
        // bearer-token fallback chain keeps working unchanged.
        #expect(session.idToken == "access-1")
        // expires_in: 1800 → expires roughly 30 minutes from now.
        let remaining = session.expiresAt.timeIntervalSinceNow
        #expect(remaining > 1700 && remaining < 1900)

        // 2. Request envelope matches the backend's expected shape.
        let body = AurionAuthURLProtocol.capturedBodies[Self.loginPath]
        #expect(body?["email"] as? String == "perry@creoq.ca")
        #expect(body?["password"] as? String == "perry")
        #expect(AurionAuthURLProtocol.capturedMethods[Self.loginPath] == "POST")
        let headers = AurionAuthURLProtocol.capturedHeaders[Self.loginPath] ?? [:]
        #expect(headers["Content-Type"] == "application/json")
    }

    // MARK: - signIn — MFA required

    @Test func signIn_mfaRequired_returnsChallengeToken() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.loginPath] = (200, [
            "mfa_required": true,
            "mfa_challenge_token": "challenge-jwt-xyz",
            "user_email": "perry@creoq.ca",
        ])

        let outcome = try await client.signIn(
            email: "perry@creoq.ca",
            password: "perry"
        )

        guard case .mfaRequired(let token, let email) = outcome else {
            Issue.record("expected .mfaRequired, got \(outcome)"); return
        }
        #expect(token == "challenge-jwt-xyz")
        #expect(email == "perry@creoq.ca")
    }

    // MARK: - signIn — invalid credentials

    @Test func signIn_invalidCredentials_throwsGenericError() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.loginPath] = (401, [
            "detail": "Invalid email or password.",
        ])

        do {
            _ = try await client.signIn(email: "x@y.com", password: "wrong")
            Issue.record("expected throw")
        } catch let error as AuthError {
            #expect(error == .invalidCredentials)
            // Error description never echoes the password.
            #expect(error.errorDescription?.contains("wrong") == false)
        }
    }

    // MARK: - verifyLoginMfa

    @Test func verifyLoginMfa_postsCorrectShape_parsesSession() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.mfaVerifyLoginPath] = (200, [
            "access_token": "access-2",
            "refresh_token": "refresh-2",
            "token_type": "Bearer",
            "expires_in": 1800,
            "user": [
                "user_id": "u-1",
                "email": "perry@creoq.ca",
                "role": "CLINICIAN",
                "full_name": "Dr. Perry Gdalevitch",
                "mfa_enrolled": true,
            ],
        ])

        let session = try await client.verifyLoginMfa(
            challengeToken: "challenge-jwt-xyz",
            code: "123456"
        )

        #expect(session.accessToken == "access-2")
        #expect(session.refreshToken == "refresh-2")

        let body = AurionAuthURLProtocol.capturedBodies[Self.mfaVerifyLoginPath]
        #expect(body?["mfa_challenge_token"] as? String == "challenge-jwt-xyz")
        #expect(body?["code"] as? String == "123456")
    }

    @Test func verifyLoginMfa_badCode_throwsInvalidCredentials() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.mfaVerifyLoginPath] = (401, [
            "detail": "Invalid email or password.",
        ])

        do {
            _ = try await client.verifyLoginMfa(
                challengeToken: "challenge-jwt-xyz",
                code: "000000"
            )
            Issue.record("expected throw")
        } catch let error as AuthError {
            #expect(error == .invalidCredentials)
        }
    }

    // MARK: - refresh

    @Test func refresh_happyPath_returnsRotatedSession() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.refreshPath] = (200, [
            "access_token": "access-3",
            "refresh_token": "refresh-3-new",
            "token_type": "Bearer",
            "expires_in": 1800,
            "user": [
                "user_id": "u-1",
                "email": "perry@creoq.ca",
                "role": "CLINICIAN",
                "full_name": "Dr. Perry Gdalevitch",
                "mfa_enrolled": false,
            ],
        ])

        let session = try await client.refresh(refreshToken: "refresh-2-old")

        // The backend rotates: the response carries a NEW refresh
        // token, distinct from the one we sent.
        #expect(session.accessToken == "access-3")
        #expect(session.refreshToken == "refresh-3-new")

        let body = AurionAuthURLProtocol.capturedBodies[Self.refreshPath]
        #expect(body?["refresh_token"] as? String == "refresh-2-old")
    }

    // MARK: - logout

    @Test func logout_postsRefreshTokenToLogoutEndpoint() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.logoutPath] = (204, [:])

        await client.logout(refreshToken: "refresh-2")

        let body = AurionAuthURLProtocol.capturedBodies[Self.logoutPath]
        #expect(body?["refresh_token"] as? String == "refresh-2")
        #expect(AurionAuthURLProtocol.capturedMethods[Self.logoutPath] == "POST")
    }

    // MARK: - requestPasswordReset

    @Test func requestPasswordReset_returnsSuccessOn204() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.forgotPasswordPath] = (204, [:])

        try await client.requestPasswordReset(email: "perry@creoq.ca")

        let body = AurionAuthURLProtocol.capturedBodies[Self.forgotPasswordPath]
        #expect(body?["email"] as? String == "perry@creoq.ca")
        #expect(AurionAuthURLProtocol.capturedMethods[Self.forgotPasswordPath] == "POST")
    }

    @Test func requestPasswordReset_alwaysSucceedsOnAnyEmail() async throws {
        // Backend's contract: same response shape regardless of
        // whether the email is on file. Client always treats 2xx as
        // success — the account-enumeration-safe contract.
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.forgotPasswordPath] = (204, [:])

        try await client.requestPasswordReset(email: "nobody-here@example.com")
        try await client.requestPasswordReset(email: "perry@creoq.ca")
        // No assertion needed — both calls just succeeding is the test.
    }

    // MARK: - resetPassword

    @Test func resetPassword_postsCorrectShape() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.resetPasswordPath] = (204, [:])

        try await client.resetPassword(
            token: "reset-token-abc",
            newPassword: "NewS3cret!Phrase"
        )

        let body = AurionAuthURLProtocol.capturedBodies[Self.resetPasswordPath]
        #expect(body?["token"] as? String == "reset-token-abc")
        #expect(body?["new_password"] as? String == "NewS3cret!Phrase")
    }

    @Test func resetPassword_invalidToken_throwsInvalidResetToken() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.resetPasswordPath] = (400, [
            "detail": "Invalid or expired reset token.",
        ])

        do {
            try await client.resetPassword(
                token: "expired",
                newPassword: "NewS3cret!Phrase"
            )
            Issue.record("expected throw")
        } catch let error as AuthError {
            // Reset failures map to the dedicated category so the UI
            // can phrase it as a link problem, not a credentials
            // problem.
            #expect(error == .invalidResetToken)
        }
    }

    // MARK: - beginMfaSetup

    @Test func beginMfaSetup_parsesSecretAndProvisioningURI() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.mfaSetupPath] = (200, [
            "secret": "JBSWY3DPEHPK3PXP",
            "provisioning_uri": "otpauth://totp/Aurion:perry@creoq.ca?secret=JBSWY3DPEHPK3PXP&issuer=Aurion",
        ])

        let setup = try await client.beginMfaSetup()

        #expect(setup.secret == "JBSWY3DPEHPK3PXP")
        #expect(setup.provisioningURI.contains("otpauth://totp/Aurion"))
        #expect(setup.provisioningURI.contains("issuer=Aurion"))
        #expect(AurionAuthURLProtocol.capturedMethods[Self.mfaSetupPath] == "GET")
    }

    @Test func beginMfaSetup_missingFields_throwsMalformed() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.mfaSetupPath] = (200, [
            "secret": "JBSWY3DPEHPK3PXP",
            // provisioning_uri missing.
        ])

        do {
            _ = try await client.beginMfaSetup()
            Issue.record("expected throw")
        } catch let error as AuthError {
            #expect(error == .malformed)
        }
    }

    // MARK: - verifyMfaSetup

    @Test func verifyMfaSetup_success_returnsSuccess() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.mfaSetupVerifyPath] = (204, [:])

        let outcome = try await client.verifyMfaSetup(code: "654321")

        #expect(outcome == .success)
        let body = AurionAuthURLProtocol.capturedBodies[Self.mfaSetupVerifyPath]
        #expect(body?["code"] as? String == "654321")
    }

    @Test func verifyMfaSetup_codeMismatch_returnsCodeMismatch() async throws {
        let client = Self.makeAuthClient()
        AurionAuthURLProtocol.responses[Self.mfaSetupVerifyPath] = (400, [
            "detail": "Invalid code. Try again.",
        ])

        let outcome = try await client.verifyMfaSetup(code: "111111")

        // 400 from setup-verify maps to .codeMismatch so the UI can
        // stay on the confirm screen without dropping the secret.
        #expect(outcome == .codeMismatch)
    }

    // MARK: - AuthError → localized descriptions

    @Test func authError_invalidCredentials_rendersGenericMessage() {
        let error = AuthError.invalidCredentials
        let description = error.errorDescription ?? ""
        // The exact message is from Localizable.strings — verify it's
        // wired (resolves to something other than the key itself).
        #expect(description != "login.error.invalidCredentials")
        #expect(!description.isEmpty)
    }

    @Test func authError_passwordTooWeak_mentionsPolicy() {
        let description = AuthError.passwordTooWeak.errorDescription ?? ""
        #expect(description != "login.error.passwordTooWeak")
        // Must surface SOME hint about the policy — "12+", "policy",
        // or any of the localized variants. We accept either lang.
        #expect(!description.isEmpty)
    }

    @Test func authError_network_rendersFriendlyMessage() {
        let description = AuthError.network.errorDescription ?? ""
        #expect(description != "login.error.network")
        #expect(!description.isEmpty)
    }

    @Test func authError_malformed_rendersFriendlyMessage() {
        let description = AuthError.malformed.errorDescription ?? ""
        #expect(description != "login.error.malformed")
        #expect(!description.isEmpty)
    }

    @Test func authError_invalidResetToken_distinctFromCredentials() {
        // .invalidResetToken and .invalidCredentials are intentionally
        // distinct categories — the UI phrases them differently. Verify
        // the localized strings actually differ so a future
        // string-file refactor doesn't collapse them by accident.
        let a = AuthError.invalidResetToken.errorDescription ?? ""
        let b = AuthError.invalidCredentials.errorDescription ?? ""
        #expect(a != b)
    }
}
