import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { renderHook } from "@testing-library/react";

/**
 * WAF-BACKOFF — the Stage-2 status poll must back off and give up on repeated
 * failure, not hammer a fixed 4s interval.
 *
 * Found live: a per-IP AWS WAF rate limit (2000/5min) would trip, then 403
 * the whole origin — and this poll's old fixed 4s interval kept hitting it,
 * holding the rate window full so it never drained. The page was keeping
 * itself blocked. Backoff + a give-up let the window recover.
 */

vi.mock("@/lib/portal-api", () => ({
  getStage2Status: vi.fn(),
}));

import { getStage2Status } from "@/lib/portal-api";
import { useStageTwoProgress } from "@/lib/portal-ws";

// The hook opens a WebSocket; stub it so construction succeeds and it never
// emits. The hook also seeds a poll directly, so the poll path runs either
// way — we don't need the socket to error.
class NoopWebSocket {
  onmessage: ((e: MessageEvent) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: ((e: CloseEvent) => void) | null = null;
  close() {}
}

beforeEach(() => {
  vi.useFakeTimers();
  (globalThis as unknown as { WebSocket: unknown }).WebSocket = NoopWebSocket;
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("Stage-2 poll backoff", () => {
  it("stops polling after repeated failures instead of hammering forever", async () => {
    // Every status call fails — the exact condition (origin 403ing) the fix is
    // for.
    vi.mocked(getStage2Status).mockRejectedValue(new Error("403"));

    renderHook(() => useStageTwoProgress("sess-1", true));

    // Drain well past the backoff ceiling (cap 60s × several). A fixed 4s
    // interval would rack up ~75 calls over 5 minutes; the give-up caps it.
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000);

    const callsAfterFiveMinutes = vi.mocked(getStage2Status).mock.calls.length;
    // Base + doubling to the cap, giving up at POLL_MAX_FAILURES=6 → 6 calls.
    expect(callsAfterFiveMinutes).toBeLessThanOrEqual(6);

    // And it STAYS stopped — no further calls once given up.
    await vi.advanceTimersByTimeAsync(5 * 60 * 1000);
    expect(vi.mocked(getStage2Status).mock.calls.length).toBe(
      callsAfterFiveMinutes,
    );
  });

  it("keeps polling at the base cadence while the origin is healthy", async () => {
    // Healthy = a running job; the poll should keep going at ~4s, not back off.
    vi.mocked(getStage2Status).mockResolvedValue({
      status: "running",
      frames_processed: 1,
      error_message: null,
    } as never);

    renderHook(() => useStageTwoProgress("sess-1", true));

    await vi.advanceTimersByTimeAsync(20_000); // ~5 polls at 4s
    const calls = vi.mocked(getStage2Status).mock.calls.length;
    // Healthy cadence keeps ticking — several calls, not a give-up.
    expect(calls).toBeGreaterThanOrEqual(4);
  });

  it("stops polling once the job completes", async () => {
    vi.mocked(getStage2Status).mockResolvedValue({
      status: "completed",
      frames_processed: 10,
      error_message: null,
    } as never);

    renderHook(() => useStageTwoProgress("sess-1", true));

    await vi.advanceTimersByTimeAsync(1000);
    const afterComplete = vi.mocked(getStage2Status).mock.calls.length;
    await vi.advanceTimersByTimeAsync(60_000);
    // No further polling after a terminal state.
    expect(vi.mocked(getStage2Status).mock.calls.length).toBe(afterComplete);
  });
});
