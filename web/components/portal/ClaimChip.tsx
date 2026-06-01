"use client";

import { useState } from "react";
import type { CitationExpansion, Claim } from "@/types";

/**
 * Citation badge attached to a claim in the note review pane.
 *
 * Single letter per source type (T/V/S/E) mirroring iOS:
 *   T  transcript    blue
 *   V  visual frame  amber
 *   S  screen frame  emerald
 *   E  physician edit  gold
 *
 * Hover surfaces a tiny popover with the source quote / frame
 * timestamp / original_text so the physician doesn't have to scroll
 * the transcript pane to glance at the source. Click triggers the
 * caller's `onClick` so the transcript pane can scroll to and
 * highlight the source segment.
 */

const SOURCE_LETTER: Record<string, string> = {
  transcript: "T",
  visual: "V",
  screen: "S",
  physician_edit: "E",
};

const SOURCE_LABEL: Record<string, string> = {
  transcript: "Transcript",
  visual: "Visual frame",
  screen: "Screen capture",
  physician_edit: "Physician edit",
};

const SOURCE_CLASSES: Record<string, string> = {
  transcript: "bg-navy-50 text-navy-700 ring-navy-500/15",
  visual: "bg-amber-50 text-amber-700 ring-amber-500/20",
  screen: "bg-emerald-50 text-emerald-700 ring-emerald-500/20",
  physician_edit: "bg-gold-50 text-gold-700 ring-gold-500/30",
};

interface ClaimChipProps {
  claim: Claim;
  citation: CitationExpansion | undefined;
  onClick?: () => void;
}

export default function ClaimChip({ claim, citation, onClick }: ClaimChipProps) {
  const [hovered, setHovered] = useState(false);
  const letter = SOURCE_LETTER[claim.source_type] ?? "?";
  const label = SOURCE_LABEL[claim.source_type] ?? claim.source_type;
  const cls = SOURCE_CLASSES[claim.source_type] ?? "bg-gray-50 text-gray-700 ring-gray-300";

  const preview = previewFor(claim, citation);

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        onClick={onClick}
        className={
          `inline-flex h-5 w-5 items-center justify-center rounded text-[10px] font-bold ring-1 ring-inset transition-colors hover:brightness-105 ${cls}` +
          (onClick ? " cursor-pointer" : " cursor-default")
        }
        aria-label={`Source: ${label}`}
        title={preview ? `${label}: ${preview}` : label}
      >
        {letter}
      </button>
      {hovered && preview && (
        <span
          className="absolute left-1/2 top-full z-10 mt-1.5 w-64 -translate-x-1/2 rounded-md border border-gray-200 bg-white p-2 text-[11px] leading-snug text-gray-700 shadow-lg"
          role="tooltip"
        >
          <span className="block font-semibold text-navy-700 mb-0.5">
            {label}
          </span>
          <span className="block italic text-gray-600">
            “{preview}”
          </span>
        </span>
      )}
    </span>
  );
}

function previewFor(claim: Claim, c: CitationExpansion | undefined): string {
  if (c) {
    if (c.transcript_text) return truncate(c.transcript_text, 160);
    if (c.frame_timestamp_ms != null) {
      return `Frame @ ${Math.round(c.frame_timestamp_ms / 1000)}s`;
    }
    if (c.original_text) return truncate(c.original_text, 160);
  }
  if (claim.source_quote) return truncate(claim.source_quote, 160);
  return "";
}

function truncate(s: string, n: number): string {
  if (s.length <= n) return s;
  return s.slice(0, n - 1) + "…";
}
