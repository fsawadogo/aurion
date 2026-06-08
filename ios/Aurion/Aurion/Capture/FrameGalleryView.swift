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
                                .accessibilityElement(children: .ignore)
                                .accessibilityLabel(
                                    L("frames.a11yFrame", formatTimestamp(frame.timestamp))
                                )
                                .accessibilityValue(maskingA11yValue(frame.maskingStatus))
                                .accessibilityHint(L("frames.a11yFrameHint"))
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
            .navigationTitle(L("frames.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Text(frameCountLabel)
                        .aurionFont(13, weight: .medium, relativeTo: .footnote)
                        .foregroundColor(.aurionTextSecondary)
                        .contentTransition(.numericText())
                        .animation(AurionAnimation.smooth, value: source.capturedFrames.count)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L("common.done")) {
                        AurionHaptics.selection()
                        dismiss()
                    }
                    .aurionFont(16, weight: .semibold, relativeTo: .body)
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
        return Lplural("frames.count", count)
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
                // Decode failure (corrupt/empty JPEG) — surface a warning
                // glyph + label so it reads as "this frame couldn't load",
                // not as a blank/black tile that looks like a capture gap.
                ZStack {
                    Rectangle()
                        .fill(Color.aurionCardBackground)
                        .aspectRatio(3.0 / 4.0, contentMode: .fit)
                    VStack(spacing: 6) {
                        Image(systemName: "exclamationmark.triangle")
                            .font(.system(size: 22, weight: .regular))
                            .foregroundColor(.aurionMutedGray)
                        Text(L("frames.decodeFailed"))
                            .aurionFont(11, weight: .medium, relativeTo: .caption2)
                            .foregroundColor(.aurionMutedGray)
                            .multilineTextAlignment(.center)
                    }
                    .padding(8)
                }
            }

            // Timestamp pill — bottom-left over the image for context.
            // Decorative: the timestamp is already spoken via the button's
            // accessibilityLabel, so hide it from VoiceOver here.
            Text(formatTimestamp(frame.timestamp))
                .aurionFont(10, weight: .semibold, relativeTo: .caption2)
                .monospacedDigit()
                .foregroundColor(.white)
                .padding(.horizontal, 6)
                .padding(.vertical, 3)
                .background(.ultraThinMaterial)
                .clipShape(Capsule())
                .padding(6)
                .accessibilityHidden(true)
        }
        // Masking-status badge — top-trailing over the image. Decorative:
        // the status is already announced via the button's accessibilityValue,
        // so hide the visual pill from VoiceOver here.
        .overlay(alignment: .topTrailing) {
            maskingBadge(frame.maskingStatus)
                .padding(6)
                .accessibilityHidden(true)
        }
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.aurionGold.opacity(0.25), lineWidth: 1)
        )
    }

    /// Pill badge surfacing a frame's privacy-masking state — green "Masked"
    /// when `MaskingPipeline` has confirmed the frame, amber "Pending"
    /// otherwise. The view's whole purpose is to let the physician verify
    /// framing + masking, so we make the masking state explicit rather than
    /// implied.
    @ViewBuilder
    private func maskingBadge(_ status: FrameMaskingStatus) -> some View {
        let masked = status == .masked
        HStack(spacing: 3) {
            Image(systemName: masked ? "checkmark.shield.fill" : "clock.fill")
                .font(.system(size: 9, weight: .bold))
            Text(masked ? L("frames.maskingMasked") : L("frames.maskingPending"))
                .aurionFont(9, weight: .bold, relativeTo: .caption2)
        }
        .foregroundColor(masked ? .aurionGreen : .aurionAmber)
        .padding(.horizontal, 6)
        .padding(.vertical, 3)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
    }

    /// VoiceOver value describing a frame's masking state, attached to the
    /// thumbnail button so the badge isn't lost to non-visual users.
    private func maskingA11yValue(_ status: FrameMaskingStatus) -> String {
        status == .masked
            ? L("frames.maskingMaskedA11y")
            : L("frames.maskingPendingA11y")
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "photo.stack")
                .font(.system(size: 48, weight: .light))
                .foregroundColor(.aurionTextSecondary.opacity(0.6))
                .symbolEffect(.pulse, options: .repeating)
            Text(L("frames.empty"))
                .aurionFont(18, weight: .semibold, relativeTo: .title3)
                .foregroundColor(.aurionTextPrimary)
            Text(L("frames.emptySub"))
                .aurionFont(13, relativeTo: .footnote)
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
/// Supports pinch-to-zoom (1×–5×) with drag-to-pan and double-tap reset so
/// the physician can inspect framing + masking detail up close.
private struct FullFrameView: View {
    let frame: CapturedFrame
    @Environment(\.dismiss) private var dismiss

    // Zoom + pan state. `last*` hold the committed value between gestures so
    // a new pinch/drag continues from where the previous one ended.
    @State private var scale: CGFloat = 1
    @State private var lastScale: CGFloat = 1
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero

    private let minScale: CGFloat = 1
    private let maxScale: CGFloat = 5

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                if let uiImage = UIImage(data: frame.imageData) {
                    Image(uiImage: uiImage)
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .scaleEffect(scale)
                        .offset(offset)
                        .gesture(magnification)
                        .simultaneousGesture(pan)
                        .onTapGesture(count: 2) { toggleZoom() }
                        .accessibilityHint(L("frames.zoomHint"))
                        .transition(.scale(scale: 0.95).combined(with: .opacity))
                }

                // Masking-status badge — top-leading over the image, mirroring
                // the gallery thumbnail's pill so the verification signal
                // carries into the full view.
                maskingBadge(frame.maskingStatus)
                    .padding(16)
                    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
                    .allowsHitTesting(false)
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .principal) {
                    Text(formatTimestamp(frame.timestamp))
                        .aurionFont(14, weight: .semibold, relativeTo: .subheadline)
                        .monospacedDigit()
                        .foregroundColor(.white)
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(L("common.close")) { dismiss() }
                        .foregroundColor(.aurionGold)
                }
            }
            .toolbarBackground(Color.black, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbarColorScheme(.dark, for: .navigationBar)
        }
    }

    // MARK: - Zoom gestures

    private var magnification: some Gesture {
        MagnificationGesture()
            .onChanged { value in
                scale = min(max(lastScale * value, minScale), maxScale)
            }
            .onEnded { _ in
                lastScale = scale
                if scale <= minScale {
                    withAnimation(AurionAnimation.smooth) { resetZoom() }
                }
            }
    }

    private var pan: some Gesture {
        DragGesture()
            .onChanged { value in
                // Panning only makes sense once zoomed in; below 1× the image
                // already fills its fitted bounds.
                guard scale > minScale else { return }
                offset = CGSize(
                    width: lastOffset.width + value.translation.width,
                    height: lastOffset.height + value.translation.height
                )
            }
            .onEnded { _ in lastOffset = offset }
    }

    private func toggleZoom() {
        AurionHaptics.selection()
        withAnimation(AurionAnimation.smooth) {
            if scale > minScale {
                resetZoom()
            } else {
                scale = 2.5
                lastScale = 2.5
            }
        }
    }

    private func resetZoom() {
        scale = minScale
        lastScale = minScale
        offset = .zero
        lastOffset = .zero
    }

    // MARK: - Masking badge

    @ViewBuilder
    private func maskingBadge(_ status: FrameMaskingStatus) -> some View {
        let masked = status == .masked
        HStack(spacing: 4) {
            Image(systemName: masked ? "checkmark.shield.fill" : "clock.fill")
                .font(.system(size: 11, weight: .bold))
            Text(masked ? L("frames.maskingMasked") : L("frames.maskingPending"))
                .aurionFont(11, weight: .bold, relativeTo: .caption2)
        }
        .foregroundColor(masked ? .aurionGreen : .aurionAmber)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(.ultraThinMaterial)
        .clipShape(Capsule())
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(masked
            ? L("frames.maskingMaskedA11y")
            : L("frames.maskingPendingA11y"))
    }

    private func formatTimestamp(_ seconds: TimeInterval) -> String {
        let totalSec = Int(seconds)
        let mm = totalSec / 60
        let ss = totalSec % 60
        return String(format: "%d:%02d", mm, ss)
    }
}
