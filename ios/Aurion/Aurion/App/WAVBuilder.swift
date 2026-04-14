import Foundation

/// Builds a standard WAV file from raw PCM data or silence.
///
/// Used by `CaptureManager` to wrap recorded audio and by `SessionManager`
/// to generate mock audio for Simulator testing.  Having a single
/// implementation prevents the header logic from drifting between call sites.
enum WAVBuilder {

    /// Wraps raw PCM data in a WAV header.
    ///
    /// - Parameters:
    ///   - pcmData: Raw 16-bit mono PCM samples.
    ///   - sampleRate: Sample rate in Hz (default 16 000).
    ///   - channels: Number of channels (default 1 -- mono).
    ///   - bitsPerSample: Bits per sample (default 16).
    /// - Returns: A complete WAV file as `Data`.
    static func build(
        from pcmData: Data,
        sampleRate: UInt32 = 16_000,
        channels: UInt16 = 1,
        bitsPerSample: UInt16 = 16
    ) -> Data {
        let byteRate = sampleRate * UInt32(channels) * UInt32(bitsPerSample / 8)
        let blockAlign = channels * (bitsPerSample / 8)
        let dataSize = UInt32(pcmData.count)
        let fileSize: UInt32 = 36 + dataSize

        var wav = Data()

        // RIFF header
        wav.append("RIFF".data(using: .ascii)!)
        wav.append(withUnsafeBytes(of: fileSize.littleEndian) { Data($0) })
        wav.append("WAVE".data(using: .ascii)!)

        // fmt subchunk
        wav.append("fmt ".data(using: .ascii)!)
        wav.append(withUnsafeBytes(of: UInt32(16).littleEndian) { Data($0) })  // subchunk size
        wav.append(withUnsafeBytes(of: UInt16(1).littleEndian) { Data($0) })   // PCM format
        wav.append(withUnsafeBytes(of: channels.littleEndian) { Data($0) })
        wav.append(withUnsafeBytes(of: sampleRate.littleEndian) { Data($0) })
        wav.append(withUnsafeBytes(of: byteRate.littleEndian) { Data($0) })
        wav.append(withUnsafeBytes(of: blockAlign.littleEndian) { Data($0) })
        wav.append(withUnsafeBytes(of: bitsPerSample.littleEndian) { Data($0) })

        // data subchunk
        wav.append("data".data(using: .ascii)!)
        wav.append(withUnsafeBytes(of: dataSize.littleEndian) { Data($0) })
        wav.append(pcmData)

        return wav
    }

    /// Creates a minimal WAV file containing silence.
    ///
    /// Useful for Simulator testing where no real microphone is available.
    ///
    /// - Parameters:
    ///   - durationSeconds: Duration of silence (default 1 second).
    ///   - sampleRate: Sample rate in Hz (default 16 000).
    /// - Returns: A complete WAV file containing the requested silence.
    static func silence(durationSeconds: Double = 1.0, sampleRate: UInt32 = 16_000) -> Data {
        let numSamples = Int(Double(sampleRate) * durationSeconds)
        let silentPCM = Data(count: numSamples * 2) // 16-bit = 2 bytes per sample
        return build(from: silentPCM, sampleRate: sampleRate)
    }
}
