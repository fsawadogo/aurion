import { describe, expect, it, vi, beforeEach } from "vitest";
import { act, render } from "@testing-library/react";
import { useState } from "react";

/**
 * The note review page DoS'd our own API.
 *
 * Found on session 9b78a2ec (the bunion follow-up) — ~2000 console errors,
 * every one `net::ERR_INSUFFICIENT_RESOURCES` on repeated GETs to
 * `/notes/{id}/detail` and `/sessions/{id}`. Not a server crash: the browser
 * ran out of sockets, the API shed load with 503s, and the WAF rate-limited
 * the clinician's IP.
 *
 * The cause was one line in the render body of StageTwoProgressBanner:
 *
 *     if (progress.isCompleted && onCompleted) queueMicrotask(onCompleted);
 *
 * `completed` is a RESTING state, not a moment. After Stage 2 finishes the
 * session sits in AWAITING_REVIEW — still `enabled` — with the job row
 * `completed` indefinitely. The parent's callback is `load()`, which calls
 * setState synchronously before it awaits, so: render → fire → setState →
 * render → fire, unthrottled, two fetches per turn. Every visit to a note
 * whose Stage 2 had completed did this.
 *
 * These tests pin the property that actually matters — fire once per
 * TRANSITION — and the loop itself, so a callback that re-renders the parent
 * can never again turn this banner into a request pump.
 */

const progressMock = vi.fn();
vi.mock("@/lib/portal-ws", () => ({
  useStageTwoProgress: (...args: unknown[]) => progressMock(...args),
}));

import StageTwoProgressBanner from "@/components/portal/StageTwoProgressBanner";

const COMPLETED = {
  status: "completed" as const,
  framesProcessed: 17,
  framesTotal: 17,
  isCompleted: true,
  isFailed: false,
  errorMessage: null,
};

const RUNNING = { ...COMPLETED, status: "running" as const, isCompleted: false };

function setProgress(state: unknown) {
  progressMock.mockReturnValue(state);
}

/** Drain pending microtasks and effects before asserting.
 *
 * The original bug fired through `queueMicrotask`, so a synchronous assertion
 * would read the counter at 0 and "fail" for the wrong reason — it would look
 * like the callback never fired rather than like it fired forever. Draining
 * first means these tests observe what the component actually did, runaway
 * loop included. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

beforeEach(() => {
  progressMock.mockReset();
});

describe("StageTwoProgressBanner completion callback", () => {
  it("fires once when the job is already completed on first render", async () => {
    setProgress(COMPLETED);
    const onCompleted = vi.fn();

    render(
      <StageTwoProgressBanner sessionId="s1" enabled onCompleted={onCompleted} />,
    );
    await settle();

    expect(onCompleted).toHaveBeenCalledTimes(1);
  });

  it("does not re-fire when the parent re-renders it", async () => {
    setProgress(COMPLETED);
    const onCompleted = vi.fn();

    const { rerender } = render(
      <StageTwoProgressBanner sessionId="s1" enabled onCompleted={onCompleted} />,
    );
    for (let i = 0; i < 5; i++) {
      // A fresh inline arrow each time, exactly as the page passes it — an
      // unstable callback identity must not read as a new completion.
      rerender(
        <StageTwoProgressBanner
          sessionId="s1"
          enabled
          onCompleted={() => onCompleted()}
        />,
      );
    }
    await settle();

    expect(onCompleted).toHaveBeenCalledTimes(1);
  });

  it("does not loop when the callback itself re-renders the parent", async () => {
    // The real shape of the bug: `load()` sets state, which re-renders this
    // banner. If completion re-fires on that render, it never terminates.
    setProgress(COMPLETED);
    const loads = vi.fn();

    function Page() {
      const [, setTick] = useState(0);
      return (
        <StageTwoProgressBanner
          sessionId="s1"
          enabled
          onCompleted={() => {
            loads();
            // Bound the test itself: a regression would otherwise spin the
            // runner forever instead of reporting the loop.
            if (loads.mock.calls.length < 50) setTick((n) => n + 1);
          }}
        />
      );
    }

    render(<Page />);
    await settle();

    expect(loads).toHaveBeenCalledTimes(1);
  });

  it("never fires while the subscription is disabled", async () => {
    setProgress(COMPLETED);
    const onCompleted = vi.fn();

    render(
      <StageTwoProgressBanner
        sessionId="s1"
        enabled={false}
        onCompleted={onCompleted}
      />,
    );
    await settle();

    expect(onCompleted).not.toHaveBeenCalled();
  });

  it("fires again for a genuinely new completion", async () => {
    // A regenerate starts a fresh Stage 2 run: completed → running →
    // completed. The parent must refetch both times, so latching on "already
    // fired once" would be wrong — it re-arms when completion drops away.
    setProgress(COMPLETED);
    const onCompleted = vi.fn();

    const { rerender } = render(
      <StageTwoProgressBanner sessionId="s1" enabled onCompleted={onCompleted} />,
    );
    await settle();
    expect(onCompleted).toHaveBeenCalledTimes(1);

    setProgress(RUNNING);
    rerender(
      <StageTwoProgressBanner sessionId="s1" enabled onCompleted={onCompleted} />,
    );
    await settle();
    expect(onCompleted).toHaveBeenCalledTimes(1);

    setProgress(COMPLETED);
    rerender(
      <StageTwoProgressBanner sessionId="s1" enabled onCompleted={onCompleted} />,
    );
    await settle();
    expect(onCompleted).toHaveBeenCalledTimes(2);
  });

  it("fires for a different session", async () => {
    setProgress(COMPLETED);
    const onCompleted = vi.fn();

    const { rerender } = render(
      <StageTwoProgressBanner sessionId="s1" enabled onCompleted={onCompleted} />,
    );
    rerender(
      <StageTwoProgressBanner sessionId="s2" enabled onCompleted={onCompleted} />,
    );
    await settle();

    expect(onCompleted).toHaveBeenCalledTimes(2);
  });
});
