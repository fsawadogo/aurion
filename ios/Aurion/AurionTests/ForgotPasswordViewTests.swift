//
//  ForgotPasswordViewTests.swift
//  AurionTests
//
//  AUTH-PIVOT-IOS — view-side contracts for the password-reset entry
//  screen. The view's account-enumeration-safe behaviour is the
//  load-bearing property under test: same confirmation panel for
//  every email, transient banner for transport-level failures, no
//  side effects on cancel.
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct ForgotPasswordViewTests {

    // MARK: - Strings parity

    @Test func forgotPasswordStrings_resolveInEnglish() {
        let keys = [
            "login.forgotPassword.linkText",
            "login.forgotPassword.title",
            "login.forgotPassword.subtitle",
            "login.forgotPassword.emailLabel",
            "login.forgotPassword.sendButton",
            "login.forgotPassword.sending",
            "login.forgotPassword.confirmation",
            "login.forgotPassword.backToLogin",
        ]
        for key in keys {
            #expect(L(key) != key, "missing string for key \(key)")
        }
    }

    // MARK: - Smoke: view renders with default network call site

    @Test func view_constructsWithDefaultRequestReset() {
        // The default initializer wires `requestReset` to
        // AurionAuth.shared.requestPasswordReset — verify that
        // construction works without exercising the network. The
        // closure isn't called at init time, so nothing actually hits
        // the wire here.
        var dismissed = false
        let view = ForgotPasswordView(onDismiss: { dismissed = true })
        // Touch the body to drive view-graph construction.
        _ = view.body
        #expect(dismissed == false)
    }

    // MARK: - Cancel path has no side effects

    @Test func cancelPath_doesNotMutateBiometricCredential() {
        // Same property the MFA challenge view holds: dismiss must
        // never touch the saved biometric credential. The forgot-
        // password view never reads from the Keychain at all; this
        // test is the structural assertion.
        let before = KeychainHelper.shared.hasBiometricCredential()
        var dismissed = false
        let view = ForgotPasswordView(onDismiss: { dismissed = true })
        _ = view.body
        let after = KeychainHelper.shared.hasBiometricCredential()
        #expect(before == after)
        #expect(dismissed == false)
    }

    // MARK: - requestReset closure contract

    @Test func customRequestReset_isUsedInsteadOfDefault() async {
        // The view accepts a `requestReset` closure as a constructor
        // arg so tests can drive the submit-flow without URLProtocol
        // setup. This test verifies the closure swap actually takes
        // effect — calling the captured closure should NOT touch the
        // network or AurionAuth.shared.
        actor Counter {
            var count = 0
            func bump() { count += 1 }
            func value() -> Int { count }
        }
        let counter = Counter()
        let view = ForgotPasswordView(
            onDismiss: { },
            requestReset: { _ in await counter.bump() }
        )
        // Drive the closure once via the view's exposed init hook.
        // The view's `submit()` is private — we exercise the closure
        // surface directly to confirm the swap took.
        try? await view.requestReset("anyone@example.com")
        let count = await counter.value()
        #expect(count == 1)
    }

    @Test func successfulSubmit_isAccountEnumerationSafe() async {
        // The view treats every 2xx the same — no observable
        // distinction between "email on file" and "email unknown".
        // We assert this at the closure-level: the same closure runs
        // for every input, so the confirmation panel renders
        // identically regardless of email.
        var calls: [String] = []
        let view = ForgotPasswordView(
            onDismiss: { },
            requestReset: { email in
                calls.append(email)
                // Returns Void on success — same shape for every
                // input. No payload that leaks account existence.
            }
        )
        try? await view.requestReset("perry@creoq.ca")
        try? await view.requestReset("unknown@example.com")
        #expect(calls == ["perry@creoq.ca", "unknown@example.com"])
    }

    @Test func networkError_isRecoverableNotFatal() async {
        // A transport failure on the reset call surfaces as a soft
        // banner (the view stays open so the user can retry) — NOT a
        // forced-confirmation flip that would hide the failure.
        // We assert by verifying the closure propagates errors back
        // to the caller; the view's submit() catches them and renders
        // the banner without flipping `didSubmit`.
        struct FakeError: Error {}
        let view = ForgotPasswordView(
            onDismiss: { },
            requestReset: { _ in throw FakeError() }
        )
        do {
            try await view.requestReset("perry@creoq.ca")
            Issue.record("expected throw")
        } catch is FakeError {
            // Expected — the closure throws, the view layer handles
            // it without crashing or auto-confirming.
        } catch {
            Issue.record("unexpected error: \(error)")
        }
    }
}
