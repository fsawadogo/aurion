import Foundation
import Combine
import SwiftUI
import AVFoundation

/// Lifecycle states a capture source moves through during a session.
/// Used by DeviceHubView to render status pills and by SessionManager
/// to gate UI flow ("Start Recording" disabled unless source is `.ready`).
enum CaptureSourceStatus: Equatable, Sendable {
    /// Hardware/permission missing or feature flag off. String is user-facing reason.
    case unavailable(String)
    case disconnected
    case ready
    case starting
    case recording
    case paused
    /// Hardware error or permission revoked mid-session. String is user-facing.
    case error(String)

    var label: String {
        switch self {
        case .unavailable(let reason): return reason
        case .disconnected: return L("sourceStatus.disconnected")
        case .ready: return L("sourceStatus.ready")
        case .starting: return L("sourceStatus.starting")
        case .recording: return L("sourceStatus.recording")
        case .paused: return L("sourceStatus.paused")
        case .error(let msg): return msg
        }
    }

    var tint: Color {
        switch self {
        case .unavailable, .disconnected: return .aurionTextSecondary
        case .ready: return .aurionGreen
        case .starting: return .aurionGold
        case .recording: return .aurionRed
        case .paused: return .aurionAmber
        case .error: return .aurionRed
        }
    }

    var isSelectable: Bool {
        if case .unavailable = self { return false }
        return true
    }
}

/// What a capture source can produce. Drives UI gating (e.g. screen capture
/// toggle only shown for sources that support it).
struct CaptureCapability: OptionSet, Sendable {
    let rawValue: Int
    static let audio  = CaptureCapability(rawValue: 1 << 0)
    static let video  = CaptureCapability(rawValue: 1 << 1)
    static let screen = CaptureCapability(rawValue: 1 << 2)
}

/// Abstract base for every capture source — built-in iPhone, Bluetooth audio,
/// Meta Wearables, body cam, etc. Mirrors the backend AI provider registry
/// pattern: SessionManager talks to `any CaptureSource`, never a concrete type.
///
/// Subclasses MUST override `id`, `displayName`, `capabilities`, `start()`,
/// and `getRecordedAudioData()`. Other methods have no-op defaults so simple
/// audio-only sources don't have to implement video paths.
@MainActor
class CaptureSource: ObservableObject, Identifiable {
    // MARK: - Static identity (subclasses override)
    var id: String { "abstract" }
    var displayName: String { "Capture Source" }
    var iconSystemName: String { "circle" }
    var capabilities: CaptureCapability { [] }

    // MARK: - Observable state
    /// Current lifecycle state. Subclasses should update this directly.
    @Published var status: CaptureSourceStatus = .disconnected
    /// Live mic level 0...1 — drives the waveform UI. Sources without an
    /// audio meter can leave this at 0.
    @Published var audioLevel: Float = 0
    /// Sub-line shown beneath the source name (e.g. "Ray-Ban Meta · -28 dB").
    /// Default is empty; subclasses populate as appropriate.
    @Published var detail: String = ""
    /// Frames buffered during recording, drained by the vision pipeline.
    @Published var capturedFrames: [CapturedFrame] = []

    // MARK: - Lifecycle (subclasses override)

    /// Called once on app launch + again after sign-in. Sources kick off
    /// async discovery here (BT route polling, BLE scan, permission request).
    /// Must be cheap and idempotent.
    func discoverIfNeeded() {}

    /// Begin capture. Throws if permissions are denied or the underlying
    /// hardware is unavailable. Sets `status = .starting → .recording`.
    func start() throws {
        throw CaptureSourceError.notImplemented
    }

    /// Pause capture without releasing the underlying session. Buffers are preserved.
    func pause() {}

    /// Resume from a paused state.
    func resume() {}

    /// Stop capture and finalize the audio buffer. After this returns,
    /// `getRecordedAudioData()` should return the complete WAV.
    func stop() {}

    /// PCM-derived WAV for the just-completed recording. Returns nil if no
    /// audio was captured (video-only source, or session never started).
    func getRecordedAudioData() -> Data? { nil }

    /// Recorded audio as an `AVAudioPCMBuffer` for downstream on-device
    /// processing (e.g. speaker tagging). Returns nil for sources that
    /// don't capture audio or only retain WAV bytes.
    func getRecordedPCMBuffer() -> AVAudioPCMBuffer? { nil }

    /// Drop any retained audio PCM. Called by `LocalDataPurger.purgeAll`
    /// when export completes or when an explicit purge is requested.
    /// Default is a no-op so video-only sources don't need to override.
    func discardRecordedAudio() {}

    /// Size in bytes of the retained audio PCM, without copying the
    /// buffer. Subclasses should peek at their backing storage; the
    /// fallback that builds a WAV just to count bytes is for source
    /// implementations that haven't been updated yet.
    func getRecordedAudioByteCount() -> Int {
        getRecordedAudioData()?.count ?? 0
    }
}

/// A capture source whose video frames can drive the clip pipeline.
///
/// `SessionManager`'s cadence-clip driver and post-stop visual-evidence path
/// operate on `any VideoClipSource` rather than a concrete source, so the
/// built-in iPhone camera and external sources (e.g. Meta Ray-Ban glasses,
/// #443) plug into the SAME masking → upload pipeline. A conformer owns a
/// `VideoRingBuffer` of recent frames and can extract a clip window from it.
///
/// Privacy: `extractCadenceClip` returns RAW (unmasked) bytes by contract —
/// the caller MUST run the MP4 through `MaskingPipeline.maskClip` before any
/// network / persistence boundary (the same rule `VideoRingBuffer` documents).
@MainActor
protocol VideoClipSource: CaptureSource {
    /// In-memory ring of recent frames (raw, never uploaded; cleared on stop).
    var clipRingBuffer: VideoRingBuffer { get }

    /// Extract a clip window ending at the current ring clock as a temp MP4.
    /// Returns RAW (unmasked) bytes; `nil` when the ring can't satisfy the
    /// window yet (warm-up before the first frame, or just-cleared on stop).
    func extractCadenceClip(windowMs: Int) async -> (url: URL, timestampMs: Int)?

    /// Resize the ring + set the capture FPS for the live cadence path.
    /// MUST be called before `start()` (the ring is rebuilt empty).
    func applyPipelineConfig(videoCaptureFPS: Double, clipWindowMs: Int)
}

enum CaptureSourceError: LocalizedError {
    case notImplemented
    case permissionDenied(String)
    case hardwareUnavailable(String)
    case featureGated(String)

    var errorDescription: String? {
        switch self {
        case .notImplemented: return "This capture source isn't available yet."
        case .permissionDenied(let what): return "Permission required: \(what)."
        case .hardwareUnavailable(let what): return "\(what) is not available."
        case .featureGated(let what): return "\(what) is disabled by server config."
        }
    }
}

/// Standard PCM settings used by every audio-only recorder in the app
/// (voice enrollment, Bluetooth audio source). 16 kHz mono 16-bit matches
/// what Whisper expects, so the backend doesn't have to resample.
enum AurionAudioFormat {
    static let recorderSettings: [String: Any] = [
        AVFormatIDKey: kAudioFormatLinearPCM,
        AVSampleRateKey: 16_000.0,
        AVNumberOfChannelsKey: 1,
        AVLinearPCMBitDepthKey: 16,
        AVLinearPCMIsBigEndianKey: false,
        AVLinearPCMIsFloatKey: false,
    ]
}
