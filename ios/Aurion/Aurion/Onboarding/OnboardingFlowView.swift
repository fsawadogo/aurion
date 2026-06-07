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
    /// `OnboardingStep.allCases` order. Computed (not static) so the words
    /// re-localize when the UI language changes at runtime.
    private var stepLabels: [String] {
        [
            L("onboarding.flow.stepPair"),
            L("onboarding.flow.stepVoice"),
            L("onboarding.flow.stepConsent"),
            L("onboarding.flow.stepRecord"),
            L("onboarding.flow.stepSave"),
        ]
    }

    /// Maps the current enum case to a 0-based index.
    private var currentStepIndex: Int {
        OnboardingStep.allCases.firstIndex(of: currentStep) ?? 0
    }

    /// Progress fraction: the fill terminates at the center of the
    /// currently active step's label. Each label slot is 1/total of the
    /// bar width, so the center of step N sits at (N + 0.5)/total.
    /// On the first step the fill reaches the middle of "Pair" rather
    /// than overshooting past it.
    private var progressFraction: CGFloat {
        let total = CGFloat(OnboardingStep.allCases.count)
        return (CGFloat(currentStepIndex) + 0.5) / total
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
                            },
                            // Mic-denied recovery (#296 #10): voice enrollment
                            // is optional, so offer Skip out of the dead-end.
                            onSkip: { completeOnboarding() }
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
                    // Track — adaptive (was .aurionNavy.opacity(0.1),
                    // invisible on the dark background in dark mode) (#293).
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.aurionBorder)
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
                ForEach(0..<stepLabels.count, id: \.self) { index in
                    Text(stepLabels[index])
                        .aurionFont(
                            11,
                            weight: index == currentStepIndex ? .bold : .medium,
                            relativeTo: .caption2
                        )
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
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
        // Expose the header as one progress element instead of five
        // disconnected words; VoiceOver hears the current step and total.
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(L("a11y.progress"))
        .accessibilityValue(
            L("setup.step", currentStepIndex + 1, OnboardingStep.allCases.count)
                + ", " + stepLabels[currentStepIndex]
        )
    }

    private func completeOnboarding() {
        appState.isOnboardingComplete = true
        appState.checkVoiceEnrollment()
    }
}
