/**
 * Circular completeness ring — port of the iOS NoteReviewView ring.
 *
 * Shows populated sections / required sections as a ring fill plus
 * a percentage in the middle. Sections with status `pending_video`
 * or `pending` don't count as populated (matching iOS:
 * NoteReviewView.swift:735-745).
 */

import type { NoteSection } from "@/types";

interface CompletenessRingProps {
  sections: NoteSection[];
  size?: number;
  strokeWidth?: number;
}

export default function CompletenessRing({
  sections,
  size = 56,
  strokeWidth = 6,
}: CompletenessRingProps) {
  const required = sections.length;
  const populated = sections.filter(
    (s) => s.status === "populated",
  ).length;
  const pct = required === 0 ? 0 : populated / required;

  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - pct);

  return (
    <div
      className="relative inline-flex items-center justify-center"
      style={{ width: size, height: size }}
      aria-label={`Completeness ${Math.round(pct * 100)}%`}
      role="img"
    >
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          fill="none"
          className="text-gray-200"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          fill="none"
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          className={
            pct >= 0.9
              ? "text-emerald-500"
              : pct >= 0.6
              ? "text-gold-500"
              : "text-amber-500"
          }
          style={{ transition: "stroke-dashoffset 200ms ease-out" }}
        />
      </svg>
      <span className="absolute text-[11px] font-semibold text-navy-700 tabular-nums">
        {Math.round(pct * 100)}%
      </span>
    </div>
  );
}
