import SwiftUI
import Foundation
import Combine

/// Global app state — manages auth, session, and onboarding status.
@MainActor
final class AppState: ObservableObject {
    @Published var isAuthenticated = false
    @Published var isOnboardingComplete = false
    @Published var hasVoiceProfile = false
    @Published var currentSession: CaptureSession?
    @Published var userRole: UserRole = .clinician

    /// Check if voice embedding exists in Keychain
    func checkVoiceEnrollment() {
        hasVoiceProfile = KeychainHelper.shared.hasVoiceEmbedding()
    }
}

enum UserRole: String, Codable {
    case clinician = "CLINICIAN"
    case evalTeam = "EVAL_TEAM"
    case complianceOfficer = "COMPLIANCE_OFFICER"
    case admin = "ADMIN"
}
