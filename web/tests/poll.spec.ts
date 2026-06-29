import { describe, expect, it } from "vitest";

import { MAX_POLL_ERRORS, shouldStopPolling } from "@/lib/poll";

describe("shouldStopPolling (video-import poll give-up)", () => {
  it("keeps polling below the consecutive-error cap", () => {
    expect(shouldStopPolling(0)).toBe(false);
    expect(shouldStopPolling(1)).toBe(false);
    expect(shouldStopPolling(MAX_POLL_ERRORS - 1)).toBe(false);
  });

  it("stops once errors reach the cap (no infinite spin)", () => {
    expect(shouldStopPolling(MAX_POLL_ERRORS)).toBe(true);
    expect(shouldStopPolling(MAX_POLL_ERRORS + 3)).toBe(true);
  });
});
