import Foundation

/// Why a cadence clip never reached S3 (#390).
///
/// Raw values are the WIRE enum — they MUST stay byte-identical to the
/// backend `ClipDropReason` in `backend/app/api/v1/clips.py`. The backend
/// rejects an unknown reason with a 422 and the server-only
/// `server_s3_put_failed` with a 400, so a drift here surfaces loudly in
/// CI rather than silently mislabelling drops.
///
/// The first three are per-tick drops inside `emitCadenceClip`; the last
/// four are the once-per-session driver-not-started reasons inside
/// `startCadenceDriverIfEnabled`. `server_s3_put_failed` is deliberately
/// absent — a device cannot observe a server-side S3 failure, so it is
/// never emitted from iOS.
enum ClipDropReason: String {
    // Per-tick (emitCadenceClip)
    case ringEmpty = "ring_empty"
    case maskingFailed = "masking_failed"
    case uploadFailed = "upload_failed"
    // Driver-not-started (startCadenceDriverIfEnabled)
    case cadenceSecondsZero = "cadence_seconds_zero"
    case modeNotClipsOrHybrid = "mode_not_clips_or_hybrid"
    case videoSourceNotBuiltin = "video_source_not_builtin"
    case captureModeNotMultimodal = "capture_mode_not_multimodal"
}

/// Per-session clip-pipeline counters, flushed as a single
/// `CLIP_PIPELINE_SUMMARY` beacon on stop (#390).
///
/// Why aggregate rather than beacon-per-tick: a per-tick drop (especially
/// `ring_empty` during camera warm-up) can fire every sub-interval, so
/// emitting a network beacon for each would flood the audit log
/// mid-recording. The once-per-session driver-not-started reasons DO get an
/// immediate `CLIP_DROPPED` beacon (they fire at most once); per-tick drops
/// are counted here and reported in aggregate. Together with the
/// record-start `CLIP_CONFIG_SNAPSHOT`, this lets the server tell
/// "never attempted" from "attempted but dropped client-side" — the
/// ambiguity that cost a full investigation in #324.
///
/// Value type, owned by `SessionManager` (a `@MainActor`), reset at every
/// record start. All mutation is on the main actor, so no synchronisation
/// is needed.
struct ClipPipelineCounters {
    var clipsExtracted = 0
    var clipsMasked = 0
    var clipsUploaded = 0
    var dropsRingEmpty = 0
    var dropsMaskingFailed = 0
    var dropsUploadFailed = 0

    /// Total client-side drops across all per-tick reasons.
    var clipsDropped: Int { dropsRingEmpty + dropsMaskingFailed + dropsUploadFailed }

    mutating func reset() { self = ClipPipelineCounters() }

    /// Build the `CLIP_PIPELINE_SUMMARY` beacon body for
    /// `APIClient.recordClipTelemetry`. `ringFramesAppended` is read from
    /// the live ring at stop (nil for audio-only sessions, where there is
    /// no video ring) and is omitted from the body when nil so the backend
    /// whitelist accepts the subset.
    func summaryBody(ringFramesAppended: Int?) -> [String: Any] {
        var body: [String: Any] = [
            "kind": "summary",
            "clips_extracted": clipsExtracted,
            "clips_masked": clipsMasked,
            "clips_uploaded": clipsUploaded,
            "clips_dropped": clipsDropped,
            "drops_ring_empty": dropsRingEmpty,
            "drops_masking_failed": dropsMaskingFailed,
            "drops_upload_failed": dropsUploadFailed,
        ]
        if let ringFramesAppended {
            body["ring_frames_appended"] = ringFramesAppended
        }
        return body
    }
}
