import SwiftUI
import AVFoundation
import UIKit

/// Live camera preview for the capture screen. Wraps an
/// `AVCaptureVideoPreviewLayer` attached to the same `AVCaptureSession` that
/// the rest of the capture pipeline (audio output, frame extraction) uses —
/// no second session, no second mic claim. Mirroring the existing pipeline
/// also means the preview reflects exactly what the Stage 2 vision provider
/// will see (same camera, same orientation, same masking applied later).
///
/// Important lifecycle note: when SwiftUI tears this view down (eye toggle,
/// app backgrounded, scene removed), `dismantleUIView` runs on the main
/// thread BEFORE the layer is released. We detach the session there so the
/// preview layer's render pipeline stops touching the still-running capture
/// session's buffers — avoids EXC_BAD_ACCESS on the AVFoundation render
/// thread when the layer dealloc would otherwise race with mid-frame work.
struct CameraPreviewLayer: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> PreviewUIView {
        let view = PreviewUIView()
        view.previewLayer.session = session
        // Aspect-fill so the preview rectangle is fully painted regardless of
        // camera resolution. The Stage 2 frame extractor uses the same buffer
        // so this is purely a visual decision for the physician.
        view.previewLayer.videoGravity = .resizeAspectFill
        return view
    }

    func updateUIView(_ uiView: PreviewUIView, context: Context) {
        if uiView.previewLayer.session !== session {
            uiView.previewLayer.session = session
        }
    }

    static func dismantleUIView(_ uiView: PreviewUIView, coordinator: ()) {
        // Detach BEFORE the layer dealloc cascade. The capture session keeps
        // running (frame extractor still feeds Stage 2); only the preview
        // tap is removed. Doing this on the main thread is safe — Apple
        // explicitly allows `previewLayer.session = nil` from any thread.
        uiView.previewLayer.session = nil
    }

    final class PreviewUIView: UIView {
        override class var layerClass: AnyClass { AVCaptureVideoPreviewLayer.self }
        var previewLayer: AVCaptureVideoPreviewLayer {
            // Force-cast is safe: layerClass guarantees the type.
            layer as! AVCaptureVideoPreviewLayer
        }
    }
}
