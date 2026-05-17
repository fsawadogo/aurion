import Foundation

/// On-device note exporter. Produces plain-text and DOCX bytes without
/// any server round-trip — pilot requirement: nothing crosses the wire on
/// export. The audit log is the only thing iOS sends back to the backend
/// after generation.
///
/// The DOCX writer is intentionally minimal: just the three files Word
/// requires (`[Content_Types].xml`, `_rels/.rels`, `word/document.xml`)
/// inside a tiny uncompressed ZIP. No styles, no tables — clinical notes
/// in this pilot are prose paragraphs, so a section title + paragraph
/// body per section is all that's needed.
enum NoteDocumentBuilder {

    // MARK: - Plain text

    /// One section per `\n\n` paragraph. Title on the first line, joined
    /// claim text on the second. Skips empty sections so the export
    /// doesn't carry "not_captured" stubs.
    static func makePlainText(_ note: NoteResponse, sessionId: String) -> Data {
        var out = "Aurion Clinical Note\n"
        out += "Session: \(sessionId)\n"
        out += "Specialty: \(note.specialty)\n"
        out += "Version: \(note.version)\n\n"
        out += "---\n\n"
        for section in note.sections {
            let body = paragraph(for: section)
            guard !body.isEmpty else { continue }
            out += "\(section.title)\n"
            out += "\(body)\n\n"
        }
        return Data(out.utf8)
    }

    // MARK: - DOCX

    /// Build a minimal DOCX. Word/Pages/Google Docs all open the output;
    /// the rendering is plain (default font, no styles) but the audit
    /// trail and content are correct, which is what the pilot needs.
    static func makeDocx(_ note: NoteResponse, sessionId: String) throws -> Data {
        let documentXML = buildDocumentXML(note: note, sessionId: sessionId)
        let entries: [(String, Data)] = [
            ("[Content_Types].xml", Data(Self.contentTypesXML.utf8)),
            ("_rels/.rels", Data(Self.rootRelsXML.utf8)),
            ("word/document.xml", Data(documentXML.utf8)),
        ]
        return MinimalZip.archive(entries: entries)
    }

    // MARK: - Helpers

    /// Join non-conflict, non-empty claims into a single prose paragraph
    /// per section. Mirrors the read-mode rendering in NoteReviewView so
    /// what the physician saw is what gets exported.
    private static func paragraph(for section: NoteSectionResponse) -> String {
        let texts = section.claims
            .filter { !($0.id.hasPrefix("conflict_") && !$0.physicianEdited) }
            .map { $0.text.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        return texts.joined(separator: " ")
    }

    private static let contentTypesXML = """
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\
        <Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\
        <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\
        <Default Extension="xml" ContentType="application/xml"/>\
        <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>\
        </Types>
        """

    private static let rootRelsXML = """
        <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\
        <Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\
        <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>\
        </Relationships>
        """

    private static func buildDocumentXML(note: NoteResponse, sessionId: String) -> String {
        var body = ""
        // Title block
        body += paragraphRun(text: "Aurion Clinical Note", bold: true, size: 28)
        body += paragraphRun(text: "Session: \(sessionId)", size: 18)
        body += paragraphRun(text: "Specialty: \(note.specialty)  ·  Version: \(note.version)", size: 18)
        body += paragraphRun(text: "", size: 18)  // spacer

        for section in note.sections {
            let prose = paragraph(for: section)
            guard !prose.isEmpty else { continue }
            body += paragraphRun(text: section.title, bold: true, size: 24)
            body += paragraphRun(text: prose, size: 22)
            body += paragraphRun(text: "", size: 22)  // spacer
        }

        return """
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\
            <w:body>\(body)</w:body>\
            </w:document>
            """
    }

    /// One Word paragraph (`<w:p>`) with a single styled run.
    private static func paragraphRun(text: String, bold: Bool = false, size: Int = 22) -> String {
        // `w:sz` is half-points: 22 = 11pt, 24 = 12pt, 28 = 14pt.
        let escaped = xmlEscape(text)
        let rpr = bold ? "<w:rPr><w:b/><w:sz w:val=\"\(size)\"/></w:rPr>" : "<w:rPr><w:sz w:val=\"\(size)\"/></w:rPr>"
        return "<w:p><w:r>\(rpr)<w:t xml:space=\"preserve\">\(escaped)</w:t></w:r></w:p>"
    }

    private static func xmlEscape(_ s: String) -> String {
        s.replacingOccurrences(of: "&", with: "&amp;")
            .replacingOccurrences(of: "<", with: "&lt;")
            .replacingOccurrences(of: ">", with: "&gt;")
            .replacingOccurrences(of: "\"", with: "&quot;")
    }
}


// MARK: - Minimal ZIP writer

/// Writes a ZIP archive with STORED (uncompressed) entries. The standard
/// is well-defined and the DOCX consumers (Word/Pages/Google Docs) all
/// accept stored entries, so we don't need a DEFLATE implementation.
///
/// Reference: PKWARE APPNOTE.TXT — local file header (signature 0x04034b50),
/// central directory (0x02014b50), end-of-central-directory (0x06054b50).
enum MinimalZip {

    static func archive(entries: [(String, Data)]) -> Data {
        var out = Data()
        var centralDirectory = Data()
        var entryOffsets: [(name: String, offset: UInt32, size: UInt32, crc: UInt32)] = []

        for (name, data) in entries {
            let offset = UInt32(out.count)
            let crc = crc32(data)
            let size = UInt32(data.count)
            let nameBytes = Array(name.utf8)
            let nameLength = UInt16(nameBytes.count)

            // Local file header
            out.append(contentsOf: leUInt32(0x04034b50)) // signature
            out.append(contentsOf: leUInt16(20))         // version needed
            out.append(contentsOf: leUInt16(0))          // general purpose flag
            out.append(contentsOf: leUInt16(0))          // method 0 = stored
            out.append(contentsOf: leUInt16(0))          // mod time
            out.append(contentsOf: leUInt16(0))          // mod date
            out.append(contentsOf: leUInt32(crc))
            out.append(contentsOf: leUInt32(size))       // compressed size
            out.append(contentsOf: leUInt32(size))       // uncompressed size
            out.append(contentsOf: leUInt16(nameLength))
            out.append(contentsOf: leUInt16(0))          // extra field length
            out.append(contentsOf: nameBytes)
            out.append(data)

            entryOffsets.append((name, offset, size, crc))
        }

        // Central directory
        for (name, offset, size, crc) in entryOffsets {
            let nameBytes = Array(name.utf8)
            let nameLength = UInt16(nameBytes.count)
            centralDirectory.append(contentsOf: leUInt32(0x02014b50))
            centralDirectory.append(contentsOf: leUInt16(20)) // version made by
            centralDirectory.append(contentsOf: leUInt16(20)) // version needed
            centralDirectory.append(contentsOf: leUInt16(0))
            centralDirectory.append(contentsOf: leUInt16(0))  // stored
            centralDirectory.append(contentsOf: leUInt16(0))
            centralDirectory.append(contentsOf: leUInt16(0))
            centralDirectory.append(contentsOf: leUInt32(crc))
            centralDirectory.append(contentsOf: leUInt32(size))
            centralDirectory.append(contentsOf: leUInt32(size))
            centralDirectory.append(contentsOf: leUInt16(nameLength))
            centralDirectory.append(contentsOf: leUInt16(0))  // extra
            centralDirectory.append(contentsOf: leUInt16(0))  // comment
            centralDirectory.append(contentsOf: leUInt16(0))  // disk #
            centralDirectory.append(contentsOf: leUInt16(0))  // internal attrs
            centralDirectory.append(contentsOf: leUInt32(0))  // external attrs
            centralDirectory.append(contentsOf: leUInt32(offset))
            centralDirectory.append(contentsOf: nameBytes)
        }

        let centralDirOffset = UInt32(out.count)
        let centralDirSize = UInt32(centralDirectory.count)
        out.append(centralDirectory)

        // End of central directory
        out.append(contentsOf: leUInt32(0x06054b50))
        out.append(contentsOf: leUInt16(0))
        out.append(contentsOf: leUInt16(0))
        out.append(contentsOf: leUInt16(UInt16(entryOffsets.count)))
        out.append(contentsOf: leUInt16(UInt16(entryOffsets.count)))
        out.append(contentsOf: leUInt32(centralDirSize))
        out.append(contentsOf: leUInt32(centralDirOffset))
        out.append(contentsOf: leUInt16(0))  // comment length

        return out
    }

    // MARK: - Little-endian helpers

    private static func leUInt16(_ value: UInt16) -> [UInt8] {
        [UInt8(value & 0xff), UInt8((value >> 8) & 0xff)]
    }

    private static func leUInt32(_ value: UInt32) -> [UInt8] {
        [
            UInt8(value & 0xff),
            UInt8((value >> 8) & 0xff),
            UInt8((value >> 16) & 0xff),
            UInt8((value >> 24) & 0xff),
        ]
    }

    /// IEEE 802.3 CRC-32 — what ZIP requires. Standard polynomial 0xEDB88320.
    /// Pre-computed lookup table is rebuilt lazily once per process.
    private static let crcTable: [UInt32] = {
        (0..<256).map { i -> UInt32 in
            var c = UInt32(i)
            for _ in 0..<8 {
                c = (c & 1 == 1) ? (0xEDB88320 ^ (c >> 1)) : (c >> 1)
            }
            return c
        }
    }()

    private static func crc32(_ data: Data) -> UInt32 {
        var crc: UInt32 = 0xFFFFFFFF
        for byte in data {
            crc = crcTable[Int((crc ^ UInt32(byte)) & 0xff)] ^ (crc >> 8)
        }
        return crc ^ 0xFFFFFFFF
    }
}
