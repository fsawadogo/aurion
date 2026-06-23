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
