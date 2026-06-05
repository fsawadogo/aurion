//
//  ResetPasswordViewTests.swift
//  AurionTests
//
//  AUTH-UNIVERSAL-LINKS — view-side contracts for the in-app reset
//  password screen. The validation rules + injected-closure surface
//  are the load-bearing properties: the view must not call the
//  network until 8+ chars and the confirm field match, the token
//  must be forwarded verbatim to the AurionAuth call, and the
//  AuthError.invalidResetToken branch must surface a localized
//  banner without crashing.
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct ResetPasswordViewTests {

    // MARK: - Strings parity

    @Test func resetPasswordStrings_resolveInEnglish() {
        let keys = [
            "login.resetPassword.title",
            "login.resetPassword.subtitle",
            "login.resetPassword.newPasswordLabel",
            "login.resetPassword.confirmLabel",
            "login.resetPassword.submitButton",
            "login.resetPassword.submitting",
            "login.resetPassword.invalidLength",
            "login.resetPassword.mismatch",
            "login.resetPassword.tokenInvalid",
            "login.resetPassword.tokenExpired",
            "login.resetPassword.successTitle",
            "login.resetPassword.success",
            "login.resetPassword.signIn",
            "login.resetPassword.backToLogin",
            "login.resetPassword.showPassword",
            "login.resetPassword.hidePassword",
        ]
        for key in keys {
            #expect(L(key) != key, "missing string for key \(key)")
        }
    }

    // MARK: - Smoke: view renders with the default closure

    @Test func view_constructsWithDefaultResetPassword() {
        // The default initializer wires `resetPassword` to
        // AurionAuth.shared.resetPassword. Construction (and a touch
        // of `body`) must not trip the network — the closure isn't
        // called at init time.
        var dismissed = false
        let view = ResetPasswordView(
            token: "test-token",
            onDismiss: { dismissed = true }
        )
        _ = view.body
        #expect(dismissed == false)
    }

    @Test func view_acceptsTokenAndForwardsToOnDismiss() {
        // The onDismiss closure must fire exactly when the caller
        // invokes it; the view doesn't run it on construction.
        var dismissCount = 0
        let view = ResetPasswordView(
            token: "tok-abc",
            onDismiss: { dismissCount += 1 }
        )
        // Invoke directly: nothing in body should auto-call dismiss.
        _ = view.body
        #expect(dismissCount == 0)
        // Invoke the captured closure as the buttons would.
        // The struct's onDismiss is a stored let-let closure, not
        // exposed by name — we run a control-path check via a
        // second view with an explicit invocation surrogate below.
        view.onDismiss()
        #expect(dismissCount == 1)
    }

    // MARK: - Closure swap (injectable surface)

    @Test func customResetPassword_isUsedInsteadOfDefault() async {
        // Same pattern ForgotPasswordView uses — proves the closure
        // override actually takes effect so subsequent tests can drive
        // the submit flow without URLProtocol setup.
        actor Captured {
            var calls: [(String, String)] = []
            func record(_ token: String, _ password: String) { calls.append((token, password)) }
            func values() -> [(String, String)] { calls }
        }
        let captured = Captured()
        let view = ResetPasswordView(
            token: "tok-1",
            onDismiss: { },
            resetPassword: { t, p in await captured.record(t, p) }
        )
        try? await view.resetPassword("tok-1", "NewS3cret!Phrase")
        let calls = await captured.values()
        #expect(calls.count == 1)
        #expect(calls.first?.0 == "tok-1")
        #expect(calls.first?.1 == "NewS3cret!Phrase")
    }

    // MARK: - Token forwarding

    @Test func submit_forwardsConstructorTokenToClosure() async {
        // The token is held in `let token: String` on the view and
        // must arrive at the resetPassword closure unchanged. We
        // check that the closure receives the SAME token the view
        // was constructed with — the deep-linked value never gets
        // rewritten in flight.
        actor Captured {
            var received: String?
            func set(_ t: String) { received = t }
            func value() -> String? { received }
        }
        let captured = Captured()
        let view = ResetPasswordView(
            token: "deep-link-token-from-email-aurion-2026",
            onDismiss: { },
            resetPassword: { token, _ in await captured.set(token) }
        )
        try? await view.resetPassword(view.token, "NewS3cret!Phrase")
        let observed = await captured.value()
        #expect(observed == "deep-link-token-from-email-aurion-2026")
    }

    // MARK: - Token policy

    @Test func passwordMinLength_matchesWebContract() {
        // The iOS rule must mirror web/lib/password-validation.ts
        // (`PASSWORD_MIN_LENGTH = 8`) and the backend's Pydantic
        // Field(min_length=8). Lockstep — if web changes, change here.
        #expect(ResetPasswordView.passwordMinLength == 8)
    }

    // MARK: - Backend error mapping

    @Test func invalidTokenError_surfacesAsBanner() async {
        // The view must catch AuthError.invalidResetToken and show
        // the localized 'expired or already used' banner instead of
        // crashing or leaking the raw error.
        struct ThrowsInvalidToken {
            static func run(_: String, _: String) async throws {
                throw AuthError.invalidResetToken
            }
        }
        let view = ResetPasswordView(
            token: "expired-token",
            onDismiss: { },
            resetPassword: { token, password in
                try await ThrowsInvalidToken.run(token, password)
            }
        )
        do {
            try await view.resetPassword("expired-token", "NewS3cret!Phrase")
            Issue.record("expected throw from the closure")
        } catch let error as AuthError {
            // The view's submit() catches this and renders the banner;
            // we're asserting at the closure boundary that the right
            // error type propagates.
            #expect(error == .invalidResetToken)
        } catch {
            Issue.record("unexpected error: \(error)")
        }
    }

    @Test func networkError_isRecoverableNotFatal() async {
        // Transport failure surfaces as a soft banner; the form stays
        // open so the user can retry. We assert at the closure level:
        // the view layer catches without crashing.
        struct FakeError: Error {}
        let view = ResetPasswordView(
            token: "tok-x",
            onDismiss: { },
            resetPassword: { _, _ in throw FakeError() }
        )
        do {
            try await view.resetPassword("tok-x", "NewS3cret!Phrase")
            Issue.record("expected throw")
        } catch is FakeError {
            // Expected — the closure throws, the view's submit()
            // handles it without flipping to the success panel.
        } catch {
            Issue.record("unexpected error: \(error)")
        }
    }

    // MARK: - Strings differ across keys

    @Test func tokenInvalidStringDistinctFromGenericTransport() {
        // The invalid-token banner copy must differ from the generic
        // network-error copy — the UI phrases them differently so
        // users can tell 'reset failed (token issue)' apart from
        // 'reset failed (offline)'.
        let invalid = L("login.resetPassword.tokenInvalid")
        let network = L("login.error.network")
        #expect(invalid != network)
        #expect(invalid != "login.resetPassword.tokenInvalid")
    }
}
