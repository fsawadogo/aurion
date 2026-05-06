import SwiftUI

/// First-launch onboarding flow: Wearable Setup -> Voice Enrollment -> Dashboard
struct OnboardingFlowView: View {
    @EnvironmentObject var appState: AppState
    @State private var currentStep: OnboardingStep = .wearableSetup
    @State private var enrollmentAudioURL: URL?

    enum OnboardingStep: CaseIterable {
        case wearableSetup
        case voiceExplanation
        case biometricConsent
        case voiceRecording
        case voiceProcessing
    }

    /// Step labels displayed below the progress bar — must align with
    /// `OnboardingStep.allCases` order.
    private static let stepLabels = ["Pair", "Voice", "Consent", "Record", "Save"]

    /// Maps the current enum case to a 0-based index.
    private var currentStepIndex: Int {
        OnboardingStep.allCases.firstIndex(of: currentStep) ?? 0
    }

    /// Progress fraction: (current step index + 1) / total steps.
    private var progressFraction: CGFloat {
        CGFloat(currentStepIndex + 1) / CGFloat(OnboardingStep.allCases.count)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                // Top progress bar with step labels
                progressHeader
                    .padding(.horizontal, AurionSpacing.xl)
                    .padding(.top, AurionSpacing.sm)
                    .padding(.bottom, AurionSpacing.lg)

                // Step content
                Group {
                    switch currentStep {
                    case .wearableSetup:
                        WearableSetupView(onComplete: {
                            withAnimation(AurionAnimation.smooth) {
                                currentStep = .voiceExplanation
                            }
                        })
                        .transition(AurionTransition.fadeSlide)
                    case .voiceExplanation:
                        VoiceExplanationView(
                            onGetStarted: {
                                withAnimation(AurionAnimation.smooth) {
                                    currentStep = .biometricConsent
                                }
                            },
                            onSkip: { completeOnboarding() }
                        )
                        .transition(AurionTransition.fadeSlide)
                    case .biometricConsent:
                        BiometricConsentView(
                            onAccept: {
                                withAnimation(AurionAnimation.smooth) {
                                    currentStep = .voiceRecording
                                }
                            },
                            onBack: {
                                withAnimation(AurionAnimation.smooth) {
                                    currentStep = .voiceExplanation
                                }
                            }
                        )
                        .transition(AurionTransition.fadeSlide)
                    case .voiceRecording:
                        VoiceRecordingView(
                            onComplete: { url in
                                enrollmentAudioURL = url
                                withAnimation(AurionAnimation.smooth) {
                                    currentStep = .voiceProcessing
                                }
                            }
                        )
                        .transition(AurionTransition.fadeSlide)
                    case .voiceProcessing:
                        VoiceProcessingView(
                            audioFileURL: enrollmentAudioURL,
                            onComplete: { completeOnboarding() }
                        )
                        .transition(AurionTransition.fadeSlide)
                    }
                }
                .animation(AurionAnimation.smooth, value: currentStep)
            }
            .navigationBarBackButtonHidden(true)
        }
    }

    // MARK: - Progress Header

    private var progressHeader: some View {
        VStack(spacing: AurionSpacing.sm) {
            // Thin gold progress line
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    // Track
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.aurionNavy.opacity(0.1))
                        .frame(height: 3)

                    // Filled portion
                    RoundedRectangle(cornerRadius: 2)
                        .fill(
                            LinearGradient(
                                colors: [.aurionGold, .aurionGoldLight],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: geo.size.width * progressFraction, height: 3)
                        .animation(AurionAnimation.smooth, value: progressFraction)
                }
            }
            .frame(height: 3)

            // Step labels
            HStack(spacing: 0) {
                ForEach(0..<Self.stepLabels.count, id: \.self) { index in
                    Text(Self.stepLabels[index])
                        .font(.system(
                            size: 11,
                            weight: index == currentStepIndex ? .bold : .medium
                        ))
                        .foregroundColor(
                            index == currentStepIndex
                                ? .aurionGold
                                : (index < currentStepIndex
                                    ? .aurionTextPrimary
                                    : .secondary.opacity(0.5))
                        )
                        .frame(maxWidth: .infinity)
                        .animation(AurionAnimation.smooth, value: currentStepIndex)
                }
            }
        }
    }

    private func completeOnboarding() {
        appState.isOnboardingComplete = true
        appState.checkVoiceEnrollment()
    }
}
