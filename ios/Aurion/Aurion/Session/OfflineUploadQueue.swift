import Combine
import Foundation

/// A clinical encounter's audio, persisted to disk because it could not be
/// uploaded when the physician finished recording (clinic network down).
///
/// Only metadata lives in the manifest; the audio bytes sit in a sibling
/// `<sessionId>.wav` file under complete file protection. `specialty` is kept
/// purely so the sync banner can say *what* is waiting — it is not PHI.
struct QueuedUpload: Codable, Identifiable {
    let sessionId: String
    let specialty: String
    let createdAt: Date
    var attempts: Int

    var id: String { sessionId }
    var audioFilename: String { "\(sessionId).wav" }
}

/// Disk-backed queue that guarantees a recorded encounter is never lost to a
/// dropped network. When `submitAudio` can't reach the backend, the WAV is
/// written to encrypted on-device storage and replayed — stop transition then
/// audio upload — when connectivity returns (or on next app launch).
///
/// **Privacy (CLAUDE.md):** queued audio is raw clinical data, so each file is
/// written with `.completeFileProtection` (encrypted at rest, unreadable while
/// the device is locked) in a directory excluded from iCloud/iTunes backup,
/// and is deleted the instant its upload succeeds — mirroring the backend's
/// "raw audio deleted after transcription" guarantee. Nothing here is logged
/// beyond session id, byte count, and status.
///
/// Scope: the audio spine only. Video/screen frames are Stage 2 enrichment and
/// are intentionally not queued — Stage 1 (audio → note) is the clinical
/// record that must survive.
@MainActor
final class OfflineUploadQueue: ObservableObject {
    static let shared = OfflineUploadQueue()

    /// Encounters awaiting upload, oldest first. Drives the sync banner.
    @Published private(set) var pending: [QueuedUpload] = []
    /// True while `flush` is actively uploading, so the UI can show a spinner.
    @Published private(set) var isSyncing = false

    private let api = APIClient.shared
    private let fm = FileManager.default
    /// Give up (and drop) an item after this many failed *server-side*
    /// attempts so a permanently-rejected encounter can't wedge the queue.
    /// Offline/timeout failures don't count — they're expected and retried.
    private let maxAttempts = 5
    /// Reentrancy guard — reconnect + launch + manual triggers can overlap.
    private var isFlushing = false

    private lazy var directory: URL = {
        let base = fm.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("OfflineUploads", isDirectory: true)
    }()
    private var manifestURL: URL { directory.appendingPathComponent("manifest.json") }

    private init() {
        ensureDirectory()
        pending = loadManifest()
    }

    /// Wire reconnect-driven flushing and drain anything left from a prior
    /// launch. Call once at app start.
    func start() {
        ReachabilityMonitor.shared.setReconnectHandler { [weak self] in
            await self?.flush()
        }
        Task { await flush() }
    }

    /// Persist a recorded encounter for deferred upload. Replaces any existing
    /// entry for the same session (a retry of the same encounter shouldn't
    /// stack duplicates).
    func enqueue(sessionId: String, specialty: String, audio: Data) throws {
        ensureDirectory()
        let item = QueuedUpload(
            sessionId: sessionId,
            specialty: specialty,
            createdAt: Date(),
            attempts: 0
        )
        try audio.write(
            to: directory.appendingPathComponent(item.audioFilename),
            options: [.atomic, .completeFileProtection]
        )
        pending = pending.filter { $0.sessionId != sessionId } + [item]
        saveManifest()
    }

    /// Attempt to upload every queued encounter. No-op when offline or empty.
    /// Stops early (keeping the rest) the moment the network drops again so we
    /// don't grind through certain-to-fail attempts.
    func flush() async {
        guard !isFlushing,
              ReachabilityMonitor.shared.isOnline,
              !pending.isEmpty else { return }
        isFlushing = true
        isSyncing = true
        defer { isFlushing = false; isSyncing = false }

        for item in pending {
            guard ReachabilityMonitor.shared.isOnline else { break }

            let fileURL = directory.appendingPathComponent(item.audioFilename)
            let audio = try? Data(contentsOf: fileURL)
            guard let audio, !audio.isEmpty else {
                // No usable audio for this manifest entry. Drop the orphan
                // when the file is missing, or readable-but-empty (garbage —
                // we only ever write non-empty WAVs atomically). Keep it only
                // when the file exists but couldn't be read, which means it's
                // locked under complete file protection — retry once the
                // device is unlocked.
                let lockedNotEmpty = audio == nil && fm.fileExists(atPath: fileURL.path)
                if !lockedNotEmpty { remove(item.sessionId) }
                continue
            }

            do {
                try await upload(item, audio: audio)
                remove(item.sessionId)
                AuditLogger.log(
                    event: .offlineUploadSynced,
                    sessionId: item.sessionId,
                    extra: ["bytes": "\(audio.count)"]
                )
            } catch APIError.offline, APIError.timeout, APIError.unauthorized {
                // Network gone again, or the token expired — both are
                // transient. Leave everything queued and retry on the next
                // reconnect / launch; don't burn a bounded-retry attempt.
                break
            } catch APIError.notFound {
                remove(item.sessionId)  // session no longer exists server-side
            } catch {
                bumpAttempts(item.sessionId)  // other 4xx/5xx — bounded retry
            }
        }
    }

    // MARK: - Upload

    private func upload(_ item: QueuedUpload, audio: Data) async throws {
        // Replay the stop transition in case it never reached the server
        // (offline at the moment the physician hit Stop). The transcription
        // endpoint requires PROCESSING_STAGE1. A 409/other error means the
        // session already moved past RECORDING — fine, proceed to the upload,
        // which is the real state gate. Only a fresh offline/timeout aborts.
        do {
            _ = try await api.stopRecording(sessionId: item.sessionId)
        } catch APIError.offline {
            throw APIError.offline
        } catch APIError.timeout {
            throw APIError.timeout
        } catch {
            // already transitioned (conflict) or transient — let the upload decide
        }
        try await api.uploadAudioForTranscription(sessionId: item.sessionId, audio: audio)
    }

    /// Drop a session's queued upload — its WAV file + manifest entry. Used by
    /// the post-export purge (#11): a session whose note already shipped must
    /// not leave a raw-audio copy in the offline queue. No-op if absent.
    func purge(sessionId: String) {
        remove(sessionId)
    }

    // MARK: - Manifest + file persistence

    private func remove(_ sessionId: String) {
        if let item = pending.first(where: { $0.sessionId == sessionId }) {
            try? fm.removeItem(at: directory.appendingPathComponent(item.audioFilename))
        }
        pending.removeAll { $0.sessionId == sessionId }
        saveManifest()
    }

    private func bumpAttempts(_ sessionId: String) {
        guard let idx = pending.firstIndex(where: { $0.sessionId == sessionId }) else { return }
        pending[idx].attempts += 1
        if pending[idx].attempts >= maxAttempts {
            remove(sessionId)
        } else {
            saveManifest()
        }
    }

    private func ensureDirectory() {
        guard !fm.fileExists(atPath: directory.path) else { return }
        try? fm.createDirectory(at: directory, withIntermediateDirectories: true)
        // Raw PHI must never leave the device via iCloud/iTunes backup.
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var dir = directory
        try? dir.setResourceValues(values)
    }

    private func loadManifest() -> [QueuedUpload] {
        guard let data = try? Data(contentsOf: manifestURL),
              let items = try? JSONDecoder.aurionISO.decode([QueuedUpload].self, from: data)
        else { return [] }
        return items.sorted { $0.createdAt < $1.createdAt }
    }

    private func saveManifest() {
        guard let data = try? JSONEncoder.aurionISO.encode(pending) else { return }
        try? data.write(to: manifestURL, options: [.atomic, .completeFileProtection])
    }
}

private extension JSONDecoder {
    static var aurionISO: JSONDecoder {
        let d = JSONDecoder()
        d.dateDecodingStrategy = .iso8601
        return d
    }
}

private extension JSONEncoder {
    static var aurionISO: JSONEncoder {
        let e = JSONEncoder()
        e.dateEncodingStrategy = .iso8601
        return e
    }
}
