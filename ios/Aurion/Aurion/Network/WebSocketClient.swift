import Foundation
import Combine

/// Envelope event pushed over `/ws/notes/{session_id}` by the backend.
///
/// Pre-PR #243 `WebSocketClient` decoded every inbound frame as a bare
/// `NoteResponse`, but the backend wraps notes in
/// `{"event": "...", "session_id": "...", "note": {...}}`. Decoding the
/// envelope as `NoteResponse` silently failed at the top-level keys
/// check, so `latestNote` never published a result and every subscriber
/// (e.g. `Stage1WSSubscriber`, `NoteReviewView`'s Stage 2 path) had to
/// fall back to polling.
///
/// The new envelope type matches the backend's `notify_*` helpers in
/// `backend/app/api/v1/websocket.py`:
///   * `stage1_delivered` — Stage 1 note ready; `note` is populated.
///   * `stage2_delivered` — Stage 2 enrichment finished; `note` populated.
///   * `stage2_progress` — incremental enrichment counter; no note.
///   * unknown — any new event type a future backend version emits;
///     decoded with the raw event string so subscribers can ignore it
///     forward-compatibly (vs. throwing and tearing the stream down).
///
/// We surface `note` as `NoteResponse?` rather than non-optional because
/// the backend's contract is "if the event carries a note, it's under
/// `note`"; making the decoder tolerant means a backend that ever
/// drops the field (or sends a partial payload mid-rollout) doesn't
/// crash deployed iOS builds. Subscribers that need a non-nil note
/// (e.g. `NoteReviewView`'s Stage 2 hand-off) gate on it explicitly.
enum WebSocketEvent: Equatable {
    /// Stage 1 note delivered. `note` carries the full Stage 1 payload
    /// (same shape as `GET /notes/{id}/stage1`).
    case stage1NoteReady(sessionId: String, note: NoteResponse?)
    /// Stage 2 enrichment finished. `note` carries the merged Stage 1+2
    /// payload.
    case stage2NoteReady(sessionId: String, note: NoteResponse?)
    /// Per-frame progress as Stage 2 captions and merges visual
    /// evidence. Used by the web portal's progress bar today; iOS
    /// reads the same data via the `/stage2-status` REST poll.
    case stage2Progress(sessionId: String, framesProcessed: Int, framesTotal: Int)
    /// Anything else the backend pushed. Carries the raw `event` string
    /// so subscribers (or logs) can identify what they ignored.
    /// Specifically NOT thrown — keeps the WebSocketClient's receive
    /// loop alive across backend additions.
    case unknown(eventType: String)
}

extension WebSocketEvent: Decodable {
    /// Decode by inspecting the `event` key first, then dispatching to
    /// the payload shape we know matches. Custom (vs. `JSONDecoder` +
    /// per-case `Codable`) so we can carry the raw event name into
    /// `.unknown` and so missing `note` doesn't throw on shapes that
    /// don't carry one.
    private enum CodingKeys: String, CodingKey {
        case event
        case sessionId = "session_id"
        case note
        case framesProcessed = "frames_processed"
        case framesTotal = "frames_total"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        let event = try container.decode(String.self, forKey: .event)
        let sessionId = try container.decodeIfPresent(String.self, forKey: .sessionId) ?? ""

        switch event {
        case "stage1_delivered":
            let note = try container.decodeIfPresent(NoteResponse.self, forKey: .note)
            self = .stage1NoteReady(sessionId: sessionId, note: note)
        case "stage2_delivered":
            let note = try container.decodeIfPresent(NoteResponse.self, forKey: .note)
            self = .stage2NoteReady(sessionId: sessionId, note: note)
        case "stage2_progress":
            let processed = try container.decodeIfPresent(Int.self, forKey: .framesProcessed) ?? 0
            let total = try container.decodeIfPresent(Int.self, forKey: .framesTotal) ?? 0
            self = .stage2Progress(
                sessionId: sessionId,
                framesProcessed: processed,
                framesTotal: total
            )
        default:
            self = .unknown(eventType: event)
        }
    }
}

/// WebSocket client for real-time note delivery (Stage 1 and Stage 2).
///
/// **Envelope decoding (lane-ios/audio-upload-resilience).** Inbound
/// frames are now decoded as `WebSocketEvent` envelopes (see above).
/// The pre-#243 path decoded every frame as a bare `NoteResponse` and
/// silently dropped real backend events, leaving subscribers stuck on
/// polling. `latestNote` is preserved for backward compatibility —
/// `NoteReviewView` reads it for the Stage 2 hand-off — and is now
/// populated from the unwrapped event payload.
///
/// Subscribers that want to discriminate event types should consume
/// the `events` `AsyncStream<WebSocketEvent>` instead of `latestNote`.
@MainActor
final class WebSocketClient: ObservableObject {
    /// Last note seen on the channel (Stage 1 OR Stage 2). Kept for
    /// the existing `NoteReviewView.onChange(of: wsClient.latestNote)`
    /// path — that view doesn't need to know whether the new note came
    /// from a Stage 1 or Stage 2 event, only that there's a fresher
    /// note to display.
    @Published var latestNote: NoteResponse?
    @Published var isConnected = false

    /// Per-instance event stream. Each call to `events` returns a NEW
    /// stream — kept simple because the WebSocketClient is itself a
    /// per-view `@StateObject`, so there's exactly one consumer per
    /// channel today. Multi-consumer multicasting can land later if
    /// needed.
    private(set) var events: AsyncStream<WebSocketEvent> = AsyncStream { _ in }
    private var eventContinuation: AsyncStream<WebSocketEvent>.Continuation?

    private var webSocket: URLSessionWebSocketTask?
    private let sessionId: String

    init(sessionId: String) {
        self.sessionId = sessionId
        // Initialize the stream + continuation eagerly so `events` is
        // immediately consumable even before `connect()` fires.
        var continuation: AsyncStream<WebSocketEvent>.Continuation!
        self.events = AsyncStream { cont in
            continuation = cont
        }
        self.eventContinuation = continuation
    }

    func connect() {
        guard let url = URL(string: "\(AppConfig.wsBaseURL)/ws/notes/\(sessionId)") else {
            // Invalid URL — surface as "not connected"; subscribers can
            // poll. Don't crash deployed builds on a misconfigured base.
            isConnected = false
            return
        }
        webSocket = URLSession.shared.webSocketTask(with: url)
        webSocket?.resume()
        isConnected = true
        receiveMessage()
    }

    func disconnect() {
        webSocket?.cancel(with: .goingAway, reason: nil)
        webSocket = nil
        isConnected = false
        eventContinuation?.finish()
    }

    private func receiveMessage() {
        webSocket?.receive { [weak self] result in
            Task { @MainActor [weak self] in
                guard let self else { return }
                switch result {
                case .success(let message):
                    let payloadData: Data?
                    switch message {
                    case .string(let text): payloadData = text.data(using: .utf8)
                    case .data(let data): payloadData = data
                    @unknown default: payloadData = nil
                    }
                    if let data = payloadData,
                       let event = try? JSONDecoder().decode(WebSocketEvent.self, from: data) {
                        self.handle(event: event)
                    }
                    // Keep receiving — a decode failure on one frame
                    // (e.g. a future event shape we don't know yet)
                    // shouldn't tear down the channel.
                    self.receiveMessage()
                case .failure:
                    self.isConnected = false
                    self.eventContinuation?.finish()
                }
            }
        }
    }

    /// Dispatch a decoded event:
    ///   * Update `latestNote` whenever the event carries a fresh note
    ///     (so the existing `NoteReviewView` observer fires).
    ///   * Forward every event (including `.unknown`) to subscribers
    ///     of the `events` stream so they can pattern-match.
    private func handle(event: WebSocketEvent) {
        switch event {
        case .stage1NoteReady(_, let note),
             .stage2NoteReady(_, let note):
            if let note { self.latestNote = note }
        case .stage2Progress, .unknown:
            break
        }
        eventContinuation?.yield(event)
    }
}
