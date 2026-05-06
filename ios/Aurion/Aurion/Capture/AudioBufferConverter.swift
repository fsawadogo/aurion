@preconcurrency import AVFoundation
import CoreMedia
import Foundation

/// Converts incoming `CMSampleBuffer` audio (whatever native format the iPhone
/// mic produces — typically 32-bit float at 44.1 or 48 kHz) into 16-bit signed
/// PCM at 16 kHz mono, which is the format `WAVBuilder.build` claims to wrap
/// and the format Whisper / most STT services expect.
///
/// Without this conversion the WAV header lies about the payload, the audio
/// level meter computes garbage values (Float32 bytes reinterpreted as Int16),
/// and the transcription service either rejects the upload or transcribes
/// garbled audio at the wrong tempo. The mismatch is silent on the iOS side —
/// nothing throws, the bytes just don't decode the way the header promises.
///
/// The converter is built lazily from the first sample buffer's format
/// description so it tracks whatever the device is actually delivering. If
/// the format changes mid-session (rare — only happens on a route change
/// like Bluetooth-mic plug-in) call `reset()` to rebuild.
///
/// Marked `nonisolated` because it's invoked from `AVCaptureAudioDataOutput`'s
/// delegate queue (single serial queue), not the main actor. The project's
/// `default-isolation=MainActor` would otherwise pull this into MainActor,
/// which would cross-thread on every audio buffer. Synchronization is the
/// caller's job — in practice CaptureManager invokes this from one queue.
nonisolated final class AudioBufferConverter: @unchecked Sendable {

    /// Standardized output: 16-bit signed PCM, 16 kHz, mono, interleaved.
    /// Matches the WAV header `WAVBuilder.build` writes by default.
    private let outputFormat: AVAudioFormat = {
        guard let format = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: 16_000,
            channels: 1,
            interleaved: true
        ) else {
            fatalError("Failed to construct 16kHz/Int16/mono AVAudioFormat")
        }
        return format
    }()

    private var converter: AVAudioConverter?
    private var inputFormat: AVAudioFormat?

    init() {}

    /// Drop the lazy state so the next `convert` call rebuilds against a new
    /// input format. Call after an AVAudioSession route change.
    func reset() {
        converter = nil
        inputFormat = nil
    }

    /// Convert a `CMSampleBuffer` to interleaved Int16 mono PCM at 16 kHz.
    /// Returns the converted bytes and the corresponding peak-RMS level
    /// (0.0…1.0) for the audio meter UI. Returns `nil` if the buffer can't
    /// be wrapped or converted (e.g. malformed sample buffer).
    func convert(_ sampleBuffer: CMSampleBuffer) -> (pcm: Data, rms: Float)? {
        guard ensureConverterReady(for: sampleBuffer),
              let converter,
              let inputFormat else { return nil }

        guard let inputBuffer = Self.pcmBuffer(from: sampleBuffer, format: inputFormat) else {
            return nil
        }

        // Output capacity scales with the sample-rate ratio. Add a small
        // headroom (256 frames) so the converter never reports the buffer
        // is too small for partial-frame edge cases.
        let outCapacity = AVAudioFrameCount(
            Double(inputBuffer.frameLength) * outputFormat.sampleRate / inputFormat.sampleRate
        ) + 256
        guard outCapacity > 0,
              let outputBuffer = AVAudioPCMBuffer(
                pcmFormat: outputFormat,
                frameCapacity: outCapacity
              ) else {
            return nil
        }

        var consumed = false
        var convError: NSError?
        let result = converter.convert(to: outputBuffer, error: &convError) { _, outStatus in
            if consumed {
                outStatus.pointee = .noDataNow
                return nil
            }
            consumed = true
            outStatus.pointee = .haveData
            return inputBuffer
        }

        guard result != .error,
              let int16Channel = outputBuffer.int16ChannelData?[0] else {
            return nil
        }

        let frameCount = Int(outputBuffer.frameLength)
        guard frameCount > 0 else { return nil }
        let byteCount = frameCount * MemoryLayout<Int16>.size
        let data = Data(bytes: int16Channel, count: byteCount)

        // RMS for the meter UI — computed on the same buffer we just wrote so
        // the level matches what's actually persisted.
        var sumSquares: Float = 0
        for i in 0..<frameCount {
            let s = Float(int16Channel[i]) / Float(Int16.max)
            sumSquares += s * s
        }
        let rms = sqrt(sumSquares / Float(frameCount))
        let clamped = min(max(rms, 0), 1)

        return (pcm: data, rms: clamped)
    }

    // MARK: - Internals

    private func ensureConverterReady(for sampleBuffer: CMSampleBuffer) -> Bool {
        if converter != nil { return true }
        guard let formatDesc = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbdPtr = CMAudioFormatDescriptionGetStreamBasicDescription(formatDesc) else {
            return false
        }
        var asbd = asbdPtr.pointee
        guard let inFmt = AVAudioFormat(streamDescription: &asbd) else { return false }
        self.inputFormat = inFmt
        self.converter = AVAudioConverter(from: inFmt, to: outputFormat)
        return self.converter != nil
    }

    /// Wrap the sample buffer's underlying audio buffer list in an
    /// `AVAudioPCMBuffer`. Uses `bufferListNoCopy` so we don't allocate and
    /// memcpy on every audio callback (these fire ~20–40 times per second
    /// during recording — copy cost adds up).
    ///
    /// Exposed as a static helper so `LiveTranscriber` can reuse it without
    /// duplicating the buffer-list dance — both consumers want the same
    /// AVAudioPCMBuffer view of the same incoming CMSampleBuffer.
    static func pcmBuffer(
        from sampleBuffer: CMSampleBuffer,
        format: AVAudioFormat
    ) -> AVAudioPCMBuffer? {
        let numSamples = CMSampleBufferGetNumSamples(sampleBuffer)
        guard numSamples > 0 else { return nil }

        var blockBuffer: CMBlockBuffer?
        var audioBufferList = AudioBufferList()
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer,
            bufferListSizeNeededOut: nil,
            bufferListOut: &audioBufferList,
            bufferListSize: MemoryLayout<AudioBufferList>.size,
            blockBufferAllocator: nil,
            blockBufferMemoryAllocator: nil,
            flags: 0,
            blockBufferOut: &blockBuffer
        )
        guard status == noErr else { return nil }

        guard let pcmBuffer = AVAudioPCMBuffer(
            pcmFormat: format,
            bufferListNoCopy: &audioBufferList,
            deallocator: nil
        ) else { return nil }

        pcmBuffer.frameLength = AVAudioFrameCount(numSamples)
        return pcmBuffer
    }
}
