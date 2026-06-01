"use client";

import { useCallback, useEffect, useState } from "react";
import {
  ClipboardDocumentIcon,
  PrinterIcon,
  ArrowPathIcon,
  PencilIcon,
  CheckIcon,
  XMarkIcon,
  SparklesIcon,
} from "@heroicons/react/24/outline";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  editMyPatientSummary,
  generateMyPatientSummary,
  getMyPatientSummary,
} from "@/lib/portal-api";
import type { PatientSummary } from "@/types";

/**
 * After-visit patient summary card on the note review screen.
 *
 * Lives below the two-column transcript/note layout. Visible only
 * after the note is approved (the parent gates the prop). Three modes:
 *
 *   No summary yet  → "Generate" CTA + an explainer line about what
 *                       it is (plain language + patient-facing).
 *   Summary present → readable card with Copy / Print / Edit /
 *                       Regenerate actions. The regenerate button
 *                       confirms before firing — physicians rarely
 *                       want to lose hand-tuned edits.
 *   Editing         → inline textarea (max 4000 chars), Save / Cancel
 *                       buttons; save bumps the version and fires the
 *                       PATIENT_SUMMARY_EDITED audit event server-side.
 */

interface PatientSummaryCardProps {
  sessionId: string;
  /** Latest is_approved value from the parent's ExportMetadata.
   *  When false, the card is hidden — patient-facing output must
   *  come from a physician-signed note. */
  noteApproved: boolean;
}

export default function PatientSummaryCard({
  sessionId,
  noteApproved,
}: PatientSummaryCardProps) {
  const [summary, setSummary] = useState<PatientSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [justCopied, setJustCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await getMyPatientSummary(sessionId);
      setSummary(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load summary.");
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function generate() {
    setGenerating(true);
    setError(null);
    try {
      const s = await generateMyPatientSummary(sessionId);
      setSummary(s);
      setDraft(s.body);
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Generation failed.";
      // Friendlier surfaces for the two routes the backend cares about:
      //   409 → note not approved or missing
      //   502 → upstream LLM failure
      if (/\b409\b/.test(msg)) {
        setError("The note has to be approved before the patient summary can be generated.");
      } else if (/\b502\b/.test(msg)) {
        setError("AI provider didn't respond — please try again in a moment.");
      } else {
        setError(msg);
      }
    } finally {
      setGenerating(false);
    }
  }

  async function regenerate() {
    if (
      !confirm(
        "Regenerate the patient summary? Any edits you made to the current version stay in the audit history but won't show here anymore.",
      )
    )
      return;
    await generate();
  }

  async function saveEdit() {
    setSaving(true);
    setError(null);
    try {
      const s = await editMyPatientSummary(sessionId, draft);
      setSummary(s);
      setEditing(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  function copy() {
    if (!summary) return;
    void navigator.clipboard.writeText(summary.body).then(() => {
      setJustCopied(true);
      window.setTimeout(() => setJustCopied(false), 1500);
    });
  }

  function print() {
    if (!summary) return;
    // Build the print window via DOM APIs rather than document.write
    // — same end result, no XSS surface (every text node uses
    // textContent so the body is treated as data, never markup).
    const w = window.open("", "_blank", "width=720,height=520");
    if (!w) return;
    const doc = w.document;
    doc.title = "After-visit summary";

    const style = doc.createElement("style");
    style.textContent =
      "body { font-family: -apple-system, system-ui, sans-serif;" +
      "       padding: 32px; line-height: 1.55; color: #0C1B37;" +
      "       max-width: 600px; margin: 0 auto; }" +
      "h1 { font-size: 18px; margin: 0 0 16px 0; color: #0C1B37; }" +
      "p  { font-size: 14px; white-space: pre-wrap; }" +
      ".footer { margin-top: 24px; padding-top: 12px;" +
      "          border-top: 1px solid #E6E9EE; font-size: 11px;" +
      "          color: #6B7280; }";
    doc.head.appendChild(style);

    const h1 = doc.createElement("h1");
    h1.textContent = "After-visit summary";
    doc.body.appendChild(h1);

    const p = doc.createElement("p");
    p.textContent = summary.body;
    doc.body.appendChild(p);

    const footer = doc.createElement("div");
    footer.className = "footer";
    footer.textContent =
      "Generated by Aurion Clinical AI. Discuss any questions with your physician.";
    doc.body.appendChild(footer);

    w.focus();
    w.print();
  }

  if (!noteApproved) return null;

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2 text-aurion-headline">
        <SparklesIcon className="h-4 w-4 text-gold-500" />
        After-visit summary
        {summary && (
          <span className="aurion-micro ml-2">
            v{summary.version}
            {summary.physician_edited ? " · edited" : ""}
          </span>
        )}
      </div>

      {error && (
        <div className="mb-3 rounded-aurion-md bg-red-50 border border-red-200 px-3 py-2 text-aurion-caption text-red-700">
          {error}
        </div>
      )}

      {loading ? (
        <LoadingSkeleton lines={3} />
      ) : !summary ? (
        <div className="py-2">
          <p className="aurion-callout text-navy-500 mb-3">
            Generate a plain-language summary for the patient to take
            home. Reads at a Grade-8 level; never adds anything beyond
            what your approved note already says.
          </p>
          <Button
            variant="primary"
            size="sm"
            loading={generating}
            disabled={generating}
            onClick={() => void generate()}
          >
            <SparklesIcon className="h-4 w-4 mr-1.5" />
            Generate summary
          </Button>
        </div>
      ) : editing ? (
        <div>
          <textarea
            className="form-input min-h-[160px] leading-relaxed resize-y"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            disabled={saving}
            maxLength={4000}
            aria-label="Edit patient summary"
          />
          <p className="aurion-caption mt-1">
            {draft.length} / 4000 characters
          </p>
          <div className="mt-3 flex gap-2">
            <Button
              size="sm"
              variant="primary"
              loading={saving}
              disabled={saving || !draft.trim() || draft === summary.body}
              onClick={() => void saveEdit()}
            >
              <CheckIcon className="h-4 w-4 mr-1" />
              Save edit
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={saving}
              onClick={() => {
                setEditing(false);
                setDraft(summary.body);
              }}
            >
              <XMarkIcon className="h-4 w-4 mr-1" />
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <div>
          <p className="aurion-body text-navy-800 whitespace-pre-wrap leading-relaxed">
            {summary.body}
          </p>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="secondary" onClick={copy}>
              <ClipboardDocumentIcon className="h-4 w-4 mr-1" />
              {justCopied ? "Copied!" : "Copy"}
            </Button>
            <Button size="sm" variant="secondary" onClick={print}>
              <PrinterIcon className="h-4 w-4 mr-1" />
              Print
            </Button>
            <Button
              size="sm"
              variant="secondary"
              onClick={() => {
                setDraft(summary.body);
                setEditing(true);
              }}
            >
              <PencilIcon className="h-4 w-4 mr-1" />
              Edit
            </Button>
            <div className="flex-1" />
            <Button
              size="sm"
              variant="ghost"
              loading={generating}
              disabled={generating}
              onClick={() => void regenerate()}
            >
              <ArrowPathIcon className="h-4 w-4 mr-1" />
              Regenerate
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
