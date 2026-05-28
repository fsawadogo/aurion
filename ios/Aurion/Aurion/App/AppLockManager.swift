import Combine
import LocalAuthentication
import SwiftUI

/// On-device app lock for the clinical PHI surface.
///
/// When enabled, Aurion requires Face ID / Touch ID (with passcode fallback)
/// to open — on cold launch and when returning to the foreground after the
/// configured idle window. This protects patient data if the phone is
/// unlocked and left unattended (a real clinic risk: phone in a coat pocket,
/// shared workstation).
///
/// The idle timer is keyed on *time spent backgrounded*, so it never fires
/// during active foreground use — an in-progress recording (app foreground
/// for the whole encounter) is never interrupted.
///
/// Auth uses `.deviceOwnerAuthentication` (biometry **or** device passcode),
/// so a failed/absent biometric falls back to the passcode rather than
/// locking the clinician out. If the device has no passcode set at all, we
/// fail open (unlock) rather than make the app unusable.
@MainActor
final class AppLockManager: ObservableObject {

    /// True while the lock screen should cover the app.
    @Published private(set) var isLocked: Bool

    /// Whether app lock is on. Persisted; toggling off clears any active lock.
    @Published var isEnabled: Bool {
        didSet {
            defaults.set(isEnabled, forKey: Keys.enabled)
            // Toggling off clears any active lock. Toggling on never locks
            // the user out mid-use — the next background/cold-launch arms it.
            if !isEnabled { isLocked = false }
        }
    }

    /// Seconds the app may be backgrounded before a re-auth is required.
    /// 0 = lock immediately on any background.
    @Published var idleTimeoutSeconds: Int {
        didSet { defaults.set(idleTimeoutSeconds, forKey: Keys.timeout) }
    }

    @Published private(set) var isAuthenticating = false

    /// Discrete auto-lock choices surfaced in Settings.
    static let timeoutOptions = [0, 60, 300, 900]

    private let defaults = UserDefaults.standard
    private enum Keys {
        static let enabled = "aurion.applock.enabled"
        static let timeout = "aurion.applock.timeout"
    }
    private var backgroundedAt: Date?

    init() {
        let enabled = defaults.bool(forKey: Keys.enabled)
        isEnabled = enabled
        idleTimeoutSeconds = (defaults.object(forKey: Keys.timeout) as? Int) ?? 300
        // Cold launch: locked iff the feature is on.
        isLocked = enabled
    }

    /// Drive lock state from the app's scene phase. Called by `AurionApp`.
    func handleScenePhase(_ phase: ScenePhase) {
        switch phase {
        case .background:
            // Start the idle clock the moment we truly leave the foreground.
            // (We ignore `.inactive` — app-switcher/Control-Center transitions
            // shouldn't start the timer.)
            if backgroundedAt == nil { backgroundedAt = Date() }
        case .active:
            if isEnabled, let since = backgroundedAt,
               Date().timeIntervalSince(since) >= Double(idleTimeoutSeconds) {
                isLocked = true
            }
            backgroundedAt = nil
        default:
            break
        }
    }

    /// Prompt for biometrics / passcode. No-op if not locked or mid-prompt.
    func authenticate() {
        guard isLocked, !isAuthenticating else { return }
        let context = LAContext()
        var error: NSError?
        guard context.canEvaluatePolicy(.deviceOwnerAuthentication, error: &error) else {
            // No biometrics AND no passcode configured — don't trap the user.
            isLocked = false
            return
        }
        isAuthenticating = true
        context.evaluatePolicy(
            .deviceOwnerAuthentication,
            localizedReason: L("applock.reason")
        ) { [weak self] success, _ in
            Task { @MainActor in
                self?.isAuthenticating = false
                if success { self?.isLocked = false }
            }
        }
    }

    /// Biometry-aware unlock button label ("Unlock with Face ID", etc.).
    var unlockButtonTitle: String {
        let context = LAContext()
        _ = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: nil)
        switch context.biometryType {
        case .faceID:  return "\(L("applock.unlock")) · Face ID"
        case .touchID: return "\(L("applock.unlock")) · Touch ID"
        default:       return L("applock.unlock")
        }
    }
}

/// Full-screen lock overlay. Auto-prompts on appear and offers a manual
/// retry button (in case the user dismisses the system sheet).
struct AppLockView: View {
    @EnvironmentObject var appLock: AppLockManager

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color.aurionNavy, Color.aurionNavyDark],
                startPoint: .top, endPoint: .bottom
            ).ignoresSafeArea()

            VStack(spacing: 20) {
                AurionLogoLockup(size: 1.0, dark: true)
                    .padding(.bottom, 8)

                Image(systemName: "lock.fill")
                    .font(.system(size: 34, weight: .semibold))
                    .foregroundColor(.aurionGold)

                Text(L("applock.title"))
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundColor(.white)
                Text(L("applock.subtitle"))
                    .font(.system(size: 14))
                    .foregroundColor(Color.aurionOnNavySecondary)

                Button {
                    AurionHaptics.impact(.medium)
                    appLock.authenticate()
                } label: {
                    HStack(spacing: 8) {
                        Image(systemName: "faceid")
                        Text(appLock.unlockButtonTitle)
                    }
                    .frame(maxWidth: .infinity)
                }
                .buttonStyle(AurionPrimaryButtonStyle())
                .padding(.horizontal, 48)
                .padding(.top, 12)
                .disabled(appLock.isAuthenticating)
            }
        }
        .transition(.opacity)
        .onAppear { appLock.authenticate() }
    }
}
