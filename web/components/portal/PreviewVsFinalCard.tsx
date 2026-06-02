"use client";

import { ArrowLeftRight, CheckCircle2, ChevronDown, ChevronUp, MinusCircle, PlusCircle } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Badge from "@/components/ui/Badge";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getMyLatestSessionPreview } from "@/lib/portal-api";
import {
  diffPreviewVsFinal,
  previewRecallPercent,
  type ClaimMatchKind,
  type PreviewToFinalDiff,
  type SectionDiffEntry,
} from "@/lib/portal-preview-diff";
import type { Claim, LivePreview, NoteSection } from "@/types";

/**
 * Preview-to-final diff card — #64 follow-up.
 *
 * Pilot-evaluation surface: shows how the last live preview snapshot
 * compares to the canonical Stage 1 note. The eval team uses this to
 * tune preview cadence + compare LLM providers ("recall against the
 * final under provider A vs B"). The physician sees it as a passive
 * panel — read-only, no actions.
 *
 * Only renders when:
 *   1. The note is approved (Stage 1 done — there's something to
 *      compare against)
 *   2. At least one preview snapshot exists for the session
 *
 * Collapsed by default — the panel is reference data, not the
 * critical path. Header shows the headline recall percentage; tapping
 * expands to the per-section breakdown.
 */

interface PreviewVsFinalCardProps {
  sessionId: string;
  /** Final Stage 1 note sections from the parent's NoteDetail. */
  finalSections: NoteSection[];
  /** Approval gate from the parent's export_metadata. */
  noteApproved: boolean;
}

const KIND_LABEL: Record<ClaimMatchKind, string> = {
  matched: "Matched",
  fuzzy: "Fuzzy match",
  preview_only: "Preview only",
  final_only: "Final only",
};

const KIND_COLOR: Record<ClaimMatchKind, string> = {
  matched: "text-emerald-700",
  fuzzy: "text-emerald-600",
  preview_only: "text-amber-700",
  final_only: "text-blue-700",
};

export default function PreviewVsFinalCard({
  sessionId,
  finalSections,
  noteApproved,
}: PreviewVsFinalCardProps) {
  const [preview, setPreview] = useState<LivePreview | null>(null);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const p = await getMyLatestSessionPreview(sessionId);
      setPreview(p);
    } catch {
      // Silent: preview-vs-final is an evaluation panel, not a
      // critical-path render. If the preview endpoint hiccups, the
      // panel just stays hidden.
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    if (!noteApproved) return;
    void load();
  }, [load, noteApproved]);

  if (!noteApproved) return null;
  if (loading) {
    // Don't render a skeleton block here — the parent already has
    // plenty of surface area. Suppress until we know if there's
    // anything to show.
    return null;
  }
  if (!preview) return null;

  const diff = diffPreviewVsFinal(preview, finalSections);
  const recall = previewRecallPercent(diff);

  return (
    <Card className="border-l-4 border-l-blue-300">
      <button
        type="button"
        className="w-full flex items-center gap-2 text-left text-aurion-headline"
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <ArrowLeftRight className="h-4 w-4 text-blue-600" />
        Preview vs final
        {recall !== null && (
          <Badge
            variant={recall >= 70 ? "success" : recall >= 40 ? "warning" : "neutral"}
            dot
          >
            {recall}% recall
          </Badge>
        )}
        <span className="aurion-micro text-navy-500 ml-2">
          v{diff.preview_meta.version} ·{" "}
          {new Date(diff.preview_meta.created_at).toLocaleTimeString()}
          {" · "}
          {diff.preview_meta.transcript_chars.toLocaleString()} chars
        </span>
        <div className="flex-1" />
        {expanded ? (
          <ChevronUp className="h-4 w-4 text-navy-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-navy-400" />
        )}
      </button>

      {expanded && (
        <div className="mt-3">
          <TotalsRow totals={diff.totals} />
          <div className="mt-3 space-y-3">
            {diff.sections.map((section) => (
              <SectionRow key={section.section_id} section={section} />
            ))}
          </div>
          <p className="aurion-micro text-navy-400 mt-3 leading-snug">
            Evaluation surface. Compares the latest preview snapshot
            against the approved final note. &quot;Fuzzy match&quot; is
            a heuristic on the first 40 characters of normalized text
            — useful for the eval team but not authoritative.
          </p>
        </div>
      )}
    </Card>
  );
}

function TotalsRow({ totals }: { totals: PreviewToFinalDiff["totals"] }) {
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-aurion-md bg-navy-50/40 px-3 py-2 text-aurion-caption">
      <KindCounter
        kind="matched"
        count={totals.matched}
        icon={<CheckCircle2 className="h-4 w-4" />}
      />
      <KindCounter
        kind="fuzzy"
        count={totals.fuzzy}
        icon={<CheckCircle2 className="h-4 w-4 opacity-70" />}
      />
      <KindCounter
        kind="final_only"
        count={totals.final_only}
        icon={<PlusCircle className="h-4 w-4" />}
      />
      <KindCounter
        kind="preview_only"
        count={totals.preview_only}
        icon={<MinusCircle className="h-4 w-4" />}
      />
    </div>
  );
}

function KindCounter({
  kind,
  count,
  icon,
}: {
  kind: ClaimMatchKind;
  count: number;
  icon: React.ReactNode;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 ${KIND_COLOR[kind]}`}>
      {icon}
      <strong>{count}</strong>
      <span>{KIND_LABEL[kind].toLowerCase()}</span>
    </span>
  );
}

function SectionRow({ section }: { section: SectionDiffEntry }) {
  if (section.claims.length === 0) {
    return (
      <div className="py-2">
        <h5 className="aurion-headline text-navy-700">{section.title}</h5>
        <p className="text-aurion-caption text-navy-400 italic mt-0.5">
          Empty in both preview and final.
        </p>
      </div>
    );
  }
  return (
    <div className="py-2">
      <div className="flex items-baseline gap-2 mb-1.5">
        <h5 className="aurion-headline text-navy-800">{section.title}</h5>
        {!section.in_preview && (
          <span className="text-aurion-micro text-blue-700">
            (final-only section)
          </span>
        )}
        {!section.in_final && (
          <span className="text-aurion-micro text-amber-700">
            (preview-only section)
          </span>
        )}
      </div>
      <ul className="space-y-1.5">
        {section.claims.map((entry, i) => (
          <ClaimRow key={`${section.section_id}-${i}`} entry={entry} />
        ))}
      </ul>
    </div>
  );
}

function ClaimRow({
  entry,
}: {
  entry: SectionDiffEntry["claims"][number];
}) {
  switch (entry.kind) {
    case "matched":
    case "fuzzy":
      return (
        <li className="flex items-start gap-2 text-aurion-caption">
          <CheckCircle2
            className={`h-4 w-4 mt-0.5 shrink-0 ${KIND_COLOR[entry.kind]}`}
          />
          <div className="flex-1 min-w-0">
            <p className="text-navy-700 leading-snug">
              {entry.final_claim?.text}
            </p>
            {entry.kind === "fuzzy" && entry.preview_claim
              && entry.preview_claim.text !== entry.final_claim?.text && (
                <p className="text-aurion-micro text-navy-500 mt-0.5 leading-snug">
                  Preview said:{" "}
                  <em>&ldquo;{entry.preview_claim.text}&rdquo;</em>
                </p>
              )}
          </div>
        </li>
      );
    case "final_only":
      return (
        <li className="flex items-start gap-2 text-aurion-caption">
          <PlusCircle
            className={`h-4 w-4 mt-0.5 shrink-0 ${KIND_COLOR.final_only}`}
          />
          <div className="flex-1 min-w-0">
            <p className="text-navy-700 leading-snug">
              {entry.final_claim?.text}
            </p>
            <p className="text-aurion-micro text-navy-400 mt-0.5">
              Not in preview — added in the final
            </p>
          </div>
        </li>
      );
    case "preview_only":
      return (
        <li className="flex items-start gap-2 text-aurion-caption">
          <MinusCircle
            className={`h-4 w-4 mt-0.5 shrink-0 ${KIND_COLOR.preview_only}`}
          />
          <div className="flex-1 min-w-0 opacity-75">
            <p className="text-navy-700 leading-snug italic">
              {entry.preview_claim?.text}
            </p>
            <p className="text-aurion-micro text-amber-700 mt-0.5">
              Was in preview — dropped in the final
            </p>
          </div>
        </li>
      );
  }
}

// Defensive: keep imports the bundler can verify match the types
// the parent passes down.
type _ExpectClaim = Claim;
type _ExpectNoteSection = NoteSection;
