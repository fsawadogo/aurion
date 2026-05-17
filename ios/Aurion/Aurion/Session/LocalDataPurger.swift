import Foundation

/// On-device cleanup of raw clinical artifacts.
///
/// CLAUDE.md §"Non-Negotiable Technical Rules" — the local copy of audio
/// + video + screen captures must be deleted after export, and the
/// deletion must be auditable. This module owns three things:
///
/// 1. The export-triggered purge (called from ExportView on success).
/// 2. The stale-session sweep (called on app foreground; deletes
///    leftover temp files that are >24h old).
/// 3. The audit + UI status hook so the clinician sees confirmation.
///
/// The purger does NOT touch session metadata, notes, or audit log
/// entries — those are durable records of what happened.
@MainActor
struct LocalDataPurger {

    struct PurgeReport: Equatable {
        let videoFramesPurged: Int
        let screenFramesPurged: Int
        let audioBytesPurged: Int
        let tempFilesDeleted: Int
        let timestamp: Date

        var totalArtifactsPurged: Int {
            videoFramesPurged + screenFramesPurged + tempFilesDeleted + (audioBytesPurged > 0 ? 1 : 0)
        }
    }

    /// Stale-session threshold. Per CLAUDE.md: raw frames purged ≤24h
    /// after export, so anything older than this without an active
    /// session attached is fair game for the sweep.
    static let staleThreshold: TimeInterval = 24 * 60 * 60

    /// Wipe in-memory frame buffers and audio PCM, delete any temp file
    /// artifacts we wrote, and audit-log the result. Idempotent.
    @discardableResult
    static func purgeAll(sessionManager: SessionManager, reason: String) -> PurgeReport {
        let videoCount = sessionManager.allVideoFrameCount
        let screenCount = sessionManager.allScreenFrameCount
        let audioBytes = sessionManager.recordedAudioByteCount

        sessionManager.clearCapturedArtifacts()
        let tempDeleted = sweepTempFiles(maxAge: nil)

        let report = PurgeReport(
            videoFramesPurged: videoCount,
            screenFramesPurged: screenCount,
            audioBytesPurged: audioBytes,
            tempFilesDeleted: tempDeleted,
            timestamp: Date()
        )
        writeAudit(report: report, sessionId: sessionManager.session?.id, reason: reason)
        return report
    }

    /// Sweep stale temp files (older than `staleThreshold`) without
    /// touching in-memory state. Called on app foreground so a crashed
    /// or backgrounded session doesn't leave dictation WAVs lying around.
    @discardableResult
    static func purgeStaleArtifacts() -> Int {
        let deleted = sweepTempFiles(maxAge: staleThreshold)
        if deleted > 0 {
            AuditLogger.log(
                event: .localDataPurged,
                sessionId: nil,
                extra: [
                    "reason": "stale_sweep",
                    "temp_files_deleted": "\(deleted)",
                ]
            )
        }
        return deleted
    }

    // MARK: - Internals

    /// Delete temp files written by Aurion (audio recordings, export
    /// staging files). `maxAge == nil` means "delete everything we own";
    /// otherwise only files older than maxAge are removed.
    private static func sweepTempFiles(maxAge: TimeInterval?) -> Int {
        let fm = FileManager.default
        let tempDir = fm.temporaryDirectory
        guard let contents = try? fm.contentsOfDirectory(
            at: tempDir,
            includingPropertiesForKeys: [.contentModificationDateKey],
            options: [.skipsHiddenFiles]
        ) else {
            return 0
        }

        var deleted = 0
        let now = Date()
        for url in contents where isAurionArtifact(url) {
            if let maxAge {
                guard let modified = (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?.contentModificationDate,
                      now.timeIntervalSince(modified) > maxAge
                else { continue }
            }
            if (try? fm.removeItem(at: url)) != nil {
                deleted += 1
            }
        }
        return deleted
    }

    /// Conservative filter — only files matching our naming patterns get
    /// swept so we don't accidentally delete temp files owned by another
    /// process sharing the iOS temp dir.
    private static func isAurionArtifact(_ url: URL) -> Bool {
        let name = url.lastPathComponent
        return name.hasPrefix("aurion_note_")
            || name.hasPrefix("voice_enrollment-")
            || name.hasPrefix("aurion-")
            || (name.contains("recording") && name.hasSuffix(".wav"))
    }

    private static func writeAudit(report: PurgeReport, sessionId: String?, reason: String) {
        AuditLogger.log(
            event: .localDataPurged,
            sessionId: sessionId,
            extra: [
                "reason": reason,
                "video_frames": "\(report.videoFramesPurged)",
                "screen_frames": "\(report.screenFramesPurged)",
                "audio_bytes": "\(report.audioBytesPurged)",
                "temp_files_deleted": "\(report.tempFilesDeleted)",
            ]
        )
    }
}
