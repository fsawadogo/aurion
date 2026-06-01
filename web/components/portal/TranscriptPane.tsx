"use client";

import { forwardRef, useImperativeHandle, useRef } from "react";
import type { CitationExpansion } from "@/types";

/**
 * Left-column transcript pane for the note review screen.
 *
 * Renders the citations dict (keyed by claim id) as a chronological
 * list of transcript snippets — each snippet anchored to its source
 * id so the note pane can scroll-and-highlight a specific source on
 * claim click.
 *
 * The pane only renders sources actually cited by the current note;
 * un-cited transcript segments are omitted. That keeps the pane
 * scannable for review (vs the full timestamped transcript dump
 * which is much longer).
 */

export interface TranscriptPaneHandle {
  scrollToSource: (sourceId: string) => void;
}

interface TranscriptPaneProps {
  /** Map of claim_id → citation expansion. */
  citations: Record<string, CitationExpansion>;
  /** Currently highlighted source id, drives the amber underline. */
  highlightedSourceId?: string | null;
}

interface TranscriptItem {
  sourceId: string;
  sourceType: string;
  text: string;
  speaker?: string | null;
  startMs?: number | null;
}

const TranscriptPane = forwardRef<TranscriptPaneHandle, TranscriptPaneProps>(
  function TranscriptPane({ citations, highlightedSourceId }, ref) {
    const containerRef = useRef<HTMLDivElement>(null);
    const itemRefs = useRef<Map<string, HTMLLIElement>>(new Map());

    useImperativeHandle(ref, () => ({
      scrollToSource(sourceId: string) {
        const el = itemRefs.current.get(sourceId);
        if (el) {
          el.scrollIntoView({ behavior: "smooth", block: "center" });
        }
      },
    }));

    const items = derefSources(citations);

    return (
      <div
        ref={containerRef}
        className="h-full overflow-y-auto rounded-lg border border-gray-200 bg-white px-4 py-3"
      >
        {items.length === 0 ? (
          <p className="text-sm text-gray-500 italic">
            No cited transcript segments yet.
          </p>
        ) : (
          <ul className="space-y-3">
            {items.map((item) => {
              const isActive = item.sourceId === highlightedSourceId;
              return (
                <li
                  key={item.sourceId}
                  ref={(el) => {
                    if (el) itemRefs.current.set(item.sourceId, el);
                    else itemRefs.current.delete(item.sourceId);
                  }}
                  className={
                    "rounded-md border px-3 py-2 transition-all duration-200 " +
                    (isActive
                      ? "border-gold-300 bg-gold-50/60 ring-1 ring-gold-200"
                      : "border-transparent hover:bg-gray-50")
                  }
                >
                  <div className="flex items-baseline gap-2 mb-1">
                    {item.speaker && (
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-navy-600">
                        {item.speaker}
                      </span>
                    )}
                    {item.startMs != null && (
                      <span className="text-[10px] tabular-nums text-gray-500">
                        {formatMs(item.startMs)}
                      </span>
                    )}
                    <span className="ml-auto text-[10px] uppercase tracking-wider text-gray-400">
                      {item.sourceType}
                    </span>
                  </div>
                  <p className="text-sm leading-snug text-gray-800">
                    {item.text}
                  </p>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  },
);

export default TranscriptPane;

function derefSources(
  citations: Record<string, CitationExpansion>,
): TranscriptItem[] {
  // Same source_id can be cited by multiple claims; dedupe by source_id
  // and keep the first occurrence's content (they should match anyway,
  // backend produces them from the same row).
  const seen = new Map<string, TranscriptItem>();
  for (const c of Object.values(citations)) {
    if (seen.has(c.source_id)) continue;
    const text =
      c.transcript_text ??
      c.original_text ??
      (c.frame_timestamp_ms != null
        ? `Frame at ${Math.round((c.frame_timestamp_ms ?? 0) / 1000)}s`
        : "");
    if (!text) continue;
    seen.set(c.source_id, {
      sourceId: c.source_id,
      sourceType: c.source_type,
      text,
      speaker: c.transcript_speaker ?? null,
      startMs: c.transcript_start_ms ?? null,
    });
  }
  // Sort by transcript timestamp when available so the pane reads
  // chronologically; un-timestamped sources (frames, edits) sink to
  // the bottom.
  return Array.from(seen.values()).sort((a, b) => {
    const at = a.startMs ?? Number.MAX_SAFE_INTEGER;
    const bt = b.startMs ?? Number.MAX_SAFE_INTEGER;
    return at - bt;
  });
}

function formatMs(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const m = Math.floor(totalSec / 60);
  const s = totalSec % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}
