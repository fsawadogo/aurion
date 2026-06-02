import SwiftUI

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

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

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
            }
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
