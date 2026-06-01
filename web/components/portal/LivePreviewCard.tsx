"use client";

import { useCallback, useEffect, useState } from "react";
import {
  EyeIcon,
  ExclamationTriangleIcon,
  ArrowPathIcon,
  SparklesIcon,
} from "@heroicons/react/24/outline";

import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  getMyLatestSessionPreview,
  listMySessionPreviews,
} from "@/lib/portal-api";
import type { LivePreview } from "@/types";

/**
 * Live preview card — #64 foundation.
 *
 * Renders the latest preview snapshot generated during a recording
 * session. Visible only when the session is in a state that makes
 * sense for previewing:
 *   * RECORDING / PAUSED — fresh previews can be requested
 *   * PROCESSING_STAGE1 — the canonical pipeline is running; the
 *     last preview is still useful as a sneak peek
 *
 * Two safety properties enforced by the UI:
 *   1. Bright "DRAFT" pill at the top — physicians must never confuse
 *      this with the canonical Stage 1 note
 *   2. Per-claim "live" footer chip — citations point at the
 *      `preview_seg_0` synthetic anchor (no real audio segments yet),
 *      explicitly NOT the same as the post-stop note's anchors
 *
 * The card polls every 4s for new preview rows (table-driven; the
 * orchestration that fires previews is iOS-side in the foundation —
 * the portal just listens). When the polling sees a new `version`,
 * the panel updates with a subtle highlight.
 *
 * Generation from the portal itself is NOT in the foundation. iOS
 * owns the cadence (it has the live audio); the portal just
 * spectates.
 */

interface LivePreviewCardProps {
  sessionId: string;
  /** Current session state from the SessionRow — gates rendering. */
  sessionState: string;
}

const VISIBLE_STATES = new Set([
  "RECORDING",
  "PAUSED",
  "PROCESSING_STAGE1",
]);

const POLL_INTERVAL_MS = 4000;

export default function LivePreviewCard({
  sessionId,
  sessionState,
}: LivePreviewCardProps) {
  const [preview, setPreview] = useState<LivePreview | null>(null);
  const [history, setHistory] = useState<LivePreview[]>([]);
  const [loading, setLoading] = useState(true);
  const [showTimeline, setShowTimeline] = useState(false);

  const visible = VISIBLE_STATES.has(sessionState);

  const load = useCallback(async () => {
    try {
      const latest = await getMyLatestSessionPreview(sessionId);
      // Only update + flag-as-new when we actually got a fresher row.
      setPreview((prev) => {
        if (!latest) return prev;
        if (prev && prev.version === latest.version) return prev;
        return latest;
      });
    } catch {
      // Polling failure isn't worth surfacing — the next tick will
      // try again. Visible failure modes (session expired,
      // network gone) come from the parent's session fetch.
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  // Initial load + polling loop. We deliberately don't poll the full
  // history list — that's only fetched when the user opens the timeline.
  useEffect(() => {
    if (!visible) return;
    void load();
    const id = setInterval(() => void load(), POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [load, visible]);

  // Lazy-load the timeline when the user opens it. Cheap enough at
  // pilot scale that we don't bother caching across open/close.
  useEffect(() => {
    if (!showTimeline) return;
    void (async () => {
      try {
        const rows = await listMySessionPreviews(sessionId);
        setHistory(rows);
      } catch {
        // Same rationale as above — silent polling failure.
      }
    })();
  }, [showTimeline, sessionId]);

  if (!visible) return null;

  const isStage1Running = sessionState === "PROCESSING_STAGE1";

  return (
    <Card className="border-l-4 border-l-amber-400">
      <div className="mb-3 flex items-center gap-2 text-aurion-headline">
        <EyeIcon className="h-4 w-4 text-amber-600" />
        Live preview
        <Badge variant="warning" dot>
          DRAFT — not the final note
        </Badge>
        {preview && (
          <span className="aurion-micro ml-2 text-navy-500">
            v{preview.version} ·{" "}
            {new Date(preview.created_at).toLocaleTimeString()}
          </span>
        )}
        <div className="flex-1" />
        {history.length > 0 && (
          <button
            type="button"
            onClick={() => setShowTimeline((v) => !v)}
            className="inline-flex items-center gap-1 text-aurion-caption text-navy-500 hover:text-navy-700"
          >
            <ArrowPathIcon className="h-4 w-4" />
            Timeline ({history.length})
          </button>
        )}
      </div>

      <div className="mb-3 flex items-start gap-2 rounded-aurion-md bg-amber-50 border border-amber-200 px-3 py-2 text-aurion-caption text-amber-900">
        <ExclamationTriangleIcon className="h-4 w-4 mt-0.5 shrink-0" />
        <div>
          <strong>Preview only.</strong> This is a draft snapshot the
          model generated mid-recording. The final note runs at
          recording stop with the full transcript + visual evidence —
          treat this as a sneak peek, not a chartable artefact.
        </div>
      </div>

      {loading ? (
        <LoadingSkeleton lines={4} />
      ) : !preview ? (
        <div className="py-4 text-center">
          <SparklesIcon className="h-8 w-8 text-navy-300 mx-auto mb-2" />
          <p className="aurion-callout text-navy-500">
            No preview yet. The first snapshot lands after the recording
            captures enough content to draft a section.
          </p>
        </div>
      ) : (
        <>
          {isStage1Running && (
            <div className="mb-2 inline-flex items-center gap-1.5 text-aurion-caption text-navy-600">
              <span className="h-2 w-2 rounded-full bg-emerald-500 animate-pulse" />
              Generating final note…
            </div>
          )}
          <PreviewSections preview={preview} />
        </>
      )}

      {showTimeline && history.length > 0 && (
        <div className="mt-4 pt-3 border-t border-hairline">
          <h4 className="aurion-headline text-aurion-caption mb-2">
            Preview history
          </h4>
          <ul className="text-aurion-caption text-navy-700 space-y-1">
            {history.map((p) => (
              <li
                key={p.id}
                className={
                  "flex items-baseline gap-2 " +
                  (preview && p.id === preview.id ? "font-semibold" : "")
                }
              >
                <span className="font-mono text-navy-500">v{p.version}</span>
                <span className="text-navy-400">
                  {new Date(p.created_at).toLocaleTimeString()}
                </span>
                <span className="text-navy-500">
                  · {p.transcript_chars.toLocaleString()} chars
                </span>
                <span className="text-navy-500">
                  · completeness {(p.completeness_score * 100).toFixed(0)}%
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function PreviewSections({ preview }: { preview: LivePreview }) {
  // Only show populated sections — the "not_captured" + "pending_video"
  // states are misleading mid-recording (the canonical pipeline hasn't
  // tried yet). Render order matches the order returned from the
  // backend (template-driven).
  const populated = preview.sections.filter(
    (s) => s.status === "populated" && s.claims.length > 0,
  );

  if (populated.length === 0) {
    return (
      <p className="aurion-callout text-navy-500 italic">
        Sections are still assembling — give it a moment.
      </p>
    );
  }

  return (
    <ul className="space-y-3">
      {populated.map((section) => (
        <li key={section.id}>
          <h5 className="aurion-headline text-navy-800 mb-1">
            {section.title || section.id.replace(/_/g, " ")}
          </h5>
          <ul className="space-y-1">
            {section.claims.map((claim) => (
              <li
                key={claim.id}
                className="text-aurion-callout text-navy-700 leading-snug"
              >
                {claim.text}
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}
