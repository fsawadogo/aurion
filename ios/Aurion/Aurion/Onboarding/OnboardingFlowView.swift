import SwiftUI

/// First-launch onboarding flow: Wearable Setup -> Voice Enrollment -> Dashboard
struct OnboardingFlowView: View {
    @EnvironmentObject var appState: AppState
    @State private var currentStep: OnboardingStep = .wearableSetup

    enum OnboardingStep: CaseIterable {
        case wearableSetup
        case voiceExplanation
        case biometricConsent
        case voiceRecording
        case voiceProcessing
    }

    /// Maps the current enum case to a 0-based index for progress dots.
    private var currentStepIndex: Int {
        OnboardingStep.allCases.firstIndex(of: currentStep) ?? 0
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                Group {
                    switch currentStep {
                    case .wearableSetup:
                        WearableSetupView(onComplete: {
                            currentStep = .voiceExplanation
                        })
                        .transition(AurionTransition.fadeSlide)
                    case .voiceExplanation:
                        VoiceExplanationView(
                            onGetStarted: { currentStep = .biometricConsent },
                            onSkip: { completeOnboarding() }
                        )
                        .transition(AurionTransition.fadeSlide)
                    case .biometricConsent:
                        BiometricConsentView(
                            onAccept: { currentStep = .voiceRecording },
                            onBack: { currentStep = .voiceExplanation }
                        )
                        .transition(AurionTransition.fadeSlide)
                    case .voiceRecording:
                        VoiceRecordingView(
                            onComplete: { currentStep = .voiceProcessing }
                        )
                        .transition(AurionTransition.fadeSlide)
                    case .voiceProcessing:
                        VoiceProcessingView(
                            onComplete: { completeOnboarding() }
                        )
                        .transition(AurionTransition.fadeSlide)
                    }
                }
                .animation(AurionAnimation.smooth, value: currentStep)

                // Progress dots
                progressDots
                    .padding(.bottom, 24)
            }
            .navigationBarBackButtonHidden(true)
        }
    }

    // MARK: - Progress Dots

    private var progressDots: some View {
        HStack(spacing: 8) {
            ForEach(0..<OnboardingStep.allCases.count, id: \.self) { index in
                Circle()
                    .fill(index == currentStepIndex ? Color.aurionGold : Color.aurionNavy.opacity(0.2))
                    .frame(width: 8, height: 8)
                    .scaleEffect(index == currentStepIndex ? 1.2 : 1.0)
                    .animation(AurionAnimation.spring, value: currentStepIndex)
            }
        }
    }

    private func completeOnboarding() {
        appState.isOnboardingComplete = true
        appState.checkVoiceEnrollment()
    }
}
