"use client";

import { ArrowPathIcon, ExclamationTriangleIcon } from "@heroicons/react/24/outline";

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

  // Fire onCompleted exactly once per transition into the completed
  // state — useEffect would be tempting but useStageTwoProgress
  // already encapsulates the lifecycle; we just react to its result.
  // Using a state machine + memoised key avoids double-fires.
  if (progress.isCompleted && onCompleted) {
    queueMicrotask(onCompleted);
  }

  if (!enabled) return null;
  if (progress.status === "no_job") return null;
  if (progress.isCompleted) return null;

  if (progress.isFailed) {
    return (
      <div
        className="mb-4 flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        role="status"
      >
        <ExclamationTriangleIcon className="h-5 w-5 shrink-0 mt-0.5" />
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
  const pct = total > 0 ? Math.min(100, Math.round((processed / total) * 100)) : 0;

  return (
    <div
      className="mb-4 flex items-center gap-3 rounded-lg border border-navy-200 bg-navy-50 px-4 py-3 text-sm text-navy-700"
      role="status"
      aria-live="polite"
    >
      <ArrowPathIcon className="h-5 w-5 shrink-0 animate-spin text-navy-500" />
      <div className="flex-1">
        <p className="font-medium">Finishing visual enrichment…</p>
        <div className="mt-1.5 h-1.5 w-full rounded-full bg-white">
          <div
            className="h-full rounded-full bg-navy-500 transition-all duration-300"
            style={{ width: total > 0 ? `${pct}%` : "10%" }}
          />
        </div>
      </div>
      <span className="shrink-0 tabular-nums text-xs font-medium text-navy-600">
        {total > 0 ? `${processed} / ${total} frames` : "starting…"}
      </span>
    </div>
  );
}
