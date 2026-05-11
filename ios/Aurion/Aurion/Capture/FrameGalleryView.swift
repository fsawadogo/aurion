import SwiftUI

/// Live gallery of frames captured during the current session. Mounted as a
/// sheet from CaptureView so the physician can verify framing + privacy
/// masking *while* recording — a strong UX signal that the system isn't a
/// black box. Updates in real time as new frames arrive (1 fps default per
/// AppConfig.pipeline.video_capture_fps).
///
/// Privacy: thumbnails are rendered from the same JPEGs the capture
/// pipeline buffered locally. None of these images have been uploaded yet —
/// upload happens post-stop via `SessionManager.submitFrames()`. Showing
/// them here pre-upload is a deliberate transparency choice, not a leak.
struct FrameGalleryView: View {
    @ObservedObject var source: BuiltInCaptureSource
    @Environment(\.dismiss) private var dismiss
    @State private var selectedFrame: CapturedFrame?

    // 3-column grid is the right density on iPhone — bigger than a
    // contact-sheet thumbnail, small enough to see most of the session in
    // one scroll.
    private let columns: [GridItem] = [
        GridItem(.flexible(), spacing: 8),
        GridItem(.flexible(), spacing: 8),
        GridItem(.flexible(), spacing: 8),
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                Color.aurionBackground.ignoresSafeArea()

                if source.capturedFrames.isEmpty {
                    emptyState
                } else {
                    ScrollView {
                        LazyVGrid(columns: columns, spacing: 8) {
                            ForEach(source.capturedFrames.reversed()) { frame in
                                Button {
                                    AurionHaptics.selection()
                                    selectedFrame = frame
                                } label: {
                                    frameThumbnail(frame)
                                }
                                .buttonStyle(.plain)
                                .transition(
                                    .scale(scale: 0.85)
                                        .combined(with: .opacity)
                                )
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.top, 12)
                        .padding(.bottom, 32)
                    }
                    .animation(AurionAnimation.smooth, value: source.capturedFrames.count)
                }
            }
            .navigationTitle("Captured Frames")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Text(frameCountLabel)
                        .font(.system(size: 13, weight: .medium))
                        .foregroundColor(.aurionTextSecondary)
                        .contentTransition(.numericText())
                        .animation(AurionAnimation.smooth, value: source.capturedFrames.count)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        AurionHaptics.selection()
                        dismiss()
                    }
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(.aurionGold)
                }
            }
            .sheet(item: $selectedFrame) { frame in
                FullFrameView(frame: frame)
            }
        }
    }

    private var frameCountLabel: String {
        let count = source.capturedFrames.count
        return "\(count) frame\(count == 1 ? "" : "s")"
    }

    @ViewBuilder
    private func frameThumbnail(_ frame: CapturedFrame) -> some View {
        ZStack(alignment: .bottomLeading) {
            if let uiImage = UIImage(data: frame.imageData) {
                Image(uiImage: uiImage)
                    .resizable()
                    .aspectRatio(contentMode: .fill)
                    .frame(maxWidth: .infinity)
                    .aspectRatio(3.0 / 4.0, contentMode: .fit)
                    .clipped()
            } else {
                Rectangle()
                    .fill(Color.aurionCardBackground)
                    .aspectRatio(3.0 / 4.0, contentMode: .fit)
            }

            // Timestamp pill — bottom-left over the image for context
            Text(formatTimestamp(frame.timestamp))
                .font(.system(size: 10, weight: .semibold))
                .monospacedDigit()
                .foregroundColor(.white)
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
                .background(.ultraThinMaterial)
                .clipShape(Capsule())
                .padding(6)
        }
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.aurionGold.opacity(0.25), lineWidth: 1)
        )
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "photo.stack")
                .font(.system(size: 48, weight: .light))
                .foregroundColor(.aurionTextSecondary.opacity(0.6))
                .symbolEffect(.pulse, options: .repeating)
            Text("No frames yet")
                .font(.system(size: 18, weight: .semibold))
                .foregroundColor(.aurionNavy)
            Text("Frames appear here as they're captured.\nDefault rate is 1 per second.")
                .font(.system(size: 13))
                .foregroundColor(.aurionTextSecondary)
                .multilineTextAlignment(.center)
        }
        .padding(.horizontal, 40)
    }

    private func formatTimestamp(_ seconds: TimeInterval) -> String {
        let totalSec = Int(seconds)
        let mm = totalSec / 60
        let ss = totalSec % 60
        return String(format: "%d:%02d", mm, ss)
    }
}

// MARK: - Full Frame View

/// Tap-to-expand presentation of a single captured frame. No edit / delete
/// affordances — the physician's role here is to verify, not curate.
private struct FullFrameView: View {
    let frame: CapturedFrame
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                if let uiImage = UIImage(data: frame.imageData) {
                    Image(uiImage: uiImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .transition(.scale(scale: 0.95).combined(with: .opacity))
                }
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text(formatTimestamp(frame.timestamp))
                        .font(.system(size: 14, weight: .semibold))
                        .monospacedDigit()
                        .foregroundColor(.white)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Close") { dismiss() }
                        .foregroundColor(.aurionGold)
                }
            }
            .toolbarBackground(Color.black, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }

    private func formatTimestamp(_ seconds: TimeInterval) -> String {
        let totalSec = Int(seconds)
        let mm = totalSec / 60
        let ss = totalSec % 60
        return String(format: "%d:%02d", mm, ss)
    }
}
