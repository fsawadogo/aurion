import AVFoundation
import SwiftUI
import UIKit

/// Lightweight SwiftUI wrapper around `AVPlayer` + `AVPlayerLayer`.
///
/// Why a custom `UIViewRepresentable` rather than `VideoPlayer` from
/// `AVKit`? Two reasons:
///
/// 1. We control the chrome. `VideoPlayer` ships its own playback
///    controls overlay that conflicts with `FullClipView`'s photo-
///    viewer aesthetic (dark background, white timestamp principal,
///    gold close button). `AVPlayerLayer` gives us a bare video
///    surface we compose ourselves.
/// 2. We need explicit looping. `AVPlayer` doesn't loop by default;
///    `AVPlayerLooper` works only with `AVQueuePlayer` and adds
///    complexity. The `.AVPlayerItemDidPlayToEndTime` observer is
///    the shortest path to "auto-play, loop forever, no controls".
///
/// ## Lifecycle
///
/// - `makeUIView`: configures the `AVPlayer` against `url`, attaches
///   the layer, registers the loop observer, kicks playback. The
///   coordinator owns the player and observer reference so they
///   survive view recomposition.
/// - `updateUIView`: a no-op for now; the wrapper assumes a single
///   URL per instance (the reviewer presents a fresh sheet per
///   citation tap, so swapping URLs mid-view doesn't happen).
/// - `dismantleUIView`: pauses the player and removes the observer
///   so a dismissed `FullClipView` doesn't leak the resource. Belt
///   and suspenders on top of SwiftUI's automatic teardown.
///
/// ## Determinism
///
/// `AVPlayer.rate > 0` after `play()` is documented behaviour but
/// not synchronous on every device. The matching test waits briefly
/// before asserting; the coordinator's `play()` invocation is
/// always-fired regardless so the user-visible behaviour is "the
/// clip starts playing as soon as the view appears".
struct AurionVideoPlayer: UIViewRepresentable {
    let url: URL

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    func makeUIView(context: Context) -> PlayerContainerView {
        let view = PlayerContainerView()
        let player = AVPlayer(url: url)
        view.playerLayer.player = player
        view.playerLayer.videoGravity = .resizeAspect

        context.coordinator.attach(player: player, item: player.currentItem)
        // Auto-play on present — matches FullFrameView's "always
        // visible immediately" UX. The user came here to see the
        // clip; the prior tap is the intent signal.
        player.play()
        return view
    }

    func updateUIView(_ uiView: PlayerContainerView, context: Context) {
        // Single-URL-per-instance. The reviewer presents a fresh
        // sheet per citation; no need to re-wire the player here.
    }

    static func dismantleUIView(_ uiView: PlayerContainerView, coordinator: Coordinator) {
        coordinator.tearDown(playerLayer: uiView.playerLayer)
    }

    // MARK: - Coordinator

    /// Owns the player + the loop observer. Kept off the view so
    /// SwiftUI's view-rebuild semantics don't drop the player
    /// reference mid-playback.
    final class Coordinator {
        private weak var player: AVPlayer?
        private var loopObserver: NSObjectProtocol?

        func attach(player: AVPlayer, item: AVPlayerItem?) {
            self.player = player
            guard let item else { return }
            // Loop on end — seek to .zero + restart. Cheap on H.264
            // local files; the ring-buffer-extracted clips are
            // typically 7 s @ 720p so the seek is sub-frame on every
            // pilot device.
            loopObserver = NotificationCenter.default.addObserver(
                forName: .AVPlayerItemDidPlayToEndTime,
                object: item,
                queue: .main
            ) { [weak player] _ in
                player?.seek(to: .zero)
                player?.play()
            }
        }

        func tearDown(playerLayer: AVPlayerLayer) {
            if let observer = loopObserver {
                NotificationCenter.default.removeObserver(observer)
                loopObserver = nil
            }
            // Pause explicitly — preventing a brief tail of audio
            // (clips are video-only by contract, but belt and
            // suspenders) or background CPU from a still-playing
            // player after the sheet dismisses.
            playerLayer.player?.pause()
            playerLayer.player = nil
        }
    }
}

/// `UIView` whose backing layer is an `AVPlayerLayer`. SwiftUI gives
/// us the host view; we just need a layer-class override so we can
/// reach the player layer directly via `view.playerLayer`.
final class PlayerContainerView: UIView {
    override static var layerClass: AnyClass { AVPlayerLayer.self }

    /// Force-cast is safe given the `layerClass` override above.
    var playerLayer: AVPlayerLayer {
        // swiftlint:disable:next force_cast
        layer as! AVPlayerLayer
    }
}
