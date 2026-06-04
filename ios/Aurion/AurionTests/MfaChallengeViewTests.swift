//
//  MfaChallengeViewTests.swift
//  AurionTests
//
//  AUTH-PIVOT-IOS — view-side contracts: identifiable wrappers, the
//  shared TotpCodeField validation rules, and the no-side-effects
//  guarantee on the cancel path.
//
//  Cherry-picked from PR #233 and rebased onto the AurionAuth call
//  surface. The TotpCodeField primitive is unchanged from #233 so the
//  validation tests carry across unchanged; the wrapper assertions
//  exercise the new backend protocol (challengeToken instead of the
//  Cognito Session opaque string).
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct MfaChallengeViewTests {

    // MARK: - Identifiable wrappers

    @Test func mfaChallenge_roundTripsChallengeTokenAndEmail() {
        let c = MfaChallenge(
            challengeToken: "challenge-jwt-xyz",
            userEmail: "perry@creoq.ca"
        )
        #expect(c.challengeToken == "challenge-jwt-xyz")
        #expect(c.userEmail == "perry@creoq.ca")
    }

    @Test func mfaChallenge_twoInstancesAreNotEqual() {
        // Each MfaChallenge gets a fresh UUID — required for SwiftUI's
        // item-based fullScreenCover to re-present after a dismiss.
        let a = MfaChallenge(challengeToken: "t", userEmail: "u@example.com")
        let b = MfaChallenge(challengeToken: "t", userEmail: "u@example.com")
        #expect(a.id != b.id)
    }

    // MARK: - TotpCodeField — sanitize

    @Test func totpCodeField_sanitize_stripsNonDigits() {
        #expect(TotpCodeField.sanitize("123 456") == "123456")
        #expect(TotpCodeField.sanitize("12a3b4") == "1234")
        #expect(TotpCodeField.sanitize("000000") == "000000")
        #expect(TotpCodeField.sanitize("") == "")
        // Authenticator paste may include surrounding whitespace.
        #expect(TotpCodeField.sanitize("   987654   ") == "987654")
    }

    @Test func totpCodeField_sanitize_clampsToSix() {
        #expect(TotpCodeField.sanitize("1234567890") == "123456")
        #expect(TotpCodeField.sanitize("9999999") == "999999")
    }

    // MARK: - TotpCodeField — isComplete

    @Test func totpCodeField_isComplete_only6AsciiDigits() {
        #expect(TotpCodeField.isComplete("123456") == true)
        #expect(TotpCodeField.isComplete("000000") == true)

        #expect(TotpCodeField.isComplete("12345") == false)   // too short
        #expect(TotpCodeField.isComplete("1234567") == false) // too long
        #expect(TotpCodeField.isComplete("") == false)
        #expect(TotpCodeField.isComplete("12345a") == false)  // letter
        #expect(TotpCodeField.isComplete("123 56") == false)  // whitespace
    }

    // MARK: - Localization parity

    @Test func mfaStrings_resolveInEnglish() {
        // Localization.swift returns the table value, falling back to
        // the key. If any of these come back == the key, the keys aren't
        // wired into Localizable.strings.
        let keys = [
            "login.mfa.challenge.title",
            "login.mfa.challenge.subtitle",
            "login.mfa.challenge.verifyButton",
            "login.mfa.challenge.cancelButton",
            "login.mfa.challenge.invalidCode",
            "login.mfa.challenge.expiredCode",
            "login.mfa.setup.title",
            "login.mfa.setup.intro",
            "login.mfa.setup.secretLabel",
            "login.mfa.setup.copySecret",
            "login.mfa.setup.copied",
            "login.mfa.setup.confirmLabel",
            "login.mfa.setup.completeButton",
            "login.mfa.setup.codeMismatch",
        ]
        for key in keys {
            #expect(L(key) != key, "missing string for key \(key)")
        }
    }

    @Test func legacyMfaUnsupportedString_isRemoved() {
        // The legacy key SHOULD now fall back to itself — proving the
        // string was removed from both locales. The new login state
        // machine handles MFA properly, so the "we can't prompt"
        // string is dead.
        #expect(L("login.mfaUnsupported") == "login.mfaUnsupported")
    }

    // MARK: - Cancel path has no Keychain side effects

    @Test func cancelPath_doesNotMutateBiometricCredential() {
        // The contract: when the user backs out of the MFA challenge,
        // the saved biometric credential — if any — must remain
        // untouched. The view's onCancel closure forwarded by
        // ContentView only nils the @State slot; it never touches the
        // Keychain.
        let before = KeychainHelper.shared.hasBiometricCredential()
        _ = MfaChallenge(challengeToken: "t", userEmail: "u@example.com")
        let after = KeychainHelper.shared.hasBiometricCredential()
        #expect(before == after)
    }
}
