//
//  AurionAuthResetPasswordTests.swift
//  AurionTests
//
//  AUTH-UNIVERSAL-LINKS — focused coverage of
//  ``AurionAuth/resetPassword(token:newPassword:)`` matching the
//  CLAUDE.md test plan for the Universal Links work:
//
//  - 204 → completes silently
//  - 400 with backend detail → throws .invalidResetToken
//  - 400 with malformed body → still throws .invalidResetToken
//  - Network error (no response) → throws .network
//
//  The happy + standard-400 cases also live in AurionAuthTests.swift
//  (PR #235); this file extends with the malformed-body + transport-
//  error branches the Universal Links work specifically asks for.
//

import Foundation
import Testing
@testable import Aurion

/// Separate URLProtocol class so this suite doesn't share state with
/// AurionAuthTests' ``AurionAuthURLProtocol`` — each suite owns its
/// own dispatch table.
final class ResetPasswordURLProtocol: URLProtocol {
    nonisolated(unsafe) static var responses: [String: (Int, [String: Any]?, Bool)] = [:]
    /// (path, statusCode, jsonOrNil, transportFails)
    /// transportFails=true → simulate a network failure (no response).
    nonisolated(unsafe) static var capturedBodies: [String: [String: Any]] = [:]

    static func reset() {
        responses = [:]
        capturedBodies = [:]
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        let path = request.url?.path ?? ""

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

        let (status, json, fails) = Self.responses[path] ?? (500, nil, false)

        if fails {
            // Simulate a transport-level failure (offline / DNS / TLS).
            let error = NSError(
                domain: NSURLErrorDomain,
                code: NSURLErrorNotConnectedToInternet,
                userInfo: nil
            )
            client?.urlProtocol(self, didFailWithError: error)
            return
        }

        let data: Data
        if let json {
            data = (try? JSONSerialization.data(withJSONObject: json)) ?? Data()
        } else {
            // Malformed-body branch: serve garbage that won't decode
            // as JSON. The auth client must still classify the 4xx
            // by status code alone.
            data = Data("<<not json>>".utf8)
        }
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

@MainActor
@Suite(.serialized)
struct AurionAuthResetPasswordTests {

    private static let resetPasswordPath = "/api/v1/auth/reset-password"

    private static func makeAuthClient() -> AurionAuth {
        ResetPasswordURLProtocol.reset()
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [ResetPasswordURLProtocol.self]
        return AurionAuth(urlSession: URLSession(configuration: config))
    }

    // MARK: - 204 → silent success

    @Test func resetPassword_204_completesSilently() async throws {
        let client = Self.makeAuthClient()
        ResetPasswordURLProtocol.responses[Self.resetPasswordPath] =
            (204, [:], false)

        // No throw = success contract. Body fields delivered verbatim.
        try await client.resetPassword(
            token: "single-use-token-abc",
            newPassword: "NewS3cret!Phrase"
        )

        let body = ResetPasswordURLProtocol.capturedBodies[Self.resetPasswordPath]
        #expect(body?["token"] as? String == "single-use-token-abc")
        #expect(body?["new_password"] as? String == "NewS3cret!Phrase")
    }

    // MARK: - 400 with structured detail → invalidResetToken

    @Test func resetPassword_400_withBackendDetail_throwsInvalidResetToken() async {
        let client = Self.makeAuthClient()
        ResetPasswordURLProtocol.responses[Self.resetPasswordPath] = (
            400,
            ["detail": "Reset token has expired."],
            false
        )

        do {
            try await client.resetPassword(
                token: "expired",
                newPassword: "NewS3cret!Phrase"
            )
            Issue.record("expected throw")
        } catch let error as AuthError {
            // Reset-token failures get their own category so the UI
            // can phrase it as a link problem, not a credentials
            // problem. The verbatim 'expired' detail is intentionally
            // NOT plumbed through — the localized banner is the
            // user-facing surface.
            #expect(error == .invalidResetToken)
        } catch {
            Issue.record("unexpected error: \(error)")
        }
    }

    // MARK: - 400 with malformed body → still invalidResetToken

    @Test func resetPassword_400_withMalformedBody_throwsInvalidResetToken() async {
        // Backends sometimes return malformed bodies on 4xx during
        // an outage (e.g. an upstream HTML error page through a
        // mis-routed proxy). The status code is the source of truth;
        // a malformed body must NOT cause a different error class.
        let client = Self.makeAuthClient()
        ResetPasswordURLProtocol.responses[Self.resetPasswordPath] =
            (400, nil, false)

        do {
            try await client.resetPassword(
                token: "any",
                newPassword: "NewS3cret!Phrase"
            )
            Issue.record("expected throw")
        } catch let error as AuthError {
            #expect(error == .invalidResetToken)
        } catch {
            Issue.record("unexpected error: \(error)")
        }
    }

    // MARK: - Network failure → .network

    @Test func resetPassword_transportFailure_throwsNetwork() async {
        let client = Self.makeAuthClient()
        ResetPasswordURLProtocol.responses[Self.resetPasswordPath] =
            (0, nil, true) // transportFails=true

        do {
            try await client.resetPassword(
                token: "any",
                newPassword: "NewS3cret!Phrase"
            )
            Issue.record("expected throw")
        } catch let error as AuthError {
            // The transport-level branch maps to .network — the UI
            // surfaces 'Couldn't reach Aurion. Check your connection'
            // instead of the misleading 'link expired' copy.
            #expect(error == .network)
        } catch {
            Issue.record("unexpected error: \(error)")
        }
    }

    // MARK: - Request envelope

    @Test func resetPassword_postsToCorrectEndpointWithJSON() async throws {
        let client = Self.makeAuthClient()
        ResetPasswordURLProtocol.responses[Self.resetPasswordPath] =
            (204, [:], false)

        try await client.resetPassword(
            token: "tok",
            newPassword: "AnotherS3cret!Phrase"
        )

        // The body MUST carry both fields under the wire-spec keys.
        // Backend's Pydantic model expects 'token' + 'new_password'
        // (snake_case for the Python side; iOS surface mirrors).
        let body = ResetPasswordURLProtocol.capturedBodies[Self.resetPasswordPath]
        #expect(body?.count == 2)
        #expect(body?["token"] as? String == "tok")
        #expect(body?["new_password"] as? String == "AnotherS3cret!Phrase")
    }
}
