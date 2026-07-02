import AVFoundation
import SwiftUI
import UIKit

/// SwiftUI host for the Ray-Ban Meta glasses POV preview (#443).
///
/// The iPhone camera preview uses an `AVCaptureVideoPreviewLayer` bound to its
/// AVCaptureSession (`CameraPreviewLayer`). The glasses have no AVCaptureSession
/// — they deliver `CMSampleBuffer`s over MWDAT — so `MetaWearablesSource`
/// enqueues those frames into an `AVSampleBufferDisplayLayer`, and this view
/// hosts that layer. Without it the physician sees a blank recording screen and
/// can't tell what the glasses are pointed at.
struct MetaPreviewView: UIViewRepresentable {
    let displayLayer: AVSampleBufferDisplayLayer

    func makeUIView(context: Context) -> PreviewUIView {
        let view = PreviewUIView()
        view.attach(displayLayer)
        return view
    }

    func updateUIView(_ uiView: PreviewUIView, context: Context) {
        uiView.attach(displayLayer)
    }

    static func dismantleUIView(_ uiView: PreviewUIView, coordinator: ()) {
        uiView.detach()
    }

    final class PreviewUIView: UIView {
        private weak var attached: AVSampleBufferDisplayLayer?

        func attach(_ newLayer: AVSampleBufferDisplayLayer) {
            guard attached !== newLayer else { return }
            attached?.removeFromSuperlayer()
            newLayer.videoGravity = .resizeAspectFill
            newLayer.frame = bounds
            layer.addSublayer(newLayer)
            attached = newLayer
        }

        func detach() {
            attached?.removeFromSuperlayer()
            attached = nil
        }

        override func layoutSubviews() {
            super.layoutSubviews()
            attached?.frame = bounds
        }
    }
}

/// Status-aware wrapper for the glasses preview. The raw `MetaPreviewView`
/// renders an empty (black) layer when the MWDAT stream never started — e.g.
/// glasses not connected in the Meta AI app — leaving the physician staring at
/// a black screen with no explanation while audio records. This wrapper
/// observes the source: POV preview while streaming, otherwise a fixed-light
/// explanatory placeholder (why video is missing + that audio continues).
struct MetaPreviewOrStatus: View {
    @ObservedObject var source: MetaWearablesSource

    var body: some View {
        if source.isReadyForPreview {
            MetaPreviewView(displayLayer: source.previewLayer)
        } else {
            // Over the capture screen's black backdrop — fixed-light styling,
            // matching the immersive layout's over-camera chrome.
            VStack(spacing: 12) {
                Image(systemName: "eyeglasses")
                    .font(.system(size: 42, weight: .light))
                    .foregroundColor(.white.opacity(0.55))
                Text(L("capture.meta.noVideoTitle"))
                    .aurionFont(17, weight: .semibold, relativeTo: .headline)
                    .foregroundColor(.white)
                if !source.detail.isEmpty {
                    Text(source.detail)
                        .aurionFont(13, relativeTo: .footnote)
                        .foregroundColor(.white.opacity(0.7))
                        .multilineTextAlignment(.center)
                        .fixedSize(horizontal: false, vertical: true)
                }
                Text(L("capture.meta.audioOnly"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionGold)
                    .multilineTextAlignment(.center)
            }
            .padding(.horizontal, 32)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
    }
}
