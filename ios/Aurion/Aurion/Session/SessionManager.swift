import Foundation
import Combine
import SwiftUI

/// Manages the full session lifecycle -- bridges iOS UI to backend API.
@MainActor
final class SessionManager: ObservableObject {
    @Published var session: CaptureSession?
    @Published var note: NoteResponse?
    @Published var isProcessing = false
    @Published var processingStatus = ""
    @Published var error: String?

    private let api = APIClient.shared

    // MARK: - Session Lifecycle

    func startNewSession(specialty: String) async {
        error = nil
        do {
            let response = try await api.createSession(specialty: specialty)
            let captureSession = CaptureSession(id: response.id, specialty: specialty)
            captureSession.state = .consentPending
            session = captureSession
        } catch {
            self.error = "Failed to create session: \(error.localizedDescription)"
        }
    }

    func confirmConsent() async {
        guard let session else { return }
        do {
            _ = try await api.confirmConsent(sessionId: session.id)
            session.confirmConsent()
        } catch {
            self.error = "Consent failed: \(error.localizedDescription)"
        }
    }

    func startRecording() async {
        guard let session else { return }
        do {
            _ = try await api.startRecording(sessionId: session.id)
            session.startRecording()
        } catch {
            self.error = "Start failed: \(error.localizedDescription)"
        }
    }

    func stopRecording() async {
        guard let session else { return }
        do {
            _ = try await api.stopRecording(sessionId: session.id)
            session.stopRecording()

            // Submit mock audio for transcription (Simulator mode)
            await submitMockAudio()
        } catch {
            self.error = "Stop failed: \(error.localizedDescription)"
        }
    }

    // MARK: - Mock Audio Pipeline (Simulator)

    private func submitMockAudio() async {
        guard let session else { return }
        isProcessing = true
        processingStatus = "Transcribing audio..."

        do {
            let mockAudio = WAVBuilder.silence()

            let url = URL(string: "\(AppConfig.baseAPIPath)/transcription/\(session.id)")!
            var request = URLRequest(url: url)
            request.httpMethod = "POST"

            let boundary = UUID().uuidString
            request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
            request.setValue("Bearer CLINICIAN", forHTTPHeaderField: "Authorization")

            var body = Data()
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"audio_file\"; filename=\"recording.wav\"\r\n".data(using: .utf8)!)
            body.append("Content-Type: audio/wav\r\n\r\n".data(using: .utf8)!)
            body.append(mockAudio)
            body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
            request.httpBody = body

            processingStatus = "Generating note..."

            let (data, response) = try await URLSession.shared.data(for: request)

            if let httpResponse = response as? HTTPURLResponse, httpResponse.statusCode == 200 {
                processingStatus = "Note ready for review"

                try await Task.sleep(nanoseconds: 2_000_000_000)
                await fetchNote()
            } else {
                processingStatus = "Using demo note for Simulator"
                try await Task.sleep(nanoseconds: 1_000_000_000)
                note = createMockNote(sessionId: session.id, specialty: session.specialty)
            }

            isProcessing = false
        } catch {
            processingStatus = "Using demo note for Simulator"
            note = createMockNote(sessionId: session.id, specialty: session.specialty)
            isProcessing = false
        }
    }

    private func fetchNote() async {
        guard let session else { return }
        do {
            note = try await api.getStage1Note(sessionId: session.id)
        } catch {
            note = createMockNote(sessionId: session.id, specialty: session.specialty)
        }
    }

    func approveNote() async {
        guard let session else { return }
        do {
            _ = try await api.approveFinalNote(sessionId: session.id)
            AurionHaptics.notification(.success)
        } catch {
            self.error = "Approval failed: \(error.localizedDescription)"
        }
    }

    func endSession() {
        session?.clearPersistence()
        session = nil
        note = nil
        isProcessing = false
        processingStatus = ""
        error = nil
    }

    // MARK: - Crash Recovery

    func validateRecoveredSession(_ recoveredSession: CaptureSession) async -> Bool {
        do {
            let response = try await api.getSession(sessionId: recoveredSession.id)
            if let backendState = SessionState(rawValue: response.state) {
                if backendState.isActive {
                    recoveredSession.state = backendState
                    session = recoveredSession
                    return true
                } else {
                    SessionPersistence.clear()
                    return false
                }
            }
            return false
        } catch let error as APIError {
            switch error {
            case .notFound:
                SessionPersistence.clear()
                self.error = "Session expired. Starting fresh."
                return false
            case .offline:
                session = recoveredSession
                return true
            default:
                SessionPersistence.clear()
                return false
            }
        } catch {
            SessionPersistence.clear()
            return false
        }
    }

    // MARK: - Mock Data Generators

    private func createMockNote(sessionId: String, specialty: String) -> NoteResponse {
        NoteResponse(
            sessionId: sessionId,
            stage: 1,
            version: 1,
            providerUsed: "demo",
            specialty: specialty,
            completenessScore: 0.83,
            sections: [
                NoteSectionResponse(id: "chief_complaint", title: "Chief Complaint", status: "populated", claims: [
                    NoteClaimResponse(id: "c1", text: "Physician noted patient presents with right knee pain for the past two weeks, worsening with activity.", sourceType: "transcript", sourceId: "seg_001", sourceQuote: "The patient presents with right knee pain for the past two weeks.")
                ]),
                NoteSectionResponse(id: "hpi", title: "History of Present Illness", status: "populated", claims: [
                    NoteClaimResponse(id: "c2", text: "Physician noted pain began gradually without specific injury, aggravated by stairs and prolonged standing.", sourceType: "transcript", sourceId: "seg_002", sourceQuote: "The pain began gradually without a specific injury.")
                ]),
                NoteSectionResponse(id: "physical_exam", title: "Physical Examination", status: "populated", claims: [
                    NoteClaimResponse(id: "c3", text: "Physician noted tenderness on palpation at the medial joint line of the right knee.", sourceType: "transcript", sourceId: "seg_003", sourceQuote: "There is tenderness on palpation at the medial joint line."),
                    NoteClaimResponse(id: "c4", text: "Physician noted range of motion restricted to approximately 110 degrees of flexion.", sourceType: "transcript", sourceId: "seg_004", sourceQuote: "Range of motion is restricted to approximately 110 degrees of flexion.")
                ]),
                NoteSectionResponse(id: "imaging_review", title: "Imaging Review", status: "pending_video", claims: []),
                NoteSectionResponse(id: "assessment", title: "Assessment", status: "populated", claims: [
                    NoteClaimResponse(id: "c5", text: "Physician stated working diagnosis of medial meniscus pathology, right knee.", sourceType: "transcript", sourceId: "seg_005", sourceQuote: "Working diagnosis is medial meniscus pathology.")
                ]),
                NoteSectionResponse(id: "plan", title: "Plan", status: "populated", claims: [
                    NoteClaimResponse(id: "c6", text: "Physician ordered MRI of the right knee and referred to physiotherapy for 6 weeks.", sourceType: "transcript", sourceId: "seg_006", sourceQuote: "We will order an MRI and start physiotherapy.")
                ]),
            ]
        )
    }
}
