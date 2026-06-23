import SwiftUI
import Foundation
import Combine

/// Global app state — manages auth, session, and onboarding status.
///
/// `isOnboardingComplete` and `hasCompletedProfileSetup` are scoped per
/// user id so a brand-new account always lands in onboarding, even on a
/// device where another user has already finished it.
@MainActor
final class AppState: ObservableObject {
    private static let defaults = UserDefaults.standard

    /// User id of the currently-active session. Used to namespace per-user
    /// UserDefaults keys (onboarding, profile setup). nil when signed out.
    private var currentUserId: String?

    @Published var isAuthenticated: Bool {
        didSet { Self.defaults.set(isAuthenticated, forKey: Keys.auth) }
    }
    @Published var isOnboardingComplete: Bool {
        didSet { writeUserFlag(Keys.onboarding, value: isOnboardingComplete) }
    }
    @Published var hasCompletedProfileSetup: Bool {
        didSet { writeUserFlag(Keys.profile, value: hasCompletedProfileSetup) }
    }
    /// Whether the first-run coach-mark tour has been dismissed with "Don't
    /// show again". Per-user, same as the other first-run flags.
    @Published var hasSeenTour: Bool {
        didSet { writeUserFlag(Keys.tour, value: hasSeenTour) }
    }
    @Published var appLanguage: String {
        didSet {
            Self.defaults.set(appLanguage, forKey: Keys.language)
            Localization.setLanguage(appLanguage)
        }
    }
    /// User-chosen appearance: "system" (follow device), "light", or "dark".
    /// App-level (not per-user), like ``appLanguage``.
    @Published var appearance: String {
        didSet { Self.defaults.set(appearance, forKey: Keys.appearance) }
    }
    /// #418 — physician accent color (one of `AurionAccent`'s raw values).
    /// Persisted to the key the Theme tokens read (`AurionAccent.current`),
    /// so a change recolors the gold-token surfaces on the next render.
    /// Synced from the backend profile on load + PUT back on change, so it
    /// matches the portal cross-device.
    @Published var accentColor: String {
        didSet { Self.defaults.set(accentColor, forKey: Keys.accent) }
    }

    /// The override to hand `.preferredColorScheme`. `nil` = follow the
    /// system; otherwise force light/dark.
    var colorSchemeOverride: ColorScheme? {
        switch appearance {
        case "light": return .light
        case "dark":  return .dark
        default:      return nil
        }
    }
    @Published var hasVoiceProfile = false
    @Published var currentSession: CaptureSession?
    @Published var userRole: UserRole = .clinician
    @Published var physicianProfile: PhysicianProfileResponse?

    init() {
        // Auth is the AND of UserDefaults flag + Keychain token presence.
        // If the token is missing (e.g. cleared by system tools), treat as
        // signed out even when the UserDefaults flag is stale.
        let hasToken = KeychainHelper.shared.hasAuthToken()
        let auth = Self.defaults.bool(forKey: Keys.auth) && hasToken
        let userId = KeychainHelper.shared.loadUserId()
        // One-time migration: legacy global flags belonged to whoever was
        // signed in when this code shipped. Attribute them to that user
        // (read from Keychain) and delete the global keys so brand-new
        // accounts don't inherit them.
        if let userId, !userId.isEmpty {
            Self.migrateLegacyFlag(Keys.onboarding, userId: userId)
            Self.migrateLegacyFlag(Keys.profile, userId: userId)
        }
        let onboarding = Self.readUserFlag(Keys.onboarding, userId: userId)
        let profile = Self.readUserFlag(Keys.profile, userId: userId)
        let tour = Self.readUserFlag(Keys.tour, userId: userId)
        let lang = Self.defaults.string(forKey: Keys.language) ?? "en"
        _isAuthenticated = Published(initialValue: auth)
        _isOnboardingComplete = Published(initialValue: onboarding)
        _hasCompletedProfileSetup = Published(initialValue: profile)
        _hasSeenTour = Published(initialValue: tour)
        _appLanguage = Published(initialValue: lang)
        _appearance = Published(initialValue: Self.defaults.string(forKey: Keys.appearance) ?? "system")
        _accentColor = Published(initialValue: Self.defaults.string(forKey: Keys.accent) ?? "gold")
        currentUserId = userId
        Localization.setLanguage(lang)
        if let role = KeychainHelper.shared.loadUserRole(),
           let parsed = UserRole(rawValue: role) {
            userRole = parsed
        }
    }

    /// Bind app state to a freshly-authenticated user. Loads that user's
    /// per-user flags from UserDefaults (false on first login, which is
    /// what triggers the onboarding flow).
    func applyAuth(userId: String, role: UserRole) {
        currentUserId = userId
        userRole = role
        // Persist the legacy auth slot (token-presence marker + userId + role)
        // that `init()` reads on relaunch. The login path only writes the
        // `cognito.*` token slots via `AurionAuth.persistTokens`, so without
        // this `hasAuthToken()`/`loadUserId()`/`loadUserRole()` are all empty
        // on the next cold launch and a logged-in clinician is bounced to
        // LoginView despite a valid refresh token. The stored token is only a
        // presence marker — `bearerToken()` prefers the live cognito ID token —
        // so it stays correct even after a refresh rotates the live token.
        KeychainHelper.shared.saveAuthToken(
            KeychainHelper.shared.bearerToken() ?? "session",
            userId: userId,
            role: role.rawValue,
            name: KeychainHelper.shared.loadUserName() ?? ""
        )
        isOnboardingComplete = Self.readUserFlag(Keys.onboarding, userId: userId)
        hasCompletedProfileSetup = Self.readUserFlag(Keys.profile, userId: userId)
        hasSeenTour = Self.readUserFlag(Keys.tour, userId: userId)
        isAuthenticated = true
    }

    /// Clears the in-memory user binding. Per-user UserDefaults flags
    /// stay on disk so the same user keeps their onboarding state if they
    /// sign back in later.
    func clearAuth() {
        isAuthenticated = false
        currentUserId = nil
        physicianProfile = nil
    }

    func checkVoiceEnrollment() {
        hasVoiceProfile = KeychainHelper.shared.hasVoiceEmbedding()
    }

    // MARK: - Per-user flag storage

    private func writeUserFlag(_ base: String, value: Bool) {
        Self.defaults.set(value, forKey: Self.userKey(base, userId: currentUserId))
    }

    private static func readUserFlag(_ base: String, userId: String?) -> Bool {
        defaults.bool(forKey: userKey(base, userId: userId))
    }

    private static func userKey(_ base: String, userId: String?) -> String {
        guard let userId, !userId.isEmpty else { return base }
        return "\(base).\(userId)"
    }

    private static func migrateLegacyFlag(_ base: String, userId: String) {
        let perUserKey = userKey(base, userId: userId)
        guard defaults.object(forKey: perUserKey) == nil else { return }
        if defaults.bool(forKey: base) {
            defaults.set(true, forKey: perUserKey)
        }
        defaults.removeObject(forKey: base)
    }

    private enum Keys {
        static let auth = "aurion.is_authenticated"
        static let onboarding = "aurion.onboarding_complete"
        static let profile = "aurion.profile_setup_complete"
        static let tour = "aurion.tour_seen"
        static let language = "aurion.app_language"
        static let appearance = "aurion.appearance"
        // Shared with the Theme tokens, which read this key via
        // `AurionAccent.current` — keep them pointed at the same string.
        static let accent = AurionAccent.defaultsKey
    }
}

enum UserRole: String, Codable {
    case clinician = "CLINICIAN"
    case evalTeam = "EVAL_TEAM"
    case complianceOfficer = "COMPLIANCE_OFFICER"
    case admin = "ADMIN"
}
