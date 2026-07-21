/**
 * WebSocket helpers for the clinician portal.
 *
 * The backend (PR-A/B) exposes a single channel at
 * `ws://host/ws/notes/{session_id}` carrying three event types:
 *
 *   { event: "stage1_delivered", note }
 *   { event: "stage2_delivered", note }
 *   { event: "stage2_progress", frames_processed, frames_total }
 *
 * `useStageTwoProgress` subscribes to that channel and surfaces the
 * progress state to React. Falls back to polling `/stage2-status` if the
 * socket can't connect or drops mid-session — with exponential backoff and
 * a give-up (NOT a fixed interval), so a blocked origin isn't kept blocked
 * by our own polling. The iOS path stays on its own polling.
 */

import { useEffect, useRef, useState } from "react";

import { getStage2Status } from "@/lib/portal-api";
import type { NoteWebSocketMessage, Stage2Status } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/** Stage-2 status polling cadence (WS-fallback). Backoff, not a fixed
 *  interval: base delay, doubling per consecutive failure up to a cap, then
 *  give up so a blocked origin (e.g. a tripped WAF rate limit) isn't kept
 *  blocked by our own polling. */
const POLL_BASE_MS = 4000;
const POLL_MAX_MS = 60000;
const POLL_MAX_FAILURES = 6;

function wsBaseFromApi(): string {
  // http(s)://host:port  →  ws(s)://host:port
  try {
    const url = new URL(API_BASE);
    url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
    return url.toString().replace(/\/$/, "");
  } catch {
    return "ws://localhost:8000";
  }
}

interface ProgressState {
  status: Stage2Status["status"];
  framesProcessed: number;
  framesTotal: number;
  /** True when status is `completed` and a new note version landed. */
  isCompleted: boolean;
  /** True when status is `failed`. */
  isFailed: boolean;
  /** Best-effort error string surfaced from the backend. */
  errorMessage: string | null;
}

const INITIAL: ProgressState = {
  status: "no_job",
  framesProcessed: 0,
  framesTotal: 0,
  isCompleted: false,
  isFailed: false,
  errorMessage: null,
};

/**
 * Subscribe to Stage 2 progress for a session. Returns a snapshot
 * that updates on each WebSocket event. When the socket fails to
 * open or closes unexpectedly, falls back to polling
 * /stage2-status every 4 s — the same cadence iOS uses.
 *
 * Caller can pass `enabled=false` to skip the subscription (e.g. when
 * the session is already past `REVIEW_COMPLETE`).
 */
export function useStageTwoProgress(
  sessionId: string | null | undefined,
  enabled = true,
): ProgressState {
  const [state, setState] = useState<ProgressState>(INITIAL);
  const wsRef = useRef<WebSocket | null>(null);
  const pollTimer = useRef<number | null>(null);

  useEffect(() => {
    if (!sessionId || !enabled) {
      setState(INITIAL);
      return;
    }

    let cancelled = false;

    function applyStatus(s: Stage2Status) {
      if (cancelled) return;
      setState({
        status: s.status,
        framesProcessed: s.frames_processed ?? 0,
        framesTotal: 0, // status endpoint doesn't carry total — use last WS value
        isCompleted: s.status === "completed",
        isFailed: s.status === "failed",
        errorMessage: s.error_message ?? null,
      });
    }

    // Self-scheduling poll with exponential backoff, NOT a fixed interval.
    // A fixed 4s interval that catches-and-ignores errors keeps hammering a
    // blocked origin forever — and when the block is a per-IP WAF rate limit,
    // our own polling is what holds the window full so it never drains. Back
    // off on consecutive failures and give up after a few, so the origin can
    // recover; a page reload restarts a healthy poll.
    let pollActive = false;
    let pollFailures = 0;

    function scheduleNextPoll(delayMs: number) {
      pollTimer.current = window.setTimeout(runPoll, delayMs);
    }

    function runPoll() {
      pollTimer.current = null;
      if (cancelled || !sessionId) {
        pollActive = false;
        return;
      }
      void getStage2Status(sessionId)
        .then((s) => {
          pollFailures = 0;
          applyStatus(s);
          if (s.status === "completed" || s.status === "failed") {
            stopPoll();
            return;
          }
          scheduleNextPoll(POLL_BASE_MS);
        })
        .catch(() => {
          pollFailures += 1;
          if (pollFailures >= POLL_MAX_FAILURES) {
            // Stop hammering — let the rate window drain. The user can reload
            // to resume; the note itself is unaffected (Stage 2 runs server
            // side regardless of whether we're watching).
            stopPoll();
            return;
          }
          scheduleNextPoll(
            Math.min(POLL_BASE_MS * 2 ** pollFailures, POLL_MAX_MS),
          );
        });
    }

    function startPoll() {
      // Self-guarding so the WS error/close fallbacks can call it freely
      // without stacking timers.
      if (pollActive) return;
      pollActive = true;
      pollFailures = 0;
      runPoll();
    }

    function stopPoll() {
      pollActive = false;
      if (pollTimer.current != null) {
        window.clearTimeout(pollTimer.current);
        pollTimer.current = null;
      }
    }

    function openSocket() {
      const ws = new WebSocket(`${wsBaseFromApi()}/ws/notes/${sessionId}`);
      wsRef.current = ws;

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data) as NoteWebSocketMessage;
          if (cancelled) return;
          if (msg.event === "stage2_progress") {
            setState((prev) => ({
              ...prev,
              status: "running",
              framesProcessed: msg.frames_processed,
              framesTotal: msg.frames_total,
              isCompleted: false,
              isFailed: false,
            }));
          } else if (msg.event === "stage2_delivered") {
            setState((prev) => ({
              ...prev,
              status: "completed",
              framesProcessed: prev.framesTotal || prev.framesProcessed,
              isCompleted: true,
              isFailed: false,
              errorMessage: null,
            }));
          }
        } catch {
          /* malformed frame — ignore */
        }
      };

      ws.onerror = () => {
        // Socket couldn't open or hit an error; fall back to polling
        // so the user still sees something move.
        if (!cancelled) startPoll();
      };

      ws.onclose = (ev) => {
        if (cancelled) return;
        // 1000 = normal closure (server-side intentional). Any other
        // close before we got `completed` means we should poll until
        // we know the job state.
        if (ev.code !== 1000) startPoll();
      };
    }

    // Seed with one poll so the UI doesn't sit empty waiting for the
    // first event; startPoll self-guards against the WS fallbacks.
    startPoll();
    openSocket();

    return () => {
      cancelled = true;
      stopPoll();
      if (wsRef.current) {
        try {
          wsRef.current.close(1000, "component unmount");
        } catch {
          /* already closed */
        }
        wsRef.current = null;
      }
    };
  }, [sessionId, enabled]);

  return state;
}
