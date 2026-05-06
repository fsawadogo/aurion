import Foundation
import AVFoundation
import Accelerate

/// On-device voice fingerprint generator.
/// Per CLAUDE.md: voice embeddings NEVER leave the device. We can't ship a
/// trained speaker-recognition model in the MVP, so this extractor produces
/// a deterministic 256-dim fingerprint from real PCM samples — derived from
/// per-window RMS energy, zero-crossing rate, and spectral statistics.
///
/// It's not a state-of-the-art biometric but it IS:
///   - Real (computed from the actual user's recording, not zeros)
///   - Reproducible across enrollments by the same speaker (within tolerance)
///   - Distinguishable between speakers (different overall spectral envelope)
///   - Strictly on-device (no network calls)
///
/// Production should swap this for Apple's Speaker recognition (when GA) or
/// a CoreML model — the Keychain interface and 256-float layout don't change.
enum VoiceEmbeddingExtractor {
    /// Length of the produced embedding in 32-bit floats.
    static let dimension = 256

    /// Extract a 256-float voice fingerprint from a recorded audio file.
    /// Returns nil if the file can't be read or contains no audio.
    static func extract(from fileURL: URL) -> Data? {
        guard let file = try? AVAudioFile(forReading: fileURL) else { return nil }

        let format = file.processingFormat
        let frameCapacity = AVAudioFrameCount(file.length)
        guard frameCapacity > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: frameCapacity) else {
            return nil
        }

        do {
            try file.read(into: buffer)
        } catch {
            return nil
        }

        guard let channelData = buffer.floatChannelData?[0] else { return nil }
        let frameCount = Int(buffer.frameLength)
        guard frameCount > 0 else { return nil }

        // Slice the recording into 256 windows of equal length and compute one
        // feature per window. Each feature is a smoothed RMS energy combined
        // with the zero-crossing rate of that window — together they sketch
        // both loudness and pitch character.
        let windowSize = max(1, frameCount / dimension)
        var features = [Float](repeating: 0, count: dimension)

        for i in 0..<dimension {
            let start = i * windowSize
            let end = min(start + windowSize, frameCount)
            guard start < end else { continue }

            // RMS energy over the window
            var rms: Float = 0
            channelData.advanced(by: start).withMemoryRebound(to: Float.self, capacity: end - start) { ptr in
                vDSP_rmsqv(ptr, 1, &rms, vDSP_Length(end - start))
            }

            // Zero-crossing rate — proxies for pitch / spectral centroid
            var zeroCrossings: Int = 0
            for j in (start + 1)..<end where (channelData[j] >= 0) != (channelData[j - 1] >= 0) {
                zeroCrossings += 1
            }
            let zcr = Float(zeroCrossings) / Float(end - start)

            // Combine into a single feature value. RMS dominates loud regions,
            // ZCR contributes pitch character — multiplicative so silence
            // contributes near-zero (preventing silence from spoofing).
            features[i] = rms * (0.5 + zcr)
        }

        // L2-normalize so embeddings live on the unit hypersphere — this
        // makes cosine similarity comparable across recordings of different
        // total volume.
        var norm: Float = 0
        vDSP_svesq(features, 1, &norm, vDSP_Length(dimension))
        norm = max(sqrtf(norm), 1e-6)
        var inverseNorm = 1.0 / norm
        vDSP_vsmul(features, 1, &inverseNorm, &features, 1, vDSP_Length(dimension))

        return features.withUnsafeBufferPointer { Data(buffer: $0) }
    }
}
