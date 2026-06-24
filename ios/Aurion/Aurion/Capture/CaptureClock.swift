import QuartzCore

/// Monotonic clock for all in-session capture timing — frame timestamps, the
/// `VideoRingBuffer` append/extract window, cadence-clip windows, and the
/// per-source `sessionStartTime` baseline.
///
/// Uses `CACurrentMediaTime()` (a `mach_absolute_time`-based clock) rather than
/// `Date`, because every capture timestamp is consumed as a session-RELATIVE
/// delta (`now - sessionStartTime`). `Date` is wall-clock and can jump
/// backward or forward mid-encounter — an NTP correction, a manual clock edit,
/// or a DST transition — which would misorder frames against the transcript or
/// shift a clip window. A monotonic clock makes those deltas immune to it.
///
/// Only DELTAS are meaningful (the epoch is arbitrary). Every capture site must
/// use THIS clock so the baseline, the ring's append timestamps, and the window
/// math all share one timeline.
@inline(__always)
func captureClockNow() -> TimeInterval { CACurrentMediaTime() }
