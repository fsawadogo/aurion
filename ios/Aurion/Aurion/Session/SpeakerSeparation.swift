import Foundation
import AVFoundation
import Accelerate

// MARK: - Speaker Separation

/// On-device speaker separation using MFCC-based voice embeddings.
///
/// Enrollment: generates a 128-dimension voice embedding from the physician's speech sample.
/// Session-time: compares each transcript segment's audio against the enrollment embedding
/// using cosine similarity. Score > 0.85 tags as "physician", otherwise "other".
///
/// Privacy: voice embedding stored exclusively in Keychain via KeychainHelper.
/// Raw audio deleted immediately after embedding generation. Embedding never transmitted to backend.
///
/// Production note: this simplified MFCC approach is suitable for MVP speaker verification.
/// Phase 7 evaluation will compare against SpeechBrain Core ML and Apple SFSpeakerRecognition.
final class SpeakerSeparation {
    static let shared = SpeakerSeparation()

    /// Cosine similarity threshold: > 0.85 = physician, <= 0.85 = other.
    let similarityThreshold: Float = 0.85

    /// Embedding dimension. Must match between enrollment and segment comparison.
    let embeddingDimension: Int = 128

    // MARK: - MFCC Configuration

    /// Number of Mel filter banks for MFCC extraction.
    private let numMelFilters: Int = 40

    /// Number of MFCC coefficients to keep per frame.
    private let numMFCCCoefficients: Int = 13

    /// FFT length for spectral analysis.
    private let fftLength: Int = 512

    /// Hop size in samples between analysis frames.
    private let hopLength: Int = 256

    /// Target sample rate for audio processing.
    private let targetSampleRate: Double = 16000.0

    /// Cached Mel filter bank -- computed once from constant parameters,
    /// reused across all calls to avoid redundant computation.
    private lazy var cachedMelFilters: [[Float]] = createMelFilterBank(
        numFilters: numMelFilters,
        fftSize: fftLength,
        sampleRate: targetSampleRate
    )

    private init() {}

    // MARK: - Voice Embedding Generation

    /// Generate a 128-dimension voice embedding from an audio buffer.
    ///
    /// Extracts MFCC features using Accelerate framework vDSP functions,
    /// then computes a compact embedding by averaging and projecting the MFCC matrix.
    ///
    /// - Parameter audioBuffer: PCM audio buffer from the enrollment recording.
    /// - Returns: 128-dimension Float array, or nil if extraction fails.
    func generateEmbedding(from audioBuffer: AVAudioPCMBuffer) -> [Float]? {
        guard let channelData = audioBuffer.floatChannelData?[0] else { return nil }
        let frameCount = Int(audioBuffer.frameLength)
        guard frameCount > fftLength else { return nil }

        let samples = Array(UnsafeBufferPointer(start: channelData, count: frameCount))

        // Step 1: Compute MFCC feature matrix
        guard let mfccMatrix = extractMFCCFeatures(from: samples) else { return nil }

        // Step 2: Reduce MFCC matrix to a fixed-size embedding
        let embedding = computeEmbeddingFromMFCC(mfccMatrix)

        guard embedding.count == embeddingDimension else { return nil }
        return embedding
    }

    // MARK: - Speaker Comparison

    /// Compute cosine similarity between two embedding vectors using Accelerate.
    ///
    /// - Parameters:
    ///   - a: First embedding vector.
    ///   - b: Second embedding vector.
    /// - Returns: Cosine similarity in range [-1, 1]. Returns 0 if vectors have different lengths.
    func cosineSimilarity(_ a: [Float], _ b: [Float]) -> Float {
        guard a.count == b.count, !a.isEmpty else { return 0.0 }

        var dotProduct: Float = 0
        var normA: Float = 0
        var normB: Float = 0

        vDSP_dotpr(a, 1, b, 1, &dotProduct, vDSP_Length(a.count))
        vDSP_dotpr(a, 1, a, 1, &normA, vDSP_Length(a.count))
        vDSP_dotpr(b, 1, b, 1, &normB, vDSP_Length(b.count))

        let denominator = sqrtf(normA) * sqrtf(normB)
        guard denominator > 0 else { return 0.0 }

        return dotProduct / denominator
    }

    // MARK: - Segment Tagging

    /// Tag a transcript segment's speaker by comparing its audio against the enrollment embedding.
    ///
    /// - Parameters:
    ///   - segmentAudio: PCM audio buffer for the transcript segment.
    ///   - enrollmentEmbedding: The physician's stored voice embedding.
    /// - Returns: Tuple of speaker label ("physician" or "other") and confidence score.
    func tagSpeaker(segmentAudio: AVAudioPCMBuffer, enrollmentEmbedding: [Float]) -> (speaker: String, confidence: Float) {
        guard let segmentEmbedding = generateEmbedding(from: segmentAudio) else {
            return (speaker: "other", confidence: 0.0)
        }

        let similarity = cosineSimilarity(segmentEmbedding, enrollmentEmbedding)

        if similarity > similarityThreshold {
            return (speaker: "physician", confidence: similarity)
        } else {
            return (speaker: "other", confidence: 1.0 - similarity)
        }
    }

    // MARK: - Keychain Integration

    /// Serialize and save a voice embedding to Keychain via KeychainHelper.
    /// Embedding is stored under key `aurion.physician.voice_embedding`.
    func saveEmbedding(_ embedding: [Float]) {
        let data = embedding.withUnsafeBytes { Data($0) }
        KeychainHelper.shared.saveVoiceEmbedding(data)
    }

    /// Load and deserialize the physician's voice embedding from Keychain.
    /// Returns nil if no embedding has been enrolled.
    func loadEmbedding() -> [Float]? {
        guard let data = KeychainHelper.shared.loadVoiceEmbedding() else { return nil }
        let count = data.count / MemoryLayout<Float>.size
        guard count == embeddingDimension else { return nil }
        return data.withUnsafeBytes { buffer in
            Array(buffer.bindMemory(to: Float.self))
        }
    }

    /// Delete the physician's voice embedding from Keychain.
    /// Called when physician revokes enrollment or deletes voice profile from Settings.
    func deleteEmbedding() {
        KeychainHelper.shared.deleteVoiceEmbedding()
    }

    /// Check whether a voice embedding is currently enrolled.
    var isEnrolled: Bool {
        KeychainHelper.shared.hasVoiceEmbedding()
    }

    // MARK: - MFCC Feature Extraction (Private)

    /// Extract MFCC features from raw audio samples using Accelerate vDSP.
    ///
    /// Process:
    /// 1. Apply Hann window to each frame
    /// 2. Compute FFT magnitude spectrum
    /// 3. Apply Mel filter bank
    /// 4. Take log of Mel energies
    /// 5. Apply DCT to get MFCC coefficients
    ///
    /// Returns a 2D array: [numFrames][numMFCCCoefficients]
    private func extractMFCCFeatures(from samples: [Float]) -> [[Float]]? {
        let numFrames = (samples.count - fftLength) / hopLength + 1
        guard numFrames > 0 else { return nil }

        // Pre-compute Hann window
        var window = [Float](repeating: 0, count: fftLength)
        vDSP_hann_window(&window, vDSP_Length(fftLength), Int32(vDSP_HANN_NORM))

        // Set up FFT
        let log2n = vDSP_Length(log2f(Float(fftLength)))
        guard let fftSetup = vDSP_create_fftsetup(log2n, FFTRadix(FFT_RADIX2)) else { return nil }
        defer { vDSP_destroy_fftsetup(fftSetup) }

        // Use the cached Mel filter bank instead of recomputing per call.
        let melFilters = cachedMelFilters

        var mfccMatrix: [[Float]] = []

        for frameIndex in 0..<numFrames {
            let startSample = frameIndex * hopLength

            // Extract and window the frame
            var frame = [Float](repeating: 0, count: fftLength)
            let availableSamples = min(fftLength, samples.count - startSample)
            for i in 0..<availableSamples {
                frame[i] = samples[startSample + i]
            }
            vDSP_vmul(frame, 1, window, 1, &frame, 1, vDSP_Length(fftLength))

            // Compute FFT
            let halfN = fftLength / 2
            var realPart = [Float](repeating: 0, count: halfN)
            var imagPart = [Float](repeating: 0, count: halfN)

            // Pack interleaved real data into split complex form
            frame.withUnsafeBufferPointer { framePtr in
                framePtr.baseAddress!.withMemoryRebound(to: DSPComplex.self, capacity: halfN) { complexPtr in
                    var splitComplex = DSPSplitComplex(realp: &realPart, imagp: &imagPart)
                    vDSP_ctoz(complexPtr, 2, &splitComplex, 1, vDSP_Length(halfN))
                }
            }

            var splitComplex = DSPSplitComplex(realp: &realPart, imagp: &imagPart)
            vDSP_fft_zrip(fftSetup, &splitComplex, 1, log2n, FFTDirection(FFT_FORWARD))

            // Compute magnitude spectrum
            var magnitudes = [Float](repeating: 0, count: halfN)
            vDSP_zvmags(&splitComplex, 1, &magnitudes, 1, vDSP_Length(halfN))

            // Normalize
            var scale = Float(1.0 / Float(fftLength))
            vDSP_vsmul(magnitudes, 1, &scale, &magnitudes, 1, vDSP_Length(halfN))

            // Apply Mel filter bank
            var melEnergies = [Float](repeating: 0, count: numMelFilters)
            for filterIdx in 0..<numMelFilters {
                var energy: Float = 0
                vDSP_dotpr(magnitudes, 1, melFilters[filterIdx], 1, &energy, vDSP_Length(halfN))
                melEnergies[filterIdx] = max(energy, 1e-10) // Floor to avoid log(0)
            }

            // Log Mel energies
            var logMelEnergies = [Float](repeating: 0, count: numMelFilters)
            var count = Int32(numMelFilters)
            vvlogf(&logMelEnergies, &melEnergies, &count)

            // DCT to get MFCC coefficients
            let mfcc = applyDCT(logMelEnergies, outputSize: numMFCCCoefficients)
            mfccMatrix.append(mfcc)
        }

        return mfccMatrix.isEmpty ? nil : mfccMatrix
    }

    /// Create a Mel-scale triangular filter bank.
    ///
    /// Maps linear frequency bins from the FFT to the Mel scale, producing
    /// triangular overlapping filters that mimic human auditory perception.
    private func createMelFilterBank(numFilters: Int, fftSize: Int, sampleRate: Double) -> [[Float]] {
        let halfFFT = fftSize / 2

        // Convert Hz to Mel scale
        func hzToMel(_ hz: Double) -> Double {
            return 2595.0 * log10(1.0 + hz / 700.0)
        }
        func melToHz(_ mel: Double) -> Double {
            return 700.0 * (pow(10.0, mel / 2595.0) - 1.0)
        }

        let lowMel = hzToMel(0)
        let highMel = hzToMel(sampleRate / 2.0)

        // Linearly spaced points in Mel scale
        var melPoints = [Double](repeating: 0, count: numFilters + 2)
        for i in 0..<(numFilters + 2) {
            melPoints[i] = lowMel + Double(i) * (highMel - lowMel) / Double(numFilters + 1)
        }

        // Convert back to Hz, then to FFT bin indices
        let binPoints = melPoints.map { mel -> Int in
            let hz = melToHz(mel)
            return Int(floor(hz * Double(fftSize) / sampleRate))
        }

        // Build triangular filters
        var filters = [[Float]](repeating: [Float](repeating: 0, count: halfFFT), count: numFilters)

        for m in 0..<numFilters {
            let left = binPoints[m]
            let center = binPoints[m + 1]
            let right = binPoints[m + 2]

            for k in left..<center where k < halfFFT && k >= 0 {
                let denom = Float(center - left)
                if denom > 0 {
                    filters[m][k] = Float(k - left) / denom
                }
            }
            for k in center..<right where k < halfFFT && k >= 0 {
                let denom = Float(right - center)
                if denom > 0 {
                    filters[m][k] = Float(right - k) / denom
                }
            }
        }

        return filters
    }

    /// Apply Type-II DCT to extract MFCC coefficients from log Mel energies.
    private func applyDCT(_ input: [Float], outputSize: Int) -> [Float] {
        let n = input.count
        var output = [Float](repeating: 0, count: outputSize)

        for k in 0..<outputSize {
            var sum: Float = 0
            for i in 0..<n {
                sum += input[i] * cosf(Float.pi * Float(k) * (Float(i) + 0.5) / Float(n))
            }
            output[k] = sum
        }

        return output
    }

    // MARK: - Embedding Computation from MFCC Matrix

    /// Reduce an MFCC feature matrix to a fixed 128-dimension embedding.
    ///
    /// Strategy:
    /// 1. Compute per-coefficient statistics across all frames (mean + std = 26 features)
    /// 2. Compute delta statistics (first-order temporal differences)
    /// 3. Pad/project to exactly 128 dimensions using a deterministic hash-like mixing
    private func computeEmbeddingFromMFCC(_ mfccMatrix: [[Float]]) -> [Float] {
        let numCoeffs = numMFCCCoefficients
        let numFrames = mfccMatrix.count

        // Mean and standard deviation per MFCC coefficient across all frames
        var means = [Float](repeating: 0, count: numCoeffs)
        var stds = [Float](repeating: 0, count: numCoeffs)

        for c in 0..<numCoeffs {
            var sum: Float = 0
            for f in 0..<numFrames {
                sum += mfccMatrix[f][c]
            }
            let mean = sum / Float(numFrames)
            means[c] = mean

            var varSum: Float = 0
            for f in 0..<numFrames {
                let diff = mfccMatrix[f][c] - mean
                varSum += diff * diff
            }
            stds[c] = sqrtf(varSum / Float(numFrames))
        }

        // Delta coefficients — temporal differences between consecutive frames
        var deltaMeans = [Float](repeating: 0, count: numCoeffs)
        var deltaStds = [Float](repeating: 0, count: numCoeffs)

        if numFrames > 1 {
            var deltas = [[Float]](repeating: [Float](repeating: 0, count: numCoeffs), count: numFrames - 1)
            for f in 0..<(numFrames - 1) {
                for c in 0..<numCoeffs {
                    deltas[f][c] = mfccMatrix[f + 1][c] - mfccMatrix[f][c]
                }
            }

            let deltaCount = numFrames - 1
            for c in 0..<numCoeffs {
                var sum: Float = 0
                for f in 0..<deltaCount {
                    sum += deltas[f][c]
                }
                let mean = sum / Float(deltaCount)
                deltaMeans[c] = mean

                var varSum: Float = 0
                for f in 0..<deltaCount {
                    let diff = deltas[f][c] - mean
                    varSum += diff * diff
                }
                deltaStds[c] = sqrtf(varSum / Float(deltaCount))
            }
        }

        // Concatenate all statistical features: means + stds + deltaMeans + deltaStds = 52 values
        var features: [Float] = []
        features.append(contentsOf: means)
        features.append(contentsOf: stds)
        features.append(contentsOf: deltaMeans)
        features.append(contentsOf: deltaStds)

        // Project to exactly embeddingDimension (128) using deterministic mixing
        var embedding = [Float](repeating: 0, count: embeddingDimension)
        let featureCount = features.count

        for i in 0..<embeddingDimension {
            // Combine multiple feature values deterministically
            var val: Float = 0
            for j in 0..<featureCount {
                // Deterministic mixing: each embedding dimension combines features
                // with different phase offsets to maximize information capture
                let idx = (i + j * 7) % featureCount
                let weight = cosf(Float(i * j + 1) * 0.1)
                val += features[idx] * weight
            }
            embedding[i] = val
        }

        // L2 normalize the embedding for cosine similarity
        var norm: Float = 0
        vDSP_dotpr(embedding, 1, embedding, 1, &norm, vDSP_Length(embeddingDimension))
        norm = sqrtf(norm)
        if norm > 0 {
            var invNorm = 1.0 / norm
            vDSP_vsmul(embedding, 1, &invNorm, &embedding, 1, vDSP_Length(embeddingDimension))
        }

        return embedding
    }
}
