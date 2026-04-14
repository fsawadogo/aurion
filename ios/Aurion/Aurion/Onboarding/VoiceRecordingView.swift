import SwiftUI
import AVFoundation

/// Screen 3 — Voice recording prompt.
/// Records 30–60 seconds of physician speech for embedding generation.
struct VoiceRecordingView: View {
    let onComplete: () -> Void

    @State private var isRecording = false
    @State private var recordingDuration: TimeInterval = 0
    @State private var audioLevel: Float = 0
    @State private var sentenceIndex = 0
    @State private var canProceed = false

    private let minimumDuration: TimeInterval = 15 // minimum seconds
    private let sentences = [
        "Range of motion is restricted to approximately 90 degrees of flexion.",
        "There is tenderness on palpation at the medial joint line.",
        "The wound edges appear well approximated with no signs of infection.",
        "I am reviewing the imaging now — there is no visible fracture displacement.",
    ]

    var body: some View {
        VStack(spacing: 24) {
            Text("Read aloud in your normal clinical voice")
                .font(.title3)
                .fontWeight(.semibold)
                .foregroundColor(Color.aurionNavy)

            // Clinical sentences to read
            VStack(alignment: .leading, spacing: 12) {
                ForEach(Array(sentences.enumerated()), id: \.offset) { index, sentence in
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: index < sentenceIndex ? "checkmark.circle.fill" : "circle")
                            .foregroundColor(index < sentenceIndex ? .green : Color.aurionNavy.opacity(0.3))
                        Text(sentence)
                            .font(.body)
                            .foregroundColor(index == sentenceIndex ? Color.aurionNavy : .secondary)
                    }
                }
            }
            .padding()
            .background(Color.aurionBackground)
            .cornerRadius(12)
            .padding(.horizontal)

            Spacer()

            // Waveform visualization placeholder
            if isRecording {
                WaveformView(level: audioLevel)
                    .frame(height: 60)
                    .padding(.horizontal, 40)

                Text(String(format: "%.0fs", recordingDuration))
                    .font(.title2)
                    .monospacedDigit()
                    .foregroundColor(Color.aurionNavy)
            }

            // Record button
            Button(action: toggleRecording) {
                ZStack {
                    Circle()
                        .fill(isRecording ? Color.red : Color.aurionGold)
                        .frame(width: 80, height: 80)
                    if isRecording {
                        RoundedRectangle(cornerRadius: 4)
                            .fill(Color.white)
                            .frame(width: 28, height: 28)
                    } else {
                        Circle()
                            .fill(Color.white)
                            .frame(width: 28, height: 28)
                    }
                }
            }
            .padding()

            Text(isRecording ? "Tap to stop" : "Tap to start recording")
                .font(.caption)
                .foregroundColor(.secondary)

            if canProceed {
                Button("Continue") {
                    onComplete()
                }
                .buttonStyle(AurionPrimaryButtonStyle())
            }

            Button("Re-record") {
                resetRecording()
            }
            .font(.caption)
            .foregroundColor(Color.aurionNavy)
            .opacity(canProceed ? 1 : 0)

            Spacer().frame(height: 20)
        }
    }

    private func toggleRecording() {
        if isRecording {
            stopRecording()
        } else {
            startRecording()
        }
    }

    private func startRecording() {
        AurionHaptics.impact(.medium)
        isRecording = true
        recordingDuration = 0
        // AVAudioEngine recording will be implemented in the capture module
        // For now, simulate recording progress
        Timer.scheduledTimer(withTimeInterval: 0.1, repeats: true) { timer in
            if !isRecording {
                timer.invalidate()
                return
            }
            recordingDuration += 0.1
            audioLevel = Float.random(in: 0.1...0.9)

            // Advance sentences based on timing
            let sentenceInterval = 8.0
            let newIndex = min(Int(recordingDuration / sentenceInterval), sentences.count)
            if newIndex > sentenceIndex {
                sentenceIndex = newIndex
            }
        }
    }

    private func stopRecording() {
        isRecording = false
        if recordingDuration >= minimumDuration {
            canProceed = true
        }
    }

    private func resetRecording() {
        canProceed = false
        sentenceIndex = 0
        recordingDuration = 0
    }
}

// MARK: - Waveform Visualization

struct WaveformView: View {
    let level: Float

    var body: some View {
        HStack(spacing: 3) {
            ForEach(0..<30, id: \.self) { i in
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.aurionGold)
                    .frame(width: 4, height: CGFloat.random(in: 4...40) * CGFloat(level))
                    .animation(.easeInOut(duration: 0.1), value: level)
            }
        }
    }
}
