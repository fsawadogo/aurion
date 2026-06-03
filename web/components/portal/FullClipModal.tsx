"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { X } from "lucide-react";

/**
 * Full-screen video clip viewer for the web reviewer.
 *
 * Mirrors `ios/Aurion/Aurion/NoteReview/FullClipView.swift` — same
 * photo-viewer aesthetic (dark backdrop, centred player, timestamp +
 * duration in the chrome, gold close button) — adapted to the web
 * design system. The component is presentation-only: business
 * decisions (which clip URL to fetch, who owns the citation) live in
 * the parent (`ClaimChip` / `NoteSectionCard`).
 *
 * ## Affordances
 *
 * Three ways to dismiss, per modal best practice:
 *   1. Top-right Close button (matches the iOS toolbar trailing).
 *   2. Backdrop click.
 *   3. `Escape` key.
 *
 * Click inside the video container does NOT close — otherwise a stray
 * tap on the seek bar would dismiss mid-review.
 *
 * ## Empty state
 *
 * When `clipUrl` is null/empty the viewer renders the localized
 * "unavailable" copy instead of a broken `<video>` element. This
 * happens when:
 *   - Stage 2 is still running (the clip exists on S3 but the URL
 *     hasn't been signed into the response yet).
 *   - The clip was discarded (low-confidence / fallback to frame).
 *
 * ## Accessibility
 *
 * `role="dialog"` + `aria-modal="true"` + `aria-labelledby` wired to
 * the header so screen readers announce the modal correctly. The
 * `<video>` element is focusable so keyboard reviewers can space-bar
 * play/pause without leaving the modal.
 */

interface FullClipModalProps {
  /** Short-TTL signed S3 URL produced by `core/s3.generate_presigned_evidence_url`
   *  on the backend. Browser handles range requests directly. Pass
   *  `null` or `""` to show the localized unavailable copy. */
  clipUrl: string | null | undefined;
  /** Trigger timestamp in milliseconds (session-relative). Rendered
   *  M:SS in the header so the reviewer knows when the clip was
   *  recorded. */
  timestampMs: number | null | undefined;
  /** Encoded clip window length in milliseconds. Rendered as the
   *  duration pill ("7.0s"). 0 / null hides the pill. */
  durationMs: number | null | undefined;
  /** Modal-close callback fired by Escape / backdrop / button. */
  onClose: () => void;
}

export default function FullClipModal({
  clipUrl,
  timestampMs,
  durationMs,
  onClose,
}: FullClipModalProps) {
  const t = useTranslations("ClipModal");
  const videoRef = useRef<HTMLVideoElement>(null);

  // Escape closes the modal — single-purpose listener wired on mount,
  // torn down on unmount so multiple modals don't pile keyboard
  // handlers.
  useEffect(() => {
    function onKeydown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    }
    window.addEventListener("keydown", onKeydown);
    return () => window.removeEventListener("keydown", onKeydown);
  }, [onClose]);

  // Lock page scroll while the modal is open so the reviewer doesn't
  // see the underlying note jitter behind the dark backdrop.
  useEffect(() => {
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, []);

  const hasClip = !!clipUrl;
  const headerTimestamp = formatTimestamp(timestampMs);
  const durationLabel = formatDuration(durationMs);

  return (
    <div
      // Backdrop — click closes. role="presentation" so a screen
      // reader doesn't announce the wrapper as the dialog.
      role="presentation"
      data-testid="clip-modal-backdrop"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 backdrop-blur-sm animate-aurion-fade-in"
      onClick={onClose}
    >
      <div
        // Inner content — stops click propagation so taps on the
        // player + chrome don't close. The dialog semantics live here.
        role="dialog"
        aria-modal="true"
        aria-labelledby="clip-modal-title"
        data-testid="clip-modal-content"
        className="relative flex w-full h-full sm:h-auto sm:max-w-3xl sm:max-h-[90vh] flex-col bg-aurion-card sm:rounded-aurion-lg shadow-card overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header — timestamp + duration pill + close button, mirroring
            the iOS principal/trailing toolbar layout. */}
        <header className="flex items-center gap-3 px-4 py-3 border-b border-aurion-hairline bg-aurion-card">
          <h2
            id="clip-modal-title"
            className="text-aurion-headline text-aurion-primary font-mono"
          >
            {headerTimestamp ?? t("title")}
          </h2>
          {durationLabel && (
            <span
              className="inline-flex items-center px-2 py-0.5 rounded-full bg-gold-100 text-gold-700 text-aurion-micro font-mono"
              aria-label={t("duration", { seconds: durationLabel })}
            >
              {durationLabel}
            </span>
          )}
          <button
            type="button"
            onClick={onClose}
            className="ml-auto inline-flex items-center gap-1.5 rounded-aurion-sm px-2.5 py-1 text-aurion-caption font-medium text-gold-700 hover:bg-gold-50 transition-colors"
            aria-label={t("close")}
          >
            <X className="h-4 w-4" />
            {t("close")}
          </button>
        </header>

        {/* Body — video, or unavailable copy when clip_url is null. */}
        <div className="flex-1 flex items-center justify-center bg-black">
          {hasClip ? (
            <video
              ref={videoRef}
              src={clipUrl ?? undefined}
              controls
              autoPlay
              loop
              muted
              playsInline
              data-testid="clip-modal-video"
              aria-label={t("controls")}
              className="max-w-full max-h-full"
            />
          ) : (
            <div className="p-8 text-center">
              <p
                className="text-aurion-callout text-aurion-secondary max-w-sm mx-auto"
                data-testid="clip-modal-unavailable"
              >
                {t("unavailable")}
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** Session-relative timestamp in M:SS. Lifted from iOS
 *  `FullClipView.formatTimestamp` so the two viewers display the same
 *  anchor in the same format. Returns null when timestamp is missing
 *  so the header falls back to the localized title. */
function formatTimestamp(ms: number | null | undefined): string | null {
  if (ms == null || ms < 0) return null;
  const totalSec = Math.floor(ms / 1000);
  const mm = Math.floor(totalSec / 60);
  const ss = totalSec % 60;
  return `${mm}:${ss.toString().padStart(2, "0")}`;
}

/** Clip duration as "7.0s". Returns null when missing so the pill
 *  hides entirely rather than rendering "0.0s". */
function formatDuration(ms: number | null | undefined): string | null {
  if (ms == null || ms <= 0) return null;
  return `${(ms / 1000).toFixed(1)}s`;
}
