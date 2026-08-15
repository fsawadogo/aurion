"use client";

import { AlertTriangle } from "lucide-react";
import { useEffect, useRef } from "react";
import ProgressBanner from "@/components/ui/ProgressBanner";
import { useStageTwoProgress } from "@/lib/portal-ws";

/**
 * Banner shown during Stage 2 visual enrichment. Pulls live progress
 * from the WebSocket (falls back to polling). Hidden when no Stage 2
 * job is running and after completion.
 *
 * Caller passes the session id; the component handles the lifecycle.
 * On failure surfaces a one-line error with a "retry" affordance —
 * but the retry is the page-level refresh button, not in this
 * component (this banner is intentionally read-only).
 */
interface StageTwoProgressBannerProps {
  sessionId: string;
  /** Disable subscription when the session is already past
   * REVIEW_COMPLETE — the WebSocket will never emit and we don't
   * want stale polling. */
  enabled: boolean;
  /** Called when status flips to `completed` so the parent can
   * refetch the note (Stage 2 added visual claims). */
  onCompleted?: () => void;
}

export default function StageTwoProgressBanner({
  sessionId,
  enabled,
  onCompleted,
}: StageTwoProgressBannerProps) {
  const progress = useStageTwoProgress(sessionId, enabled);

  // Fire onCompleted once per TRANSITION into the completed state.
  //
  // This used to be a bare `if (progress.isCompleted) queueMicrotask(...)` in
  // the render body. `completed` is not a moment, it is a resting state: once
  // Stage 2 finishes, the session sits in AWAITING_REVIEW (still `enabled`)
  // with the job row `completed` forever. So the callback fired on EVERY
  // render — and the parent's callback is `load()`, which calls setState
  // synchronously before awaiting. Render → fire → setState → render →
  // fire… an unthrottled loop, two fetches per turn, until Chrome ran out of
  // sockets (`ERR_INSUFFICIENT_RESOURCES`) and the WAF rate-limited the
  // clinician's IP. Opening any note whose Stage 2 had completed DoS'd the
  // API.
  //
  // The key is the ARMING mechanism, not the effect: `firedFor` latches the
  // session we already notified about and only re-arms when the completed
  // state goes away (new session, or a regenerate that starts a fresh job),
  // so a repeat completion still fires exactly once.
  const onCompletedRef = useRef(onCompleted);
  useEffect(() => {
    onCompletedRef.current = onCompleted;
  });

  const completionKey = enabled && progress.isCompleted ? sessionId : null;
  const firedFor = useRef<string | null>(null);
  useEffect(() => {
    if (completionKey === null) {
      firedFor.current = null; // re-arm for the next completion
      return;
    }
    if (firedFor.current === completionKey) return;
    firedFor.current = completionKey;
    onCompletedRef.current?.();
  }, [completionKey]);

  if (!enabled) return null;
  if (progress.status === "no_job") return null;
  if (progress.isCompleted) return null;

  if (progress.isFailed) {
    return (
      <div
        className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        role="status"
      >
        <AlertTriangle className="h-5 w-5 shrink-0 mt-0.5" />
        <div className="flex-1">
          <p className="font-medium">Stage 2 visual enrichment failed.</p>
          {progress.errorMessage && (
            <p className="mt-0.5 text-xs text-red-600">{progress.errorMessage}</p>
          )}
          <p className="mt-1 text-xs text-red-600">
            You can still approve the Stage 1 note — visual sections will
            stay marked as not captured.
          </p>
        </div>
      </div>
    );
  }

  const total = progress.framesTotal;
  const processed = progress.framesProcessed;

  // Determinate only once a frame count exists. Before that this used to show
  // a hardcoded 10% bar, which claimed progress it did not have — the shared
  // banner animates instead, which is the honest form of "starting…".
  return (
    <ProgressBanner
      message="Finishing visual enrichment…"
      percent={
        total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : undefined
      }
      detail={total > 0 ? `${processed} / ${total} frames` : "starting…"}
      testId="stage2-progress-banner"
    />
  );
}
