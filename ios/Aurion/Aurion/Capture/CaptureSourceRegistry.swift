import Foundation
import Combine
import SwiftUI

/// Singleton registry of every capture source the app knows about. Mirrors
/// the backend's provider_registry.py pattern: views and SessionManager
/// always go through `CaptureSourceRegistry.shared` rather than instantiating
/// a concrete source directly.
///
/// Audio and video are tracked independently because some hardware (notably
/// Ray-Ban Meta via the Wearables Toolkit) exposes only one of the two —
/// Meta gives you video frames but the mic still goes through BT Classic
/// to a separate audio source.
@MainActor
final class CaptureSourceRegistry: ObservableObject {
    static let shared = CaptureSourceRegistry()

    @Published private(set) var sources: [CaptureSource] = []

    /// Strongly-typed handle on the always-present built-in source. Surfaced
    /// here so DeviceHubView / permission UI can read camera+mic state without
    /// casting through `sources` or instantiating a second CaptureManager.
    let builtIn: BuiltInCaptureSource

    /// Required — every session needs an audio source for transcription.
    /// Defaults to BuiltInCaptureSource on first launch.
    @Published var activeAudioSource: CaptureSource

    /// Optional — sessions can run audio-only when the physician doesn't
    /// want video. nil means no video stream this session.
    @Published var activeVideoSource: CaptureSource?

    /// Sources that can record audio. Surfaced in DeviceHubView's audio picker.
    var audioSources: [CaptureSource] {
        sources.filter { $0.capabilities.contains(.audio) }
    }

    /// Sources that can record video. Surfaced in DeviceHubView's video picker.
    var videoSources: [CaptureSource] {
        sources.filter { $0.capabilities.contains(.video) }
    }

    /// Active sources to start/stop for a recording, deduplicated by identity.
    /// When audio and video resolve to the same instance (e.g. iPhone covers both),
    /// it appears once — avoids `start()` being called twice on a shared
    /// AVCaptureSession, which throws and produces ambiguous state.
    var activeSourcesForSession: [CaptureSource] {
        var seen = Set<ObjectIdentifier>()
        var result: [CaptureSource] = []
        for source in [activeAudioSource, activeVideoSource].compactMap({ $0 }) {
            if seen.insert(ObjectIdentifier(source)).inserted {
                result.append(source)
            }
        }
        return result
    }

    private static let audioSourceKey = "aurion.capture.audio_source_id"
    private static let videoSourceKey = "aurion.capture.video_source_id"
    private static let videoNoneSentinel = "__none__"

    private init() {
        let builtin = BuiltInCaptureSource()
        let bluetooth = BluetoothAudioSource()
        let meta = MetaWearablesSource()
        builtIn = builtin
        sources = [builtin, bluetooth, meta]
        activeAudioSource = builtin
        activeVideoSource = builtin

        if let savedAudioID = UserDefaults.standard.string(forKey: Self.audioSourceKey),
           let restored = sources.first(where: { $0.id == savedAudioID && $0.capabilities.contains(.audio) }) {
            activeAudioSource = restored
        }
        if let savedVideoID = UserDefaults.standard.string(forKey: Self.videoSourceKey) {
            if savedVideoID == Self.videoNoneSentinel {
                activeVideoSource = nil
            } else if let restored = sources.first(where: { $0.id == savedVideoID && $0.capabilities.contains(.video) }) {
                activeVideoSource = restored
            }
        }

        for source in sources { source.discoverIfNeeded() }
    }

    func setActiveAudio(_ id: String) {
        guard let source = sources.first(where: { $0.id == id }),
              source.capabilities.contains(.audio),
              source.status.isSelectable else { return }
        activeAudioSource = source
        UserDefaults.standard.set(id, forKey: Self.audioSourceKey)
    }

    /// Pass nil to disable video for the next session.
    func setActiveVideo(_ id: String?) {
        if let id {
            guard let source = sources.first(where: { $0.id == id }),
                  source.capabilities.contains(.video),
                  source.status.isSelectable else { return }
            activeVideoSource = source
            UserDefaults.standard.set(id, forKey: Self.videoSourceKey)
        } else {
            activeVideoSource = nil
            UserDefaults.standard.set(Self.videoNoneSentinel, forKey: Self.videoSourceKey)
        }
    }
}
