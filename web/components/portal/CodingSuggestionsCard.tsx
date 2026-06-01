"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CalculatorIcon,
  CheckIcon,
  XMarkIcon,
  PencilSquareIcon,
  ExclamationTriangleIcon,
  ArrowPathIcon,
} from "@heroicons/react/24/outline";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  confirmMyCodingSuggestion,
  editMyCodingSuggestion,
  extractMyCodingSuggestions,
  listMyCodingSuggestions,
  rejectMyCodingSuggestion,
} from "@/lib/portal-api";
import type { CodingSuggestion, CodingSystem } from "@/types";

/**
 * Coding & billing suggestions card — #69 strategic separate surface.
 *
 * Aurion's clinical note is descriptive-only. Coding is inferential
 * by definition (mapping free-text → discrete code). The contradiction
 * is resolved by giving coding its own card with explicit "Assistive
 * — physician confirms" framing.  The data never flows back into the
 * clinical note.
 *
 * Visual cues that this is a different surface:
 *   - prominent warning chip in the header
 *   - cooler grey-violet accent (not the gold of clinical surfaces)
 *   - per-row low-confidence badge stays amber to draw attention
 *   - low-confidence rows render expanded by default; high collapsed
 *
 * Approval-gated (same rule as orders / summary): suggestions are
 * billing-bound and shouldn't come from a draft note.
 */

interface CodingSuggestionsCardProps {
  sessionId: string;
  /** From the parent's ExportMetadata.is_approved. */
  noteApproved: boolean;
}

const SYSTEM_LABEL: Record<CodingSystem, string> = {
  em: "E/M",
  icd10: "ICD-10",
  cpt: "CPT",
};

export default function CodingSuggestionsCard({
  sessionId,
  noteApproved,
}: CodingSuggestionsCardProps) {
  const [items, setItems] = useState<CodingSuggestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [extracting, setExtracting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const xs = await listMyCodingSuggestions(sessionId);
      setItems(xs);
    } catch (e) {
      setError(
        e instanceof Error ? e.message : "Failed to load suggestions.",
      );
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function extract() {
    setExtracting(true);
    setError(null);
    try {
      const created = await extractMyCodingSuggestions(sessionId);
      await load();
      if (created.length === 0) {
        setError(
          "No billable structure was found in this note. The extractor only suggests codes the note's claims clearly support — try re-running after enriching the note, or skip coding for this visit.",
        );
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Extraction failed.";
      if (/\b409\b/.test(msg)) {
        setError(
          "Suggestions can only be extracted after the note is approved.",
        );
      } else if (/\b502\b/.test(msg)) {
        setError("AI provider didn't respond — please try again.");
      } else {
        setError(msg);
      }
    } finally {
      setExtracting(false);
    }
  }

  async function onConfirm(s: CodingSuggestion) {
    setBusyId(s.id);
    setError(null);
    try {
      const updated = await confirmMyCodingSuggestion(sessionId, s.id);
      setItems(items.map((x) => (x.id === updated.id ? updated : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Confirm failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function onReject(s: CodingSuggestion) {
    if (
      !confirm(
        `Reject ${SYSTEM_LABEL[s.code_system]} code ${s.code}? The row stays in the audit trail.`,
      )
    )
      return;
    setBusyId(s.id);
    setError(null);
    try {
      const updated = await rejectMyCodingSuggestion(sessionId, s.id);
      setItems(items.map((x) => (x.id === updated.id ? updated : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Reject failed.");
    } finally {
      setBusyId(null);
    }
  }

  async function onEdit(
    s: CodingSuggestion,
    patch: { code: string; description: string },
  ) {
    setBusyId(s.id);
    setError(null);
    try {
      const updated = await editMyCodingSuggestion(sessionId, s.id, patch);
      setItems(items.map((x) => (x.id === updated.id ? updated : x)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Edit failed.");
    } finally {
      setBusyId(null);
    }
  }

  if (!noteApproved) return null;

  // Surfaces drafts-first so the physician knows what still needs
  // attention; rejected goes to the bottom (kept for audit).
  const sorted = [...items].sort((a, b) => {
    const rank: Record<string, number> = {
      suggested: 0, edited: 1, confirmed: 2, rejected: 3,
    };
    if (rank[a.status] !== rank[b.status]) return rank[a.status] - rank[b.status];
    return b.created_at.localeCompare(a.created_at);
  });

  const pendingCount = sorted.filter((s) => s.status === "suggested").length;
  const confirmedCount = sorted.filter(
    (s) => s.status === "confirmed" || s.status === "edited",
  ).length;
  // Surfaces an actionable header callout when the LLM emitted codes
  // that aren't in our curated catalog. We exclude rejected rows
  // because the physician already declined them — keeping the count
  // limited to actionable rows.
  const unvalidatedCount = sorted.filter(
    (s) => s.code_validated === false && s.status !== "rejected",
  ).length;

  return (
    <Card className="border-l-4 border-l-navy-300">
      <div className="mb-3 flex items-center gap-2 text-aurion-headline">
        <CalculatorIcon className="h-4 w-4 text-navy-500" />
        Coding & billing suggestions
        {sorted.length > 0 && (
          <span className="aurion-micro ml-2">
            {pendingCount} pending · {confirmedCount} confirmed
          </span>
        )}
        <div className="flex-1" />
        {sorted.length > 0 && (
          <Button
            size="sm"
            variant="ghost"
            loading={extracting}
            disabled={extracting}
            onClick={() => void extract()}
          >
            <ArrowPathIcon className="h-4 w-4 mr-1" />
            Re-suggest
          </Button>
        )}
      </div>

      {/* Always-visible disclaimer — the safety property of this
          surface depends on the physician knowing it's assistive. */}
      <div className="mb-3 flex items-start gap-2 rounded-aurion-md bg-amber-50 border border-amber-200 px-3 py-2 text-aurion-caption text-amber-900">
        <ExclamationTriangleIcon className="h-4 w-4 mt-0.5 shrink-0" />
        <div>
          <strong>Assistive — physician must confirm.</strong> These
          suggestions are LLM-generated from the approved note&apos;s
          claims. They do not appear in the clinical note. Confirm,
          edit, or reject each before billing.
        </div>
      </div>

      {/* Header-level catalog miss callout — actionable summary so
          the physician notices the unvalidated rows without having
          to scan each one. Distinct from the "assistive" disclaimer
          above: that's about the surface; this is about a specific
          row's catalog status. */}
      {unvalidatedCount > 0 && (
        <div className="mb-3 flex items-start gap-2 rounded-aurion-md bg-amber-50 border border-amber-300 px-3 py-2 text-aurion-caption text-amber-900">
          <ExclamationTriangleIcon className="h-4 w-4 mt-0.5 shrink-0" />
          <div>
            <strong>
              {unvalidatedCount} code{unvalidatedCount === 1 ? "" : "s"}{" "}
              not in catalog.
            </strong>{" "}
            Review the highlighted rows below — the LLM emitted billing
            codes that aren&apos;t in our curated reference. They may
            still be valid, but cross-reference your EMR before
            submitting.
          </div>
        </div>
      )}

      {error && (
        <div className="mb-3 rounded-aurion-md bg-amber-50 border border-amber-200 px-3 py-2 text-aurion-caption text-amber-800">
          {error}
        </div>
      )}

      {loading ? (
        <LoadingSkeleton lines={3} />
      ) : sorted.length === 0 ? (
        <div className="py-2">
          <p className="aurion-callout text-navy-500 mb-3">
            Generate billing code suggestions from this note — E/M level,
            ICD-10 diagnoses, CPT procedures. The extractor stays
            conservative: only what the note&apos;s claims clearly support.
          </p>
          <Button
            variant="primary"
            size="sm"
            loading={extracting}
            disabled={extracting}
            onClick={() => void extract()}
          >
            <CalculatorIcon className="h-4 w-4 mr-1.5" />
            Suggest codes for this visit
          </Button>
        </div>
      ) : (
        <ul className="divide-y divide-hairline">
          {sorted.map((s) => (
            <SuggestionRow
              key={s.id}
              suggestion={s}
              busy={busyId === s.id}
              onConfirm={() => void onConfirm(s)}
              onReject={() => void onReject(s)}
              onEdit={(patch) => void onEdit(s, patch)}
            />
          ))}
        </ul>
      )}
    </Card>
  );
}

/* ── Row ─────────────────────────────────────────────────────────────── */

function SuggestionRow({
  suggestion,
  busy,
  onConfirm,
  onReject,
  onEdit,
}: {
  suggestion: CodingSuggestion;
  busy: boolean;
  onConfirm: () => void;
  onReject: () => void;
  onEdit: (patch: { code: string; description: string }) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draftCode, setDraftCode] = useState(suggestion.code);
  const [draftDesc, setDraftDesc] = useState(suggestion.description);

  // Low-confidence rows expand by default — they deserve more
  // attention; high/medium collapse to one-line.
  const [expanded, setExpanded] = useState(suggestion.confidence === "low");

  const isPending = suggestion.status === "suggested";
  const isConfirmed = suggestion.status === "confirmed" || suggestion.status === "edited";
  const isRejected = suggestion.status === "rejected";

  function saveEdit() {
    if (!draftCode.trim() || !draftDesc.trim()) return;
    onEdit({ code: draftCode.trim(), description: draftDesc.trim() });
    setEditing(false);
  }

  return (
    <li
      className={
        "py-3 flex flex-col gap-2 " +
        (isRejected ? "opacity-60" : "")
      }
    >
      <div className="flex items-start gap-3">
        <div className="shrink-0 mt-0.5">
          <SystemBadge system={suggestion.code_system} />
        </div>
        <div className="flex-1 min-w-0">
          <button
            type="button"
            className="text-left w-full"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
          >
            <div className="flex items-baseline flex-wrap gap-x-2 gap-y-1">
              <span className="font-mono font-semibold text-navy-900 text-aurion-body">
                {suggestion.code}
              </span>
              <span className="aurion-callout text-navy-700">
                {suggestion.description}
              </span>
              <ConfidenceBadge confidence={suggestion.confidence} />
              <CatalogBadge validated={suggestion.code_validated} />
              <StatusBadge status={suggestion.status} />
            </div>
          </button>
          {expanded && (
            <>
              <p className="text-aurion-caption text-navy-500 mt-1 leading-snug">
                {suggestion.justification}
              </p>
              {suggestion.code_validated === false && (
                <p className="text-aurion-caption text-amber-700 mt-1 leading-snug">
                  <strong>Verify before billing.</strong> This code
                  wasn&apos;t found in our curated billing catalog. It may
                  still be a valid code — cross-reference against your
                  EMR&apos;s reference before submitting.
                </p>
              )}
            </>
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {(isPending || isConfirmed) && !editing && (
            <button
              type="button"
              onClick={() => {
                setDraftCode(suggestion.code);
                setDraftDesc(suggestion.description);
                setEditing(true);
              }}
              disabled={busy}
              className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-navy-50 hover:text-navy-700 disabled:opacity-50"
              aria-label="Edit code"
            >
              <PencilSquareIcon className="h-4 w-4" />
            </button>
          )}
          {isPending && !editing && (
            <>
              <Button
                size="sm"
                variant="primary"
                loading={busy}
                disabled={busy}
                onClick={onConfirm}
              >
                <CheckIcon className="h-4 w-4 mr-1" />
                Confirm
              </Button>
              <button
                type="button"
                onClick={onReject}
                disabled={busy}
                className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
                aria-label="Reject"
              >
                <XMarkIcon className="h-4 w-4" />
              </button>
            </>
          )}
        </div>
      </div>

      {editing && (
        <div className="ml-8 flex flex-col gap-2 p-3 rounded-aurion-md bg-navy-50/50">
          <div className="flex gap-2">
            <input
              type="text"
              value={draftCode}
              onChange={(e) => setDraftCode(e.target.value)}
              className="font-mono w-32 px-2 py-1 text-sm rounded-aurion-xs border border-hairline focus:border-gold-500 focus:outline-none"
              placeholder="Code"
              maxLength={32}
            />
            <input
              type="text"
              value={draftDesc}
              onChange={(e) => setDraftDesc(e.target.value)}
              className="flex-1 px-2 py-1 text-sm rounded-aurion-xs border border-hairline focus:border-gold-500 focus:outline-none"
              placeholder="Description"
              maxLength={200}
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setEditing(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={saveEdit}
              loading={busy}
              disabled={busy || !draftCode.trim() || !draftDesc.trim()}
            >
              Save
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

function SystemBadge({ system }: { system: CodingSystem }) {
  // Each code system gets its own neutral chip color — visually
  // group rows by family without using the gold accent (which is
  // reserved for clinical-content surfaces).
  const styles: Record<CodingSystem, string> = {
    em: "bg-navy-100 text-navy-800",
    icd10: "bg-purple-100 text-purple-800",
    cpt: "bg-emerald-100 text-emerald-800",
  };
  return (
    <span
      className={
        "inline-flex items-center px-2 py-0.5 rounded-aurion-xs text-aurion-micro font-semibold uppercase tracking-wide " +
        styles[system]
      }
    >
      {SYSTEM_LABEL[system]}
    </span>
  );
}

function ConfidenceBadge({ confidence }: { confidence: "low" | "medium" | "high" }) {
  switch (confidence) {
    case "low":
      return <Badge variant="warning" dot>Low confidence</Badge>;
    case "medium":
      return <Badge variant="neutral">Medium</Badge>;
    case "high":
      return <Badge variant="success" dot>High</Badge>;
  }
}

/** Catalog validation surface — three-state.
 *
 *  true  → no chip (silent success; recognized code)
 *  false → amber "Not in catalog" warning; the row body also gets
 *          a verify-before-billing callout when expanded
 *  null  → no chip (legacy row predating validation; UI stays neutral
 *          rather than surfacing false uncertainty) */
function CatalogBadge({ validated }: { validated?: boolean | null }) {
  if (validated === false) {
    return <Badge variant="warning" dot>Not in catalog</Badge>;
  }
  return null;
}

function StatusBadge({
  status,
}: {
  status: "suggested" | "confirmed" | "rejected" | "edited";
}) {
  switch (status) {
    case "suggested":
      return null; // default state, no chip clutter
    case "confirmed":
      return <Badge variant="success">Confirmed</Badge>;
    case "edited":
      return <Badge variant="info">Edited & confirmed</Badge>;
    case "rejected":
      return <Badge variant="neutral">Rejected</Badge>;
  }
}
