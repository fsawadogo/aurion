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
 * progress state to React. Falls back to polling `/stage2-status`
 * every 4 s if the socket can't connect or drops mid-session — the
 * iOS path stays on polling, so this is just a UX win for the web.
 */

import { useEffect, useRef, useState } from "react";

import { getStage2Status } from "@/lib/portal-api";
import type { NoteWebSocketMessage, Stage2Status } from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

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

    function pollOnce() {
      if (cancelled || !sessionId) return;
      void getStage2Status(sessionId)
        .then((s) => {
          applyStatus(s);
          if (s.status === "completed" || s.status === "failed") {
            stopPoll();
          }
        })
        .catch(() => {
          /* network blip; next interval will retry */
        });
    }

    function startPoll() {
      stopPoll();
      pollOnce();
      pollTimer.current = window.setInterval(pollOnce, 4000);
    }

    function stopPoll() {
      if (pollTimer.current != null) {
        window.clearInterval(pollTimer.current);
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
        if (!cancelled && pollTimer.current == null) startPoll();
      };

      ws.onclose = (ev) => {
        if (cancelled) return;
        // 1000 = normal closure (server-side intentional). Any other
        // close before we got `completed` means we should poll until
        // we know the job state.
        if (ev.code !== 1000 && pollTimer.current == null) startPoll();
      };
    }

    // Always seed with one poll so the UI doesn't sit empty waiting
    // for the first event.
    pollOnce();
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
