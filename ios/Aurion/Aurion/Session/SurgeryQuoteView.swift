import SwiftUI
import UIKit

// MARK: - Surgery quote add-on (note-options phase 3)
//
// Generate a surgical cost quote from the approved note (the AI drafts the
// procedures discussed; it never sets a price), let the physician add/edit
// line items + type fees, then export a patient-facing PDF. Presented as a
// sheet from the note-screen Options → Add-ons menu.

struct SurgeryQuoteView: View {
    let sessionId: String
    /// Approved-note states — generation is server-refused (409) otherwise, so
    /// we gate the affordance instead of surfacing an error.
    let sessionState: String
    let onClose: () -> Void

    @State private var lineItems: [SurgeryQuoteLineItem] = []
    @State private var currency: String = "CAD"
    @State private var notes: String = ""
    @State private var loaded: SurgeryQuoteResponse?

    @State private var isLoading = true
    @State private var isGenerating = false
    @State private var isSaving = false
    @State private var error: String?

    @State private var exportURL: URL?
    @State private var showShareSheet = false

    private let currencies = ["CAD", "USD", "EUR", "GBP"]

    private var isApproved: Bool {
        ["REVIEW_COMPLETE", "EXPORTED", "PURGED"].contains(sessionState)
    }

    private var totalCents: Int {
        lineItems.compactMap(\.feeCents).reduce(0, +)
    }

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                } else if !isApproved && loaded == nil {
                    lockedState
                } else if loaded == nil && lineItems.isEmpty {
                    emptyState
                } else {
                    editor
                }
            }
            .background(Color.aurionBackground.ignoresSafeArea())
            .navigationTitle(L("quote.title"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(L("common.close"), action: onClose)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if loaded != nil || !lineItems.isEmpty {
                        Button(L("quote.save")) { Task { await save() } }
                            .disabled(isSaving || !canSave)
                    }
                }
            }
            .task { await load() }
            .sheet(isPresented: $showShareSheet) {
                if let exportURL { ShareSheet(items: [exportURL]) }
            }
            .alert(
                L("quote.failedShort"),
                isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } }),
                presenting: error
            ) { _ in
                Button(L("common.ok"), role: .cancel) { error = nil }
            } message: { Text($0) }
            .overlay {
                if isGenerating || isSaving {
                    ZStack {
                        Color.black.opacity(0.06).ignoresSafeArea()
                        ProgressView(isGenerating ? L("quote.generating") : L("quote.saving"))
                            .padding(AurionSpacing.xl)
                            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: AurionRadius.md))
                    }
                }
            }
        }
    }

    // MARK: - States

    private var lockedState: some View {
        EmptyStateView(
            icon: "lock.fill",
            title: L("quote.lockedTitle"),
            subtitle: L("quote.lockedSub")
        )
        .padding(AurionSpacing.xl)
    }

    private var emptyState: some View {
        VStack(spacing: AurionSpacing.xl) {
            Spacer()
            AurionIconBubble(symbol: "doc.text.magnifyingglass", tint: .aurionGold, size: 90, symbolWeight: .light)
            VStack(spacing: AurionSpacing.sm) {
                Text(L("quote.emptyTitle")).aurionTitle()
                Text(L("quote.emptySub"))
                    .aurionFont(15, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .multilineTextAlignment(.center)
                    .fixedSize(horizontal: false, vertical: true)
                    .padding(.horizontal, AurionSpacing.xl)
            }
            Button(L("quote.generate")) { Task { await generate() } }
                .buttonStyle(AurionPrimaryButtonStyle())
                .padding(.horizontal, AurionSpacing.xl)
            Spacer()
        }
    }

    private var editor: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: AurionSpacing.lg) {
                Text(L("quote.editorHint"))
                    .aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
                    .fixedSize(horizontal: false, vertical: true)

                ForEach($lineItems) { $item in
                    lineItemCard($item)
                }

                Button {
                    withAnimation(.aurionIOS) {
                        lineItems.append(
                            SurgeryQuoteLineItem(
                                id: "li_" + UUID().uuidString.prefix(8).lowercased(),
                                procedure: "", detail: "", feeCents: nil
                            )
                        )
                    }
                } label: {
                    Label(L("quote.addLine"), systemImage: "plus.circle.fill")
                        .foregroundColor(.aurionGold)
                }
                .buttonStyle(.plain)

                Divider().overlay(Color.aurionBorder)

                // Currency + total
                HStack {
                    Text(L("quote.currency")).aurionFont(14, weight: .medium, relativeTo: .subheadline)
                    Spacer()
                    Picker(L("quote.currency"), selection: $currency) {
                        ForEach(currencies, id: \.self) { Text($0).tag($0) }
                    }
                    .pickerStyle(.menu)
                    .tint(.aurionGold)
                }
                HStack {
                    Text(L("quote.total")).aurionFont(16, weight: .bold, relativeTo: .body)
                    Spacer()
                    Text(Self.formatMoney(cents: totalCents, currency: currency))
                        .aurionFont(16, weight: .bold, relativeTo: .body)
                        .foregroundColor(.aurionNavy)
                }

                VStack(alignment: .leading, spacing: AurionSpacing.xs) {
                    Text(L("quote.notes")).aurionFont(13, weight: .medium, relativeTo: .footnote)
                        .foregroundColor(.aurionTextSecondary)
                    TextEditor(text: $notes)
                        .aurionFont(15, relativeTo: .subheadline)
                        .frame(minHeight: 70)
                        .scrollContentBackground(.hidden)
                        .padding(6)
                        .background(Color.aurionFieldBackground)
                        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
                }

                Button {
                    exportPDF()
                } label: {
                    Label(L("quote.exportPDF"), systemImage: "square.and.arrow.up")
                }
                .buttonStyle(AurionPrimaryButtonStyle())
                .disabled(lineItems.allSatisfy { $0.procedure.trimmingCharacters(in: .whitespaces).isEmpty })
                .padding(.top, AurionSpacing.sm)

                Button(L("quote.regenerate")) { Task { await generate() } }
                    .aurionFont(14, relativeTo: .subheadline)
                    .foregroundColor(.aurionTextSecondary)
                    .frame(maxWidth: .infinity)
            }
            .padding(AurionSpacing.xl)
            .frame(maxWidth: 720)
            .frame(maxWidth: .infinity)
        }
    }

    private func lineItemCard(_ item: Binding<SurgeryQuoteLineItem>) -> some View {
        VStack(alignment: .leading, spacing: AurionSpacing.sm) {
            HStack {
                TextField(L("quote.procedure"), text: item.procedure)
                    .aurionFont(16, weight: .semibold, relativeTo: .body)
                Button {
                    withAnimation(.aurionIOS) {
                        lineItems.removeAll { $0.id == item.wrappedValue.id }
                    }
                } label: {
                    Image(systemName: "trash")
                        .foregroundColor(.aurionTextSecondary)
                        .frame(minWidth: 36, minHeight: 36)
                }
                .buttonStyle(.plain)
                .accessibilityLabel(L("quote.removeLine"))
            }
            TextField(L("quote.description"), text: item.detail, axis: .vertical)
                .aurionFont(14, relativeTo: .subheadline)
                .foregroundColor(.aurionTextSecondary)
                .lineLimit(1...3)
            HStack {
                Text(L("quote.fee")).aurionFont(13, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
                Spacer()
                Text(currency).aurionFont(13, weight: .medium, relativeTo: .footnote)
                    .foregroundColor(.aurionTextSecondary)
                TextField(
                    "0.00",
                    text: Binding(
                        get: { Self.dollarsString(cents: item.wrappedValue.feeCents) },
                        set: { item.wrappedValue.feeCents = Self.centsFromDollars($0) }
                    )
                )
                .keyboardType(.decimalPad)
                .multilineTextAlignment(.trailing)
                .frame(width: 110)
                .aurionFont(16, weight: .semibold, relativeTo: .body)
            }
        }
        .padding(AurionSpacing.md)
        .background(Color.aurionCardBackground)
        .overlay(RoundedRectangle(cornerRadius: AurionRadius.md).stroke(Color.aurionBorder, lineWidth: 1))
        .clipShape(RoundedRectangle(cornerRadius: AurionRadius.md))
    }

    private var canSave: Bool {
        !lineItems.isEmpty
            && lineItems.allSatisfy { !$0.procedure.trimmingCharacters(in: .whitespaces).isEmpty }
    }

    // MARK: - Actions

    private func load() async {
        isLoading = true
        do {
            if let q = try await APIClient.shared.getSurgeryQuote(sessionId: sessionId) {
                apply(q)
            }
        } catch {
            self.error = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        isLoading = false
    }

    private func apply(_ q: SurgeryQuoteResponse) {
        loaded = q
        lineItems = q.lineItems
        currency = q.currency
        notes = q.notes ?? ""
    }

    private func generate() async {
        isGenerating = true
        error = nil
        do {
            let q = try await APIClient.shared.generateSurgeryQuote(sessionId: sessionId)
            withAnimation(.aurionIOS) { apply(q) }
            AurionHaptics.notification(.success)
        } catch {
            self.error = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        isGenerating = false
    }

    private func save() async {
        isSaving = true
        error = nil
        do {
            let q = try await APIClient.shared.editSurgeryQuote(
                sessionId: sessionId,
                lineItems: lineItems,
                currency: currency,
                notes: notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? nil : notes
            )
            apply(q)
            AurionHaptics.notification(.success)
        } catch {
            self.error = (error as? APIError)?.errorDescription ?? error.localizedDescription
        }
        isSaving = false
    }

    private func exportPDF() {
        do {
            let data = try SurgeryQuotePDFRenderer.render(
                lineItems: lineItems,
                currency: currency,
                notes: notes,
                dateString: Self.today()
            )
            let dir = FileManager.default.temporaryDirectory
            let url = dir.appendingPathComponent("aurion_quote_\(sessionId).pdf")
            try data.write(to: url, options: [.atomic])
            exportURL = url
            showShareSheet = true
            AurionHaptics.notification(.success)
        } catch {
            self.error = (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
        }
    }

    // MARK: - Money + date helpers

    static func centsFromDollars(_ s: String) -> Int? {
        let cleaned = s.replacingOccurrences(of: ",", with: "").trimmingCharacters(in: .whitespaces)
        if cleaned.isEmpty { return nil }
        guard let dollars = Double(cleaned), dollars >= 0 else { return nil }
        return Int((dollars * 100).rounded())
    }

    static func dollarsString(cents: Int?) -> String {
        guard let cents else { return "" }
        return String(format: "%.2f", Double(cents) / 100.0)
    }

    static func formatMoney(cents: Int, currency: String) -> String {
        let f = NumberFormatter()
        f.numberStyle = .currency
        f.currencyCode = currency
        return f.string(from: NSNumber(value: Double(cents) / 100.0)) ?? "\(currency) 0.00"
    }

    static func today() -> String {
        let f = DateFormatter()
        f.dateStyle = .long
        return f.string(from: Date())
    }
}

// MARK: - Patient-facing quote document (PDF)

/// Aurion-branded quote document rendered into the exported PDF. Mirrors the
/// SOAP export's masthead so the two documents read as one family.
struct SurgeryQuoteDocumentBody: View {
    let lineItems: [SurgeryQuoteLineItem]
    let currency: String
    let notes: String
    let dateString: String

    private var pricedItems: [SurgeryQuoteLineItem] {
        lineItems.filter { !$0.procedure.trimmingCharacters(in: .whitespaces).isEmpty }
    }
    private var totalCents: Int { pricedItems.compactMap(\.feeCents).reduce(0, +) }

    var body: some View {
        VStack(alignment: .leading, spacing: 22) {
            VStack(alignment: .leading, spacing: 6) {
                Text("AURION CLINICAL AI")
                    .font(.system(size: 9, weight: .bold)).tracking(2)
                    .foregroundColor(.aurionGold)
                Text(L("quote.docTitle"))
                    .font(.system(size: 30, weight: .bold))
                    .foregroundColor(.aurionNavy)
                Text(dateString)
                    .font(.system(size: 13)).foregroundColor(.black.opacity(0.55))
                Rectangle().fill(Color.aurionGold).frame(height: 2).padding(.top, 8)
            }

            VStack(spacing: 0) {
                HStack {
                    Text(L("quote.colProcedure"))
                        .font(.system(size: 11, weight: .bold)).tracking(0.5)
                        .foregroundColor(.black.opacity(0.5))
                    Spacer()
                    Text(L("quote.colFee"))
                        .font(.system(size: 11, weight: .bold)).tracking(0.5)
                        .foregroundColor(.black.opacity(0.5))
                }
                .padding(.bottom, 8)
                ForEach(pricedItems) { item in
                    HStack(alignment: .top) {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(item.procedure)
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundColor(.aurionNavy)
                            if !item.detail.isEmpty {
                                Text(item.detail)
                                    .font(.system(size: 12))
                                    .foregroundColor(.black.opacity(0.6))
                                    .fixedSize(horizontal: false, vertical: true)
                            }
                        }
                        Spacer(minLength: 16)
                        Text(item.feeCents == nil
                             ? L("quote.tbd")
                             : SurgeryQuoteView.formatMoney(cents: item.feeCents!, currency: currency))
                            .font(.system(size: 14, weight: .semibold))
                            .foregroundColor(.aurionNavy)
                    }
                    .padding(.vertical, 8)
                    Rectangle().fill(Color.black.opacity(0.08)).frame(height: 1)
                }
                HStack {
                    Text(L("quote.total"))
                        .font(.system(size: 15, weight: .bold)).foregroundColor(.aurionNavy)
                    Spacer()
                    Text(SurgeryQuoteView.formatMoney(cents: totalCents, currency: currency))
                        .font(.system(size: 15, weight: .bold)).foregroundColor(.aurionNavy)
                }
                .padding(.top, 10)
            }

            if !notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text(L("quote.notes").uppercased())
                        .font(.system(size: 10, weight: .bold)).tracking(0.6)
                        .foregroundColor(.black.opacity(0.45))
                    Text(notes)
                        .font(.system(size: 13)).foregroundColor(.black.opacity(0.8))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.top, 4)
            }

            Text(L("quote.disclaimer"))
                .font(.system(size: 11)).italic()
                .foregroundColor(.black.opacity(0.5))
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 8)
        }
        .padding(.horizontal, 24)
        .padding(.vertical, 28)
        .background(Color.white)
    }
}

enum SurgeryQuotePDFRendererError: LocalizedError {
    case rasterisationFailed
    var errorDescription: String? { "Could not render the quote for PDF." }
}

/// On-device PDF renderer for the surgery quote. Same US-Letter + ImageRenderer
/// approach as NotePDFRenderer; quotes are short so a simple page-height slice
/// is enough (no gap-backoff needed).
enum SurgeryQuotePDFRenderer {
    private static let pageSize = CGSize(width: 612, height: 792)
    private static let pageMargin: CGFloat = 36

    @MainActor
    static func render(
        lineItems: [SurgeryQuoteLineItem],
        currency: String,
        notes: String,
        dateString: String
    ) throws -> Data {
        let contentWidth = pageSize.width - pageMargin * 2
        let document = SurgeryQuoteDocumentBody(
            lineItems: lineItems, currency: currency, notes: notes, dateString: dateString
        )
        .frame(width: contentWidth, alignment: .topLeading)

        let renderer = ImageRenderer(content: document)
        renderer.scale = 2
        renderer.proposedSize = .init(width: contentWidth, height: nil)
        guard let cgImage = renderer.cgImage else {
            throw SurgeryQuotePDFRendererError.rasterisationFailed
        }
        let renderedHeight = CGFloat(cgImage.height) / renderer.scale
        let renderedWidth = CGFloat(cgImage.width) / renderer.scale
        let printableHeight = pageSize.height - pageMargin * 2

        let pdfData = NSMutableData()
        UIGraphicsBeginPDFContextToData(pdfData, .init(origin: .zero, size: pageSize), nil)
        var yOffset: CGFloat = 0
        while yOffset < renderedHeight {
            UIGraphicsBeginPDFPage()
            guard let ctx = UIGraphicsGetCurrentContext() else { break }
            let sliceHeight = min(printableHeight, renderedHeight - yOffset)
            let cropRect = CGRect(
                x: 0, y: yOffset * renderer.scale,
                width: renderedWidth * renderer.scale, height: sliceHeight * renderer.scale
            )
            if let slice = cgImage.cropping(to: cropRect) {
                let drawRect = CGRect(x: pageMargin, y: pageMargin, width: renderedWidth, height: sliceHeight)
                ctx.saveGState()
                ctx.translateBy(x: 0, y: pageSize.height)
                ctx.scaleBy(x: 1, y: -1)
                ctx.draw(slice, in: CGRect(
                    x: drawRect.minX, y: pageSize.height - drawRect.maxY,
                    width: drawRect.width, height: drawRect.height
                ))
                ctx.restoreGState()
            }
            yOffset += sliceHeight
        }
        UIGraphicsEndPDFContext()
        return pdfData as Data
    }
}
