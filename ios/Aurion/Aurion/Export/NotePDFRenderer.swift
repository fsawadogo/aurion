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
        // CRITICAL: UIGraphicsEndPDFContext writes the PDF trailer +
        // xref table. Until it runs, `pdfData` holds only the PDF
        // header (~53 bytes). A naïve `defer { End() }` would run
        // AFTER the `return pdfData as Data` expression is evaluated,
        // and the `as Data` conversion COPIES the bytes — so the
        // returned Data captures the pre-trailer header-only snapshot
        // and downstream readers (Adobe, Preview, etc.) reject the
        // file as corrupt. End() must run BEFORE the return.
        // We still need the error-path guarantee that End() is called
        // on any throw — wrap the drawing loop in do/catch.
        do {
            try _drawPaginatedSlices(
                cgImage: cgImage,
                renderedWidth: renderedWidth,
                renderedHeight: renderedHeight,
                printableHeight: printableHeight,
                renderer: renderer
            )
        } catch {
            UIGraphicsEndPDFContext()
            throw error
        }
        UIGraphicsEndPDFContext()
        return pdfData as Data
    }

    /// Pagination loop extracted so `render()` can wrap it in a
    /// do/catch around the PDF context lifecycle. Assumes a PDF
    /// context is already open via `UIGraphicsBeginPDFContextToData`.
    @MainActor
    private static func _drawPaginatedSlices(
        cgImage: CGImage,
        renderedWidth: CGFloat,
        renderedHeight: CGFloat,
        printableHeight: CGFloat,
        renderer: ImageRenderer<some View>
    ) throws {
        let scale = renderer.scale
        // Precompute which pixel rows are entirely page background (white).
        // Page breaks are then backed off onto these gaps so no line of text —
        // or a navy SOAP band — is ever bisected across two pages.
        let backgroundRow = _backgroundRows(cgImage)

        var yOffsetInRendered: CGFloat = 0
        while yOffsetInRendered < renderedHeight {
            UIGraphicsBeginPDFPage()
            guard let ctx = UIGraphicsGetCurrentContext() else {
                throw NotePDFRendererError.pdfContextUnavailable
            }

            var sliceHeight = min(printableHeight, renderedHeight - yOffsetInRendered)
            // Not the last page → shrink the slice up to the nearest blank gap
            // so the page break lands between lines, not through one.
            if renderedHeight - yOffsetInRendered > printableHeight + 0.5,
               let gapHeight = _backoffToGap(
                   backgroundRow: backgroundRow,
                   scale: scale,
                   startPoints: yOffsetInRendered,
                   idealHeightPoints: sliceHeight,
                   maxBackoffPoints: 150,
                   minHeightPoints: 240
               ) {
                sliceHeight = gapHeight
            }
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
    }

    /// For every pixel row of `image` (top-left origin), whether that row is
    /// entirely page background (white). Used to choose page breaks that fall
    /// in the blank gaps between content rather than through a line or band.
    private static func _backgroundRows(_ image: CGImage) -> [Bool] {
        let width = image.width
        let height = image.height
        guard width > 0, height > 0 else { return [] }
        let bytesPerRow = width * 4
        var data = [UInt8](repeating: 0, count: bytesPerRow * height)
        let space = CGColorSpaceCreateDeviceRGB()
        let drawn: Bool = data.withUnsafeMutableBytes { raw -> Bool in
            guard let base = raw.baseAddress,
                  let ctx = CGContext(
                      data: base, width: width, height: height,
                      bitsPerComponent: 8, bytesPerRow: bytesPerRow,
                      space: space,
                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                  ) else { return false }
            ctx.draw(image, in: CGRect(x: 0, y: 0, width: width, height: height))
            return true
        }
        guard drawn else { return [] }
        // CGContext is bottom-up: buffer row r maps to image-top row height-1-r.
        var bgTop = [Bool](repeating: false, count: height)
        let step = max(1, width / 320) * 4  // sample ~320 columns; *4 bytes/px
        for r in 0..<height {
            let rowStart = r * bytesPerRow
            let rowEnd = rowStart + bytesPerRow
            var isBackground = true
            var p = rowStart
            while p + 2 < rowEnd {
                // R, G, B near 255 = white background (alpha ignored).
                if data[p] < 248 || data[p + 1] < 248 || data[p + 2] < 248 {
                    isBackground = false
                    break
                }
                p += step
            }
            bgTop[height - 1 - r] = isBackground
        }
        return bgTop
    }

    /// The largest slice height (points) ≤ the ideal that still ends on a
    /// background row, searching downward up to `maxBackoffPoints`. Returns
    /// nil when no gap is found in the window (caller keeps the hard cut — a
    /// single unbroken block taller than a page, which shouldn't occur for
    /// clinical prose).
    private static func _backoffToGap(
        backgroundRow: [Bool],
        scale: CGFloat,
        startPoints: CGFloat,
        idealHeightPoints: CGFloat,
        maxBackoffPoints: CGFloat,
        minHeightPoints: CGFloat
    ) -> CGFloat? {
        guard !backgroundRow.isEmpty else { return nil }
        let candidate = Int(((startPoints + idealHeightPoints) * scale).rounded())
        let floorHeight = max(minHeightPoints, idealHeightPoints - maxBackoffPoints)
        let lowest = max(1, Int(((startPoints + floorHeight) * scale).rounded()))
        var y = min(candidate, backgroundRow.count - 1)
        while y >= lowest {
            if backgroundRow[y] {
                return CGFloat(y) / scale - startPoints
            }
            y -= 1
        }
        return nil
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
