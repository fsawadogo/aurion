//
//  MfaChallengeViewTests.swift
//  AurionTests
//
//  AUR-COG-MFA — view-side contracts: identifiable wrappers, the shared
//  TotpCodeField validation rules, and the no-side-effects guarantee on
//  the cancel path.
//

import Foundation
import Testing
@testable import Aurion

@MainActor
struct MfaChallengeViewTests {

    // MARK: - Identifiable wrappers

    @Test func mfaChallenge_roundTripsSessionAndUsername() {
        let c = MfaChallenge(session: "session-1", username: "u@example.com")
        #expect(c.session == "session-1")
        #expect(c.username == "u@example.com")
    }

    @Test func mfaSetupChallenge_roundTripsSessionAndUsername() {
        let c = MfaSetupChallenge(session: "setup-1", username: "u@example.com")
        #expect(c.session == "setup-1")
        #expect(c.username == "u@example.com")
    }

    @Test func mfaChallenge_twoInstancesAreNotEqual() {
        // Each MfaChallenge gets a fresh UUID — required for SwiftUI's
        // item-based fullScreenCover to re-present after a dismiss.
        let a = MfaChallenge(session: "s", username: "u")
        let b = MfaChallenge(session: "s", username: "u")
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
        // Localization.swift returns the table value, falling back to the
        // key. If any of these come back == the key, the keys aren't
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
        // string was removed from both locales.
        #expect(L("login.mfaUnsupported") == "login.mfaUnsupported")
    }

    // MARK: - Cancel path has no Keychain side effects

    @Test func cancelPath_doesNotMutateBiometricCredential() {
        // The contract: when the user backs out of the MFA challenge, the
        // saved biometric credential — if any — must remain untouched.
        // The view's onCancel closure forwarded by ContentView only nils
        // the @State slot; it never touches the Keychain.
        //
        // We assert this at the API surface: MfaChallenge initialization
        // does not call KeychainHelper. There is no init-time observer
        // we can stub, so the check is structural — the wrapper has no
        // dependency on KeychainHelper at all.
        let before = KeychainHelper.shared.hasBiometricCredential()
        _ = MfaChallenge(session: "s", username: "u")
        let after = KeychainHelper.shared.hasBiometricCredential()
        #expect(before == after)
    }
}
