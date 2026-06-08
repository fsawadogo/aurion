import Foundation

/// Drives the during-recording clip cadence floor (#324).
///
/// Why this exists: raw video frames live ONLY in `CaptureManager`'s
/// in-memory `clipRingBuffer`, which is cleared on stop. So a silent
/// physical exam — no transcript-side visual trigger — would otherwise
/// produce no clips at all, because the legacy post-stop clip extraction
/// reads the already-cleared ring. This driver fixes that by extracting a
/// clip every `cadenceSeconds` DURING recording.
///
/// (This does NOT violate the no-real-time-vision rule — that forbids
/// vision PROVIDER calls during recording, not on-device clip
/// extraction/masking/upload. Gemini captioning still runs post-stop in
/// the backend.)
///
/// Mechanics: a fine repeating timer fires at `min(N, 5)` s; on each fire
/// the driver emits a clip IFF the cadence interval `N` has elapsed since
/// the last extraction (the shared `lastClipExtractedAt` watermark) and
/// the per-session safety ceiling hasn't been hit.
///
/// Lifecycle mirrors the recording state machine — the owner
/// (`SessionManager`) drives these from `startRecording` / `pauseRecording`
/// / `resumeRecording` / `stopRecording`:
///   - `start()`      — create + schedule the timer (no-op if disabled).
///   - `suspend()`    — invalidate the timer; watermark + count preserved.
///   - `resume()`     — re-create the timer (same watermark, same count).
///   - `invalidate()` — tear down for good.
///
/// `cadenceSeconds == 0` ⇒ `start()` is a strict no-op (no timer is ever
/// created), preserving today's trigger-only behavior until AppConfig
/// pushes a non-zero `clip_cadence_seconds` to the device.
@MainActor
final class CadenceClipDriver {

    /// Cadence floor in seconds (AppConfig `clip_cadence_seconds`). Zero
    /// disables the driver entirely.
    let cadenceSeconds: Int

    /// Hard per-session ceiling on emitted cadence clips. Belt-and-braces
    /// against a pathologically long encounter flooding the backend; logged
    /// once when first hit. Deliberately NOT an AppConfig field — it's a
    /// safety valve, not a tuning knob.
    let perSessionCap: Int

    /// Async work performed on each due tick. Returns `true` when a clip was
    /// successfully extracted (so the watermark + emitted count advance);
    /// `false` when the tick was a no-op (ring couldn't satisfy the window,
    /// etc.). Masking/upload outcomes downstream of a successful extraction
    /// don't gate the return — once a clip is pulled, the cadence interval
    /// is considered satisfied so we don't hammer the ring within `N`.
    private let onTick: () async -> Bool

    /// The repeating timer. `nil` whenever the driver is suspended,
    /// invalidated, or disabled. `isActive` mirrors this.
    private var timer: Timer?

    /// Shared watermark — the reference clock used to decide whether a tick
    /// is "due". Any future iOS-side live trigger MUST bump this via
    /// `noteExtraction(at:)` so cadence ticks within `N` of a live-trigger
    /// clip are skipped (forward-compatible; today nothing else writes it,
    /// so cadence runs unopposed). `nil` until the first extraction.
    private(set) var lastClipExtractedAt: TimeInterval?

    /// Count of clips emitted this session — gated by `perSessionCap`.
    private(set) var clipsEmitted = 0

    /// Latch so the per-session cap is logged exactly once.
    private var capLogged = false

    /// Guards against a second tick starting while a slow
    /// extract → mask → upload cycle is still in flight. Set/cleared
    /// synchronously on the main actor so the check-then-set is atomic.
    private var tickInFlight = false

    init(
        cadenceSeconds: Int,
        perSessionCap: Int = 120,
        onTick: @escaping () async -> Bool
    ) {
        self.cadenceSeconds = cadenceSeconds
        self.perSessionCap = perSessionCap
        self.onTick = onTick
    }

    /// True while the repeating timer is scheduled. False when disabled,
    /// suspended, or invalidated.
    var isActive: Bool { timer != nil }

    /// Fine sub-interval the timer fires at, `min(N, 5)` s. The tick body
    /// then enforces the real `N`-second floor via the watermark, so a
    /// short sub-interval just makes the floor more responsive without
    /// over-emitting. Exposed for tests.
    var subIntervalSeconds: Double { Double(min(max(cadenceSeconds, 1), 5)) }

    // MARK: - Lifecycle

    /// Create + schedule the repeating timer. No-op when `cadenceSeconds`
    /// is 0 (feature off) or a timer is already running (idempotent).
    func start() {
        guard cadenceSeconds > 0 else { return }   // feature off → no timer
        guard timer == nil else { return }         // already scheduled
        let t = Timer(timeInterval: subIntervalSeconds, repeats: true) { [weak self] _ in
            // Timer fires on the main run loop; hop onto the main actor to
            // run the async tick. Fire-and-forget — `tickInFlight` prevents
            // overlap if a tick outruns the sub-interval.
            Task { @MainActor in await self?.fire() }
        }
        // .common so the timer keeps firing while the user interacts with
        // scrolling UI (default mode pauses during tracking run loops).
        RunLoop.main.add(t, forMode: .common)
        timer = t
    }

    /// Invalidate the timer but preserve the watermark + emitted count so a
    /// later `resume()` continues the same cadence. Used on pause.
    func suspend() {
        timer?.invalidate()
        timer = nil
    }

    /// Re-schedule after a `suspend()`. Same watermark, same count.
    func resume() {
        start()
    }

    /// Tear the driver down for good. Used on stop / session teardown.
    func invalidate() {
        timer?.invalidate()
        timer = nil
    }

    // MARK: - Tick

    /// Decide-and-emit for a single tick. `async` + `@discardableResult` so
    /// tests can drive ticks deterministically (`await driver.fire(now:)`)
    /// without waiting on the run loop. Returns whether a clip was emitted.
    ///
    /// Order of gates: feature-enabled → not-already-in-flight →
    /// under-cap → watermark-due. On a due tick it awaits `onTick`; only a
    /// `true` result advances the watermark (to the tick's `now`) and the
    /// emitted count.
    @discardableResult
    func fire(now: TimeInterval = Date.timeIntervalSinceReferenceDate) async -> Bool {
        guard cadenceSeconds > 0 else { return false }
        guard !tickInFlight else { return false }

        // Per-session safety cap — stop emitting after the ceiling; log once.
        guard clipsEmitted < perSessionCap else {
            if !capLogged {
                capLogged = true
                NSLog("[Aurion] cadence clip ceiling (%d) reached — suppressing further cadence clips this session (#324)", perSessionCap)
            }
            return false
        }

        // Watermark: skip if a clip (cadence OR a future live trigger) was
        // taken within `N` seconds of this tick.
        if let last = lastClipExtractedAt, now - last < Double(cadenceSeconds) {
            return false
        }

        tickInFlight = true
        defer { tickInFlight = false }

        let didExtract = await onTick()
        if didExtract {
            lastClipExtractedAt = now
            clipsEmitted += 1
        }
        return didExtract
    }

    /// Bump the shared watermark. Called internally after a successful
    /// cadence extraction (via `fire`) and intended to be called by any
    /// future iOS-side live trigger so cadence ticks within `N` of it are
    /// skipped (the "skip-if-already-covered" contract).
    func noteExtraction(at time: TimeInterval = Date.timeIntervalSinceReferenceDate) {
        lastClipExtractedAt = time
    }
}
