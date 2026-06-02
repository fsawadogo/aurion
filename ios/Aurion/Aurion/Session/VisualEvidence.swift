import Foundation

// MARK: - TriggerEvent (placeholder)

/// A single transcript-side trigger emitted by the (forthcoming) trigger
/// classifier. The classifier scans transcript segments for visual cue
/// language ("on examination", "you can see…", "show me your…") and emits
/// one of these per cue with the segment that produced it.
///
/// P1-4 only needs this as a value-typed handle so the `VisualEvidence`
/// enum can carry it alongside a clip URL. The real classifier ships in
/// a later PR; when it does, this struct stays the same shape but gains
/// a richer `kind` enum + classifier confidence. The fields here are the
/// minimum set every downstream consumer needs:
///
/// - `kind`: trigger taxonomy bucket — `"motion"`, `"rom"`, `"gait"`,
///   `"procedural"`, etc. The HYBRID dispatcher in P1-5 keys on this to
///   decide frame-vs-clip per `AppConfig.pipeline.clip_trigger_kinds`.
/// - `timestamp`: relative session time (seconds since session start) of
///   the triggering transcript segment's midpoint.
/// - `segmentId`: the transcript segment id (`seg_001` etc.) that anchors
///   the citation. Same id surface as today's `is_visual_trigger` segments.
///
/// **Do not** rename or reshape these without a coordinated change to the
/// dispatcher and the citation schema — they're load-bearing for the
/// audio<->visual anchor that powers every Stage 2 citation.
struct TriggerEvent: Sendable, Equatable {
    let kind: String
    let timestamp: TimeInterval
    let segmentId: String
}

// MARK: - VisualEvidence

/// Polymorphic visual evidence emitted by the capture pipeline for a single
/// trigger. The pipeline today only ever produces `.frame`; `.clip` is
/// reserved for the dual-mode work and only ever populated when the
/// dispatcher (P1-5) is enabled. The Liskov contract is that every
/// downstream consumer that reads a `.frame` keeps reading the same
/// `CapturedFrame` it always has — the enum is purely additive.
///
/// - `.frame(captured)`: an existing `CapturedFrame` (JPEG + timestamp).
///   Identical to the value the existing pipeline already publishes.
/// - `.clip(url, duration, trigger)`: a local file URL to a temp `.mp4`
///   produced by `VideoRingBuffer.extract(around:duration:)`. `duration`
///   is the requested window length in milliseconds (mirrors backend
///   schema's `duration_ms`). `trigger` carries the anchor that drove
///   the clip extraction so masking + upload can attribute it.
///
/// The MP4 file URL points at the app's temp directory; callers are
/// responsible for cleaning it up after upload / Stage 2 completion.
enum VisualEvidence {
    case frame(CapturedFrame)
    case clip(URL, duration: Int, trigger: TriggerEvent)
}
