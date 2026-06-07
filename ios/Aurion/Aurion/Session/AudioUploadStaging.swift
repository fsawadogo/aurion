import Foundation

/// Single source of truth for the on-disk audio-upload staging location.
///
/// The active upload's WAV is written under Application Support (not the OS
/// temp dir) so a discretionary sandbox sweep can't yank the bytes between
/// `submitAudio` and a Retry. One file per session (`<sessionId>.wav`).
///
/// Extracted so `SessionManager` (writer) and `LocalDataPurger` (orphan
/// sweep + discard purge, #282) agree on exactly one path — a crash loses
/// the in-memory `recordedAudioFileURL`, so the purger must be able to find
/// staged WAVs by convention, not by a live reference.
enum AudioUploadStaging {
    static var directory: URL {
        let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        return base.appendingPathComponent("AudioUploadStaging", isDirectory: true)
    }

    static func fileURL(sessionId: String) -> URL {
        directory.appendingPathComponent("\(sessionId).wav")
    }
}
