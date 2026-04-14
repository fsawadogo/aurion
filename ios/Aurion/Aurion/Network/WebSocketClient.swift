import Foundation
import Combine

/// WebSocket client for real-time note delivery (Stage 1 and Stage 2).
@MainActor
final class WebSocketClient: ObservableObject {
    @Published var latestNote: NoteResponse?
    @Published var isConnected = false

    private var webSocket: URLSessionWebSocketTask?
    private let sessionId: String

    init(sessionId: String) {
        self.sessionId = sessionId
    }

    func connect() {
        let url = URL(string: "\(AppConfig.wsBaseURL)/ws/notes/\(sessionId)")!
        webSocket = URLSession.shared.webSocketTask(with: url)
        webSocket?.resume()
        isConnected = true
        receiveMessage()
    }

    func disconnect() {
        webSocket?.cancel(with: .goingAway, reason: nil)
        isConnected = false
    }

    private func receiveMessage() {
        webSocket?.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch result {
                case .success(let message):
                    switch message {
                    case .string(let text):
                        if let data = text.data(using: .utf8),
                           let note = try? JSONDecoder().decode(NoteResponse.self, from: data) {
                            self.latestNote = note
                        }
                    case .data(let data):
                        if let note = try? JSONDecoder().decode(NoteResponse.self, from: data) {
                            self.latestNote = note
                        }
                    @unknown default:
                        break
                    }
                    self.receiveMessage()
                case .failure:
                    self.isConnected = false
                }
            }
        }
    }
}
