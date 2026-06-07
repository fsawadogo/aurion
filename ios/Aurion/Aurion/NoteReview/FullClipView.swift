import SwiftUI
import AVFoundation

/// Photo-viewer-style presentation of a single clip-kind citation.
/// Mirrors `FullFrameView` in `Capture/FrameGalleryView.swift` so the
/// reviewer's clip-vs-frame experience is interchangeable from the
/// physician's perspective — same dark chrome, same toolbar layout,
/// same close affordance — only the content surface differs
/// (`AurionVideoPlayer` vs. a static `Image`).
///
/// The Liskov contract: a reviewer tapping any citation chip sees a
/// modal with a black background, a centred monospaced timestamp in
/// the toolbar, and a gold "Close" trailing button. The body inside
/// is the artifact that's being reviewed (image or clip). Nothing
/// else changes.
///
/// ## Inputs
///
/// - `clipURL`: a local file URL (cached masked MP4 produced by
///   `MaskingPipeline.maskClip` in P1-5) OR a backend-signed remote
///   URL once the note endpoint plumbs that field through.
///   `AVPlayer` handles both transparently.
/// - `durationMs`: the encoded window length, surfaced as a duration
///   pill alongside the timestamp so the physician sees "this is a
///   7s clip from 4:33".
/// - `timestamp`: relative session time of the trigger anchor, in
///   seconds. Same display format as `FullFrameView`.
struct FullClipView: View {
    let clipURL: URL
    let durationMs: Int
    let timestamp: TimeInterval
    @Environment(\.dismiss) private var dismiss

    /// Readiness of the clip asset. `AurionVideoPlayer` owns its own
    /// `AVPlayer` and exposes no status, so we probe playability on a
    /// parallel `AVURLAsset` to gate loading → ready → failed. This covers
    /// the common failure modes — missing local file, corrupt MP4, or a
    /// slow/unreachable signed remote URL — instead of leaving a black frame.
    private enum ClipLoadState: Equatable {
        case loading
        case ready
        case failed
    }
    @State private var loadState: ClipLoadState = .loading

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                switch loadState {
                case .ready:
                    AurionVideoPlayer(url: clipURL)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .transition(.opacity)
                        .accessibilityLabel(L("clip.viewer.accessibility"))

                    VStack {
                        Spacer()
                        if durationMs > 0 {
                            durationPill
                                .padding(.bottom, 24)
                        }
                    }
                case .loading:
                    loadingOverlay
                case .failed:
                    unavailableOverlay
                }
            }
            .animation(AurionAnimation.smooth, value: loadState)
            .task(id: clipURL) { await loadClip() }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text(formatTimestamp(timestamp))
                        .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                        .monospacedDigit()
                        .foregroundColor(.white)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L("common.close")) { dismiss() }
                        .foregroundColor(.aurionGold)
                }
            }
            // Same dark-chrome treatment as FullFrameView so the two
            // viewers feel like one component family.
            .toolbarBackground(Color.black, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
        .navigationViewStyle(.stack)
    }

    // MARK: - Loading / failure surfaces

    /// Spinner over the black background while the clip readies. Keeps the
    /// chrome identical to the playing state so the transition is just the
    /// spinner fading out as the video fades in.
    private var loadingOverlay: some View {
        VStack(spacing: 14) {
            ProgressView()
                .tint(.white)
                .scaleEffect(1.2)
            Text(L("clip.loading"))
                .aurionFont(13, weight: .medium, relativeTo: .footnote)
                .foregroundColor(.white.opacity(0.7))
        }
        .transition(.opacity)
    }

    /// Inline failure surface — a warning glyph, an explanation, and a
    /// secondary Close so the physician can leave without hunting for the
    /// toolbar button. The toolbar Close stays available too.
    private var unavailableOverlay: some View {
        VStack(spacing: 14) {
            Image(systemName: "exclamationmark.triangle")
                .font(.system(size: 40, weight: .light))
                .foregroundColor(.white.opacity(0.6))
            Text(L("clip.unavailable"))
                .aurionFont(15, weight: .semibold, relativeTo: .subheadline)
                .foregroundColor(.white)
                .multilineTextAlignment(.center)
            Button(L("common.close")) {
                AurionHaptics.selection()
                dismiss()
            }
            .aurionFont(15, weight: .semibold, relativeTo: .body)
            .foregroundColor(.aurionGold)
            .padding(.top, 4)
        }
        .padding(40)
        .transition(.opacity)
    }

    /// Probe playability on a parallel asset (iOS 16 async loader). Local
    /// files resolve near-instantly; remote signed URLs surface the spinner
    /// until the asset responds, and any error/non-playable result flips to
    /// the failure surface rather than leaving a black frame.
    private func loadClip() async {
        loadState = .loading
        let asset = AVURLAsset(url: clipURL)
        do {
            let playable = try await asset.load(.isPlayable)
            loadState = playable ? .ready : .failed
        } catch {
            loadState = .failed
        }
    }

    /// Floating duration pill anchored bottom-centre. Distinct from
    /// the timestamp principal so the physician sees both "when this
    /// happened in the session" (toolbar) and "how long the clip
    /// runs" (pill).
    private var durationPill: some View {
        Text(formatDuration(durationMs))
            .aurionFont(12, weight: .semibold, relativeTo: .caption)
            .monospacedDigit()
            .foregroundColor(.white)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(.ultraThinMaterial)
            .clipShape(Capsule())
    }

    /// Session-relative timestamp in MM:SS. Lifted verbatim from
    /// `FullFrameView.formatTimestamp` so the two viewers display the
    /// same anchor in the same format.
    private func formatTimestamp(_ seconds: TimeInterval) -> String {
        let totalSec = Int(seconds)
        let mm = totalSec / 60
        let ss = totalSec % 60
        return String(format: "%d:%02d", mm, ss)
    }

    /// Clip duration in compact "7.0s" format. Milliseconds resolution
    /// is too noisy for the user-facing label; round to one decimal.
    private func formatDuration(_ ms: Int) -> String {
        let seconds = Double(ms) / 1000.0
        return String(format: "%.1fs", seconds)
    }
}
