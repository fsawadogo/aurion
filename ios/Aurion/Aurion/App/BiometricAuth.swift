@preconcurrency import LocalAuthentication

/// Thin wrapper over `LocalAuthentication` for describing the device's
/// authentication capability. The actual auth prompt is triggered implicitly
/// by reading the biometric-protected Keychain item (see
/// ``KeychainHelper.loadBiometricRefreshToken``), so this type only answers
/// "can we?" and "what's it called?" for the UI.
enum BiometricAuth {
    enum Kind { case faceID, touchID, opticID, passcode }

    /// True when the device can authenticate the user by biometry **or**
    /// device passcode — the same policy the saved-credential Keychain item
    /// is protected with (`.userPresence`). If this is false, the
    /// "remember me" affordances are hidden.
    static var isAvailable: Bool {
        LAContext().canEvaluatePolicy(.deviceOwnerAuthentication, error: nil)
    }

    /// The strongest enrolled factor, used only to label the UI. Falls back
    /// to `.passcode` when no biometry is enrolled (the user can still save a
    /// login — `.userPresence` accepts the passcode).
    static var kind: Kind {
        let context = LAContext()
        _ = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
        switch context.biometryType {
        case .faceID:  return .faceID
        case .touchID: return .touchID
        case .opticID: return .opticID
        default:       return .passcode
        }
    }

    /// Display name. Apple product names (Face ID / Touch ID / Optic ID) are
    /// brand-fixed in every locale; only "Passcode" is localized.
    static var typeLabel: String {
        switch kind {
        case .faceID:   return "Face ID"
        case .touchID:  return "Touch ID"
        case .opticID:  return "Optic ID"
        case .passcode: return L("biometric.passcode")
        }
    }

    static var iconName: String {
        switch kind {
        case .faceID:   return "faceid"
        case .touchID:  return "touchid"
        case .opticID:  return "opticid"
        case .passcode: return "lock.fill"
        }
    }

    /// Prompt the user (Face ID / Touch ID / passcode) and, on success, return
    /// the authenticated `LAContext`. Uses the callback-based `evaluatePolicy`
    /// so the UI never blocks during the prompt; the returned context can be
    /// handed straight to a Keychain read (`kSecUseAuthenticationContext`) to
    /// unlock the saved item without a second prompt. Returns nil on cancel or
    /// failure.
    static func authenticate(reason: String) async -> LAContext? {
        let context = LAContext()
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: nil) else {
            return nil
        }
        return await withCheckedContinuation { continuation in
            context.evaluatePolicy(
                .deviceOwnerAuthentication,
                localizedReason: reason
            ) { success, _ in
                continuation.resume(returning: success ? context : nil)
            }
        }
    }
}
