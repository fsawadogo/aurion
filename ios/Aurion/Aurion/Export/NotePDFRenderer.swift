import SwiftUI
import UIKit
import PDFKit

/// On-device PDF renderer for a clinical note.
///
/// Uses SwiftUI's `ImageRenderer` (iOS 16+) to capture the same
/// ``NoteDocumentBody`` view the user sees on screen, then paginates the
/// captured CGImage onto US-Letter PDF pages with `UIGraphicsPDFRenderer`.
///
/// Sharing the SwiftUI view between screen and print means there's exactly
/// one source of truth for the note layout — typography, spacing, and
/// section ordering can't drift between what the physician sees and what
/// the PDF ships.
///
/// The renderer is fully synchronous on the main thread but completes in
/// well under 200ms for typical SOAP notes (6 sections, ~12 claims),
/// because ImageRenderer rasterises only the visible bounding box. Callers
/// should run it inside a `Task { @MainActor in ... }` so the SwiftUI
/// environment is wired.
enum NotePDFRenderer {

    /// US Letter portrait — matches what Pages / Word default to so the
    /// PDF prints cleanly without scaling.
    private static let pageSize = CGSize(width: 612, height: 792)
    /// 36pt (0.5") page margin all around — standard letterhead inset.
    private static let pageMargin: CGFloat = 36
    /// Vertical space below the title header on page 1 only.
    private static let titleBlockExtraTopPad: CGFloat = 0

    /// Returns PDF bytes for the supplied note. Throws on rendering failure.
    @MainActor
    static func render(
        note: NoteResponse,
        specialtyTitle: String,
        dateString: String
    ) throws -> Data {
        // Build the SwiftUI document the same way SessionNoteView does,
        // pinned to the page's content width so ImageRenderer lays it
        // out for print rather than screen.
        let contentWidth = pageSize.width - pageMargin * 2
        let document = NoteDocumentBody(
            note: note,
            specialtyTitle: specialtyTitle,
            dateString: dateString,
            forPDF: true
        )
        .frame(width: contentWidth, alignment: .topLeading)

        let renderer = ImageRenderer(content: document)
        // 2x scale so the captured raster reads sharp on Retina displays
        // and prints crisp at 144dpi (effective).
        renderer.scale = 2
        renderer.proposedSize = .init(width: contentWidth, height: nil)

        guard let cgImage = renderer.cgImage else {
            throw NotePDFRendererError.rasterisationFailed
        }
        let renderedHeight = CGFloat(cgImage.height) / renderer.scale
        let renderedWidth = CGFloat(cgImage.width) / renderer.scale

        // Paginate: slice the tall captured image into page-height
        // chunks and draw each onto its own PDF page.
        let printableHeight = pageSize.height - pageMargin * 2
        let pdfData = NSMutableData()
        UIGraphicsBeginPDFContextToData(pdfData, .init(origin: .zero, size: pageSize), nil)
        defer { UIGraphicsEndPDFContext() }

        var yOffsetInRendered: CGFloat = 0
        while yOffsetInRendered < renderedHeight {
            UIGraphicsBeginPDFPage()
            guard let ctx = UIGraphicsGetCurrentContext() else {
                throw NotePDFRendererError.pdfContextUnavailable
            }

            let sliceHeight = min(printableHeight, renderedHeight - yOffsetInRendered)
            // Pull the corresponding strip out of the source CGImage.
            // Coordinates here are pixel-space (cgImage uses pixels, not
            // points), so multiply by scale.
            let cropRect = CGRect(
                x: 0,
                y: yOffsetInRendered * renderer.scale,
                width: renderedWidth * renderer.scale,
                height: sliceHeight * renderer.scale
            )
            guard let slice = cgImage.cropping(to: cropRect) else {
                throw NotePDFRendererError.croppingFailed
            }

            // CGContext draws bottom-up by default; flip so the slice
            // lands right-side up at the top of the page.
            let drawRect = CGRect(
                x: pageMargin,
                y: pageMargin,
                width: renderedWidth,
                height: sliceHeight
            )
            ctx.saveGState()
            ctx.translateBy(x: 0, y: pageSize.height)
            ctx.scaleBy(x: 1, y: -1)
            let flippedRect = CGRect(
                x: drawRect.minX,
                y: pageSize.height - drawRect.maxY,
                width: drawRect.width,
                height: drawRect.height
            )
            ctx.draw(slice, in: flippedRect)
            ctx.restoreGState()

            yOffsetInRendered += sliceHeight
        }

        return pdfData as Data
    }
}

enum NotePDFRendererError: LocalizedError {
    case rasterisationFailed
    case pdfContextUnavailable
    case croppingFailed

    var errorDescription: String? {
        switch self {
        case .rasterisationFailed:
            return "Could not rasterise the note for PDF."
        case .pdfContextUnavailable:
            return "PDF graphics context unavailable."
        case .croppingFailed:
            return "Could not crop the note raster for pagination."
        }
    }
}
