//
//  AurionTests.swift
//  AurionTests
//
//  Created by Faïçal Sawadogo on 2026-04-12.
//

import Testing
import UIKit
@testable import Aurion

struct AurionTests {

    @Test func example() async throws {
        // Write your test here and use APIs like `#expect(...)` to check expected conditions.
    }

    // MARK: - P0-01 Fail-Closed Masking

    /// An empty UIImage (no backing cgImage) must fail masking with a
    /// well-typed reason and produce no imageData. This is the simplest
    /// fail-closed contract: the pipeline never invents bytes when it cannot
    /// prove the frame is masked.
    @Test func maskVideoFrame_invalidImage_failsClosed() async {
        let result = await MaskingPipeline.shared.maskVideoFrame(UIImage(), sessionId: "test-session")
        #expect(result.success == false)
        #expect(result.imageData == nil)
        #expect(result.frameType == .video)
        #expect(result.failureReason == .invalidImage)
    }

    @Test func redactScreenCapture_invalidImage_failsClosed() async {
        let result = await MaskingPipeline.shared.redactScreenCapture(UIImage(), sessionId: "test-session")
        #expect(result.success == false)
        #expect(result.imageData == nil)
        #expect(result.frameType == .screen)
        #expect(result.failureReason == .invalidImage)
    }

    /// MaskingResult must carry its frame type and reason verbatim so the
    /// audit log and the masking proof contract (P0-02) can deserialize them
    /// without ambiguity.
    @Test func maskingFailureReason_rawValues() {
        #expect(MaskingFailureReason.invalidImage.rawValue == "invalid_image")
        #expect(MaskingFailureReason.detectionError.rawValue == "detection_error")
        #expect(MaskingFailureReason.ocrError.rawValue == "ocr_error")
        #expect(MaskingFailureReason.renderError.rawValue == "render_error")
        #expect(MaskingFrameType.video.rawValue == "video")
        #expect(MaskingFrameType.screen.rawValue == "screen")
    }

    // MARK: - P0-03 Demo Mode Gating

    /// In Debug + simulator (the only place the test suite runs), demo
    /// content is permitted unless `AURION_DEMO_DISABLED=1` is set. The
    /// release-build branch is verified statically by `#if DEBUG`
    /// wrapping the `createDemoNote` function — a release compile that
    /// referenced it would fail to build.
    @Test func demoMode_simulatorDebug_enabledByDefault() {
        // Test target is always Debug + simulator. The runtime override is
        // not set by default in `xcodebuild test`, so demo should be on.
        #expect(ProcessInfo.processInfo.environment["AURION_DEMO_DISABLED"] != "1")
        #expect(DemoMode.isEnabled == true)
    }

    // MARK: - Capture Mode Stream Eligibility

    /// Each mode's intent — what streams should run. A regression that, say,
    /// lights the camera in audioOnly mode would trip this before it ships.
    @Test func captureMode_includesVideo() {
        #expect(CaptureMode.multimodal.includesVideo == true)
        #expect(CaptureMode.audioOnly.includesVideo == false)
        #expect(CaptureMode.smartDictation.includesVideo == false)
    }

    @Test func captureMode_includesScreen() {
        // Mode capability only — the runtime gate AND's with the feature flag.
        #expect(CaptureMode.multimodal.includesScreen == true)
        #expect(CaptureMode.audioOnly.includesScreen == false)
        #expect(CaptureMode.smartDictation.includesScreen == false)
    }

    // MARK: - PHI Pattern QA Suite
    //
    // Per-category positive tests so a regex regression points to the
    // failing class instead of dumping a 60-line diff. Each sample is a
    // string the screen OCR could plausibly return from a real EMR view.

    private func expectPHI(_ samples: [String], category: StaticString) {
        for sample in samples {
            #expect(
                MaskingPipeline.containsPHIPattern(sample),
                "[\(category)] expected PHI detection on: \(sample)"
            )
        }
    }

    @Test func phiPatterns_detectsNames() {
        expectPHI([
            "Patient: Jane Doe",
            "Patient: Marie-Claude O'Brien",
            "Name: John Smith",
            "Nom: Pierre Tremblay",
            "Last Name: Smith",
            "First Name: John",
            "Surname: McGregor",
            "Prénom: Marie",
            "Smith, John",
            "Tremblay, Marie-Claude",
            "Dr. Perry Gdalevitch",
            "Dr Marie Gdalevitch",
            "Physician Sawadogo",
        ], category: "names")
    }

    @Test func phiPatterns_detectsIdentifierNumbers() {
        expectPHI([
            "MRN: 1234567",
            "MRN 9876543",
            "Medical Record Number: ABC-123-456",
            "Chart # 999888",
            "Dossier: 4521",
            "ABCD 1234 5678",
            "1234 567 890",
            "1234567890",
            "Health Card: ABCD 1234 5678",
            "RAMQ: TREP 1234 5678",
            "NAM TREJ 1234 5678",
            "Carte Soleil ABCD 12345678",
            "123-456-789",
            "Account: VISIT-2026-001",
            "Visit: 88421",
            "Encounter Number: E45123",
        ], category: "identifiers")
    }

    @Test func phiPatterns_detectsDemographics() {
        expectPHI([
            "DOB: 1985-03-12",
            "Date of Birth: 12/03/1985",
            "Born: 1985.03.12",
            "Naissance 1985-03-12",
            "Age: 42 yrs",
            "Age: 8 ans",
            "Sex: F",
            "Gender: Male",
            "Sexe: Femme",
        ], category: "demographics")
    }

    @Test func phiPatterns_detectsContact() {
        expectPHI([
            "(514) 555-1234",
            "+1 514-555-1234",
            "555-1234567",
            "514.555.1234",
            "patient@example.com",
            "first.last+suffix@hospital.qc.ca",
            "H3A 1B2",
            "H3A-1B2",
            "12345",
            "12345-6789",
            "1234 Sherbrooke Street",
            "42 Main St",
            "100 Rue Saint-Denis",
        ], category: "contact")
    }

    @Test func phiPatterns_detectsLocation() {
        expectPHI([
            "Room: 234",
            "Bed 12B",
            "Chambre 405",
            "Lit 2",
        ], category: "location")
    }

    // MARK: - Consent Metadata

    /// `isConsentConfirmed` is derived from `consentMethod` so the two
    /// can't desynchronize. `confirmConsent(method:)` is the single path.
    @Test @MainActor func consent_isDerivedFromMethod() {
        let session = CaptureSession(specialty: "general")
        #expect(session.isConsentConfirmed == false)
        session.confirmConsent(method: .paperForm)
        #expect(session.isConsentConfirmed == true)
        #expect(session.consentMethod == .paperForm)
        #expect(session.consentConfirmedAt != nil)
    }

    @Test func consentMethod_rawValues() {
        #expect(ConsentMethod.verbal.rawValue == "verbal")
        #expect(ConsentMethod.paperForm.rawValue == "paper_form")
        #expect(ConsentMethod.digitalForm.rawValue == "digital_form")
    }

    // MARK: - Stage 1 Retry Prompt Derivation
    //
    // Marie bug-bash (Bug A): the `.timedOut(elapsed:)` case was removed
    // when Stage 1 delivery switched from a 30s wall-clock URLSession
    // cap to a /ws/notes/{id} subscription. Failure copy is now
    // localized + timeout-neutral so it covers any backend failure
    // mode (provider error, 5xx, WS-fallback poll deadline).

    @Test func stage1Status_retryPrompt_idleStatesAreSilent() {
        #expect(Stage1Status.idle.retryPrompt == nil)
        #expect(Stage1Status.uploading.retryPrompt == nil)
        #expect(Stage1Status.generating.retryPrompt == nil)
        #expect(Stage1Status.stillWorkingLong.retryPrompt == nil)
        #expect(Stage1Status.ready.retryPrompt == nil)
        #expect(Stage1Status.queuedOffline.retryPrompt == nil)
    }

    @Test func stage1Status_retryPrompt_surfacesFailure() {
        // `.failed` is now the only state that exposes a retry prompt.
        // Copy comes from Localizable (`processing.stage1Failed.*`) so
        // we assert non-empty rather than pinning exact wording — the
        // strings are EN+FR parity-tested separately by Xcode's
        // missing-key warnings, not the runtime tests.
        let failure = Stage1Status.failed(reason: "Network error")
        let prompt = failure.retryPrompt
        #expect(prompt != nil)
        #expect((prompt?.title.isEmpty ?? true) == false)
        #expect((prompt?.detail.isEmpty ?? true) == false)
    }

    /// Strings that are SAFE to leave on-screen and should not trigger
    /// redaction. Clinical content from the descriptive-mode note model —
    /// observations, findings, plan items. Regressions here mean the
    /// regex layer is over-redacting.
    @Test func phiPatterns_doesNotFalsePositiveOnClinicalContent() {
        let cleanSamples: [String] = [
            "Range of motion restricted to 110 degrees",
            "Tenderness on palpation at the medial joint line",
            "Heart rate 72 bpm",
            "BP 120/80",
            "Discussed treatment plan with the patient",
            "Plan: order MRI, refer to physiotherapy",
            "Working diagnosis: medial meniscus pathology",
            "WBC 7.2",
            "Imaging Review",
            "Assessment",
        ]

        for sample in cleanSamples {
            #expect(
                !MaskingPipeline.containsPHIPattern(sample),
                "Unexpected PHI match on clean clinical text: \(sample)"
            )
        }
    }

    // MARK: - M-11 On-device Export

    /// Plain text export skips empty sections and emits the title +
    /// joined claims. Conflict claims are filtered unless physician-edited.
    @Test func makePlainText_skipsEmptyAndUnresolvedConflicts() {
        let note = NoteResponse(
            sessionId: "sess-1",
            stage: 2,
            version: 3,
            providerUsed: "anthropic",
            specialty: "orthopedic_surgery",
            completenessScore: 0.9,
            sections: [
                NoteSectionResponse(
                    id: "physical_exam",
                    title: "Physical Examination",
                    status: "populated",
                    claims: [
                        NoteClaimResponse(id: "c1", text: "Tender medial joint line.", sourceType: "transcript", sourceId: "seg_001", sourceQuote: "tender medial joint line"),
                    ]
                ),
                NoteSectionResponse(
                    id: "imaging_review",
                    title: "Imaging Review",
                    status: "populated",
                    claims: [
                        NoteClaimResponse(id: "vc1", text: "X-ray shows healing fracture.", sourceType: "visual", sourceId: "frame_14500", sourceQuote: ""),
                        NoteClaimResponse(id: "conflict_1", text: "Unresolved visual conflict.", sourceType: "visual", sourceId: "frame_14600", sourceQuote: ""),
                    ]
                ),
                NoteSectionResponse(
                    id: "plan",
                    title: "Plan",
                    status: "not_captured",
                    claims: []
                ),
            ]
        )

        let data = NoteDocumentBuilder.makePlainText(note, sessionId: "sess-1")
        let text = String(decoding: data, as: UTF8.self)

        #expect(text.contains("Physical Examination"))
        #expect(text.contains("Tender medial joint line."))
        #expect(text.contains("X-ray shows healing fracture."))
        // Empty section is skipped entirely.
        #expect(!text.contains("Plan\n"))
        // Unresolved conflict is filtered out.
        #expect(!text.contains("Unresolved visual conflict"))
    }

    @Test func makePlainText_includesResolvedConflict() {
        let resolved = NoteClaimResponse(
            id: "conflict_1",
            text: "Physician confirms post-op hardware.",
            sourceType: "visual",
            sourceId: "frame_14600",
            sourceQuote: "",
            physicianEdited: true,
            originalText: "stale text"
        )
        let note = NoteResponse(
            sessionId: "sess-2",
            stage: 2,
            version: 4,
            providerUsed: "anthropic",
            specialty: "orthopedic_surgery",
            completenessScore: 1.0,
            sections: [
                NoteSectionResponse(id: "imaging_review", title: "Imaging Review", status: "populated", claims: [resolved]),
            ]
        )
        let data = NoteDocumentBuilder.makePlainText(note, sessionId: "sess-2")
        let text = String(decoding: data, as: UTF8.self)
        #expect(text.contains("Physician confirms post-op hardware."))
    }

    /// A minimal DOCX must be a valid ZIP whose central directory ends with
    /// the canonical EOCD signature (0x06054b50). If the ZIP bytes are
    /// malformed, Word/Pages won't open the file.
    @Test func makeDocx_producesValidZipSignature() throws {
        let note = NoteResponse(
            sessionId: "sess-3",
            stage: 1,
            version: 1,
            providerUsed: "anthropic",
            specialty: "general",
            completenessScore: 0.5,
            sections: [
                NoteSectionResponse(id: "chief_complaint", title: "Chief Complaint", status: "populated", claims: [
                    NoteClaimResponse(id: "c1", text: "Knee pain x 2 weeks.", sourceType: "transcript", sourceId: "seg_001", sourceQuote: ""),
                ]),
            ]
        )
        let data = try NoteDocumentBuilder.makeDocx(note, sessionId: "sess-3")
        #expect(data.count > 0)
        // First 4 bytes of every DOCX/ZIP are the local file header signature.
        let pkSig: [UInt8] = [0x50, 0x4b, 0x03, 0x04]
        #expect(Array(data.prefix(4)) == pkSig)
        // The end-of-central-directory record must appear somewhere — we
        // just confirm the signature exists (full parsing is overkill here).
        let eocdSig: [UInt8] = [0x50, 0x4b, 0x05, 0x06]
        let bytes = Array(data)
        let hasEocd = (0..<bytes.count - 3).contains { i in
            Array(bytes[i..<(i + 4)]) == eocdSig
        }
        #expect(hasEocd)
    }
}
