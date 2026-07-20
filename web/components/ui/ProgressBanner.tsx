import { RefreshCw } from "lucide-react";

/**
 * "Something is happening to this note right now" — the one progress banner.
 *
 * Extracted from `StageTwoProgressBanner`, which established the visual
 * language (spinning icon, filling track, live region). A second bespoke
 * banner for regeneration would have duplicated the a11y wiring and let the
 * two drift apart, so the presentation lives here and both callers use it.
 *
 * **Determinate vs indeterminate is a truthfulness decision, not a style one.**
 * Stage 2 knows how many frames it has processed, so it shows a real
 * percentage. Regeneration is a single POST that returns when it is done —
 * there is nothing to measure, so it animates without claiming a number.
 * Inventing a fake percentage would be worse than showing none.
 */
export interface ProgressBannerProps {
  /** The headline — what is happening, in the clinician's words. */
  message: string;
  /**
   * Completion 0–100 for determinate progress. Omit for indeterminate,
   * which animates a sliding bar instead of filling a fixed width.
   */
  percent?: number;
  /** Optional right-hand detail, e.g. "12 / 40 frames" or an elapsed time. */
  detail?: string;
  /** Test hook so callers can assert their own banner. */
  testId?: string;
}

export default function ProgressBanner({
  message,
  percent,
  detail,
  testId = "progress-banner",
}: ProgressBannerProps) {
  const determinate = typeof percent === "number";
  const clamped = determinate ? Math.min(100, Math.max(0, percent)) : 0;

  return (
    <div
      className="mb-4 flex items-center gap-3 rounded-lg border border-navy-200 bg-navy-50 px-4 py-3 text-sm text-navy-700"
      // `role="status"` + polite live region: a screen-reader user is told the
      // note is being replaced. Without it they get a silent stale document —
      // which is the failure this whole slice exists to prevent.
      role="status"
      aria-live="polite"
      data-testid={testId}
    >
      <RefreshCw className="h-5 w-5 shrink-0 animate-spin text-navy-500" />
      <div className="flex-1">
        <p className="font-medium">{message}</p>
        <div
          className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-white"
          role="progressbar"
          aria-valuenow={determinate ? clamped : undefined}
          aria-valuemin={determinate ? 0 : undefined}
          aria-valuemax={determinate ? 100 : undefined}
        >
          <div
            className={
              determinate
                ? "h-full rounded-full bg-navy-500 transition-all duration-300"
                : "h-full w-1/3 rounded-full bg-navy-500 animate-aurion-indeterminate"
            }
            style={determinate ? { width: `${clamped}%` } : undefined}
          />
        </div>
      </div>
      {detail && (
        <span className="shrink-0 tabular-nums text-xs font-medium text-navy-600">
          {detail}
        </span>
      )}
    </div>
  );
}
