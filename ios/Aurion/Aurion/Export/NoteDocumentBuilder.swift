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
    static func makeDocx(
        _ note: NoteResponse,
        sessionId: String,
        dateString: String = "",
        patientAgeSex: String = "",
        encounterType: String = ""
    ) throws -> Data {
        let documentXML = buildDocumentXML(
            note: note,
            sessionId: sessionId,
            dateString: dateString,
            patientAgeSex: patientAgeSex,
            encounterType: encounterType
        )
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

    // Aurion brand palette (hex, no #) — matches Theme.swift / the backend
    // DOCX + the iOS PDF redesign so every export surface reads identically.
    private static let navyHex = "0C1B37"
    private static let navyMidHex = "2A448C"
    private static let goldHex = "C9A84C"
    private static let amberHex = "D9941F"
    private static let grayHex = "6B7280"
    private static let inkHex = "1A1F29"
    private static let whiteHex = "FFFFFF"

    private static func buildDocumentXML(
        note: NoteResponse,
        sessionId: String,
        dateString: String,
        patientAgeSex: String,
        encounterType: String
    ) -> String {
        var body = ""

        // ── Masthead: gold eyebrow, navy title, meta strip, gold rule ────
        body += para("AURION CLINICAL AI", bold: true, size: 16, color: goldHex, after: 0)
        body += para(specialtyTitle(note.specialty), bold: true, size: 44, color: navyHex, after: 60)
        // Encounter metadata strip — Date · Patient Age/Sex · Encounter Type.
        // Mirrors the reference letterhead + the iOS PDF/screen header band.
        // Internal metadata (completeness / version / provider) stays omitted
        // — it lives in the audit log, not on the clinician-facing note.
        body += metaTable(
            dateString: dateString,
            patientAgeSex: patientAgeSex,
            encounterType: encounterType
        )
        body += para("", border: goldHex, before: 80, after: 160)  // gold rule

        // ── SOAP-grouped body ────────────────────────────────────────────
        for group in soapGroups(note.sections) {
            body += para("  \(group.0)  —  \(group.1)", bold: true, size: 26,
                         color: whiteHex, fill: navyHex, before: 160, after: 80)
            for section in group.2 {
                body += para(section.title, bold: true, size: 22, color: navyMidHex,
                             border: goldHex, before: 100, after: 20)
                let prose = paragraph(for: section)
                if prose.isEmpty {
                    body += para(statusNote(section.status), italic: true, size: 20,
                                 color: grayHex, after: 60)
                } else {
                    body += para(prose, size: 22, color: inkHex, after: 60)
                }
            }
        }

        // ── Draft banner + provenance + review disclaimer ────────────────
        // Mode-neutral wording (scribe-0 #620): iOS does not read the grounded
        // flag, so the export must not claim "no diagnostic or interpretive
        // conclusions" — that is false once Grounded Synthesis Mode is on. A
        // neutral "AI-generated, review required" disclaimer is true in both modes.
        body += para("  DRAFT  ·  AI-generated clinical note — clinician review required before clinical use",
                     bold: true, size: 18, color: whiteHex, fill: amberHex, before: 200, after: 60)
        body += para("Generated by Aurion Clinical AI", size: 16, color: grayHex, after: 20)
        body += para("This document is an AI-generated clinical note. Clinician review is required before it is used or filed.",
                     italic: true, size: 16, color: grayHex, after: 0)

        return """
            <?xml version="1.0" encoding="UTF-8" standalone="yes"?>\
            <w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">\
            <w:body>\(body)</w:body>\
            </w:document>
            """
    }

    /// One Word paragraph (`<w:p>`) with a single styled run. Supports inline
    /// colour (`w:color`), paragraph shading (`w:shd`, for the navy/amber
    /// bands), and a bottom border (`w:pBdr`, for the gold rules) — all valid
    /// without a styles part. `w:sz` is half-points (22 = 11pt). pPr children
    /// follow the CT_PPr schema order: pBdr, shd, spacing.
    private static func para(
        _ text: String,
        bold: Bool = false,
        italic: Bool = false,
        size: Int = 22,
        color: String? = nil,
        fill: String? = nil,
        border: String? = nil,
        before: Int = 0,
        after: Int = 80
    ) -> String {
        var pPr = "<w:pPr>"
        if let border = border {
            pPr += "<w:pBdr><w:bottom w:val=\"single\" w:sz=\"6\" w:space=\"2\" w:color=\"\(border)\"/></w:pBdr>"
        }
        if let fill = fill {
            pPr += "<w:shd w:val=\"clear\" w:color=\"auto\" w:fill=\"\(fill)\"/>"
        }
        pPr += "<w:spacing w:before=\"\(before)\" w:after=\"\(after)\"/>"
        pPr += "</w:pPr>"
        var rPr = "<w:rPr>"
        if bold { rPr += "<w:b/>" }
        if italic { rPr += "<w:i/>" }
        if let color = color { rPr += "<w:color w:val=\"\(color)\"/>" }
        rPr += "<w:sz w:val=\"\(size)\"/></w:rPr>"
        return "<w:p>\(pPr)<w:r>\(rPr)<w:t xml:space=\"preserve\">\(xmlEscape(text))</w:t></w:r></w:p>"
    }

    // Light-navy tint for the metadata band — matches the iOS PDF strip.
    private static let metaStripHex = "EAF2FB"

    /// The Date · Patient Age/Sex · Encounter Type band, as a borderless
    /// full-width 3-cell table with light-navy shading. A Word table needs
    /// no styles part — tblPr/tblGrid/tr/tc are valid standalone.
    private static func metaTable(
        dateString: String,
        patientAgeSex: String,
        encounterType: String
    ) -> String {
        let notDoc = "Not documented"
        let dateVal = dateString.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? notDoc : dateString
        let patientVal = patientAgeSex.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? notDoc : patientAgeSex
        let encounterVal = encounterType.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? notDoc : encounterType
        let cells = metaCell(label: "Date", value: dateVal)
            + metaCell(label: "Patient Age / Sex", value: patientVal)
            + metaCell(label: "Encounter Type", value: encounterVal)
        return """
            <w:tbl>\
            <w:tblPr>\
            <w:tblW w:w="5000" w:type="pct"/>\
            <w:tblBorders>\
            <w:top w:val="none" w:sz="0" w:space="0" w:color="auto"/>\
            <w:left w:val="none" w:sz="0" w:space="0" w:color="auto"/>\
            <w:bottom w:val="none" w:sz="0" w:space="0" w:color="auto"/>\
            <w:right w:val="none" w:sz="0" w:space="0" w:color="auto"/>\
            <w:insideH w:val="none" w:sz="0" w:space="0" w:color="auto"/>\
            <w:insideV w:val="none" w:sz="0" w:space="0" w:color="auto"/>\
            </w:tblBorders>\
            </w:tblPr>\
            <w:tblGrid><w:gridCol w:w="3120"/><w:gridCol w:w="3120"/><w:gridCol w:w="3120"/></w:tblGrid>\
            <w:tr>\(cells)</w:tr>\
            </w:tbl>
            """
    }

    /// One shaded table cell: a small uppercase gray label over a navy value.
    private static func metaCell(label: String, value: String) -> String {
        let labelPara = para(label.uppercased(), bold: true, size: 15, color: grayHex, after: 20)
        let valuePara = para(value, bold: true, size: 20, color: navyHex, after: 0)
        return """
            <w:tc>\
            <w:tcPr>\
            <w:tcW w:w="1666" w:type="pct"/>\
            <w:shd w:val="clear" w:color="auto" w:fill="\(metaStripHex)"/>\
            <w:tcMar>\
            <w:top w:w="90" w:type="dxa"/><w:left w:w="130" w:type="dxa"/>\
            <w:bottom w:w="90" w:type="dxa"/><w:right w:w="130" w:type="dxa"/>\
            </w:tcMar>\
            </w:tcPr>\
            \(labelPara)\(valuePara)\
            </w:tc>
            """
    }

    /// Pretty specialty title for the masthead (mirrors the backend export).
    private static func specialtyTitle(_ key: String) -> String {
        let map = [
            "orthopedic_surgery": "Orthopedic Surgery",
            "plastic_surgery": "Plastic Surgery",
            "musculoskeletal": "Musculoskeletal",
            "emergency_medicine": "Emergency Medicine",
            "general": "General Medicine",
        ]
        return map[key] ?? key.replacingOccurrences(of: "_", with: " ").capitalized
    }

    private static func statusNote(_ status: String) -> String {
        switch status {
        case "pending_video": return "Pending video analysis."
        case "processing_failed": return "Could not be processed — clinician entry required."
        default: return "Not captured during this encounter."
        }
    }

    /// Bucket the note's sections into the four SOAP headers (order-preserving),
    /// routing unknown ids by keyword and dropping empty groups. Mirrors the
    /// iOS PDF view + the backend export so all surfaces read identically.
    private static func soapGroups(
        _ sections: [NoteSectionResponse]
    ) -> [(String, String, [NoteSectionResponse])] {
        let mapping: [(String, String, [String])] = [
            ("S", "SUBJECTIVE", ["chief_complaint", "hpi", "history",
                                 "past_medical_history", "past_surgical_history",
                                 "medications", "allergies"]),
            ("O", "OBJECTIVE", ["vital_signs", "physical_exam", "wound_assessment",
                                "functional_assessment", "imaging_review", "investigations"]),
            ("A", "ASSESSMENT", ["assessment"]),
            ("P", "PLAN", ["plan", "disposition"]),
        ]
        var byId: [String: NoteSectionResponse] = [:]
        for s in sections where byId[s.id] == nil { byId[s.id] = s }
        var used = Set<String>()
        var buckets: [[NoteSectionResponse]] = mapping.map { _ in [] }
        for (i, entry) in mapping.enumerated() {
            for sid in entry.2 {
                if let s = byId[sid] {
                    buckets[i].append(s)
                    used.insert(sid)
                }
            }
        }
        for s in sections where !used.contains(s.id) {
            let sid = s.id.lowercased()
            let idx: Int
            if sid.contains("assess") || sid.contains("impression") { idx = 2 }
            else if sid.contains("plan") || sid.contains("dispo") || sid.contains("follow") { idx = 3 }
            else if sid.contains("exam") || sid.contains("imag") || sid.contains("vital")
                        || sid.contains("investig") || sid.contains("objective") { idx = 1 }
            else { idx = 0 }
            buckets[idx].append(s)
        }
        var result: [(String, String, [NoteSectionResponse])] = []
        for (i, entry) in mapping.enumerated() where !buckets[i].isEmpty {
            result.append((entry.0, entry.1, buckets[i]))
        }
        return result
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
