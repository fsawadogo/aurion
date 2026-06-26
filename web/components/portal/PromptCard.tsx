"use client";

import {
  CheckCircle2,
  ChevronDown,
  ChevronUp,
  Edit3,
  Lock,
  Megaphone,
} from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";
import Card from "@/components/ui/Card";
import PromptUserPromptEditor from "@/components/portal/PromptUserPromptEditor";
import type { AIPrompt } from "@/types";

/**
 * One row on the AI Prompts Transparency page.
 *
 * Phase A: dense rest state (name + purpose + when-it-runs) that
 * expands on demand to reveal the full system prompt.
 *
 * Phase B (replacement semantics) added:
 *   - "Custom prompt active" badge when `is_overridden` is true (the
 *     physician has saved their own prompt that REPLACES the system
 *     default).
 *   - "Edit your prompt" button that opens the
 *     `PromptUserPromptEditor` modal — CLINICIAN-only at the server
 *     level (the button is rendered for everyone but the PATCH
 *     endpoint 403s for ADMIN/EVAL_TEAM/COMPLIANCE_OFFICER, who
 *     never have user prompts anyway).
 *   - Expanded view shows the `active_prompt` text — what the LLM
 *     actually receives for THIS physician (their saved prompt when
 *     set, the system default otherwise — NOT both).
 *
 * The card owns its own modal state. A successful save updates the
 * card-local `current` AIPrompt so the parent page doesn't need to
 * refetch on every edit; the parent can also pass an onChange
 * callback if it wants to sync the page's prompts list.
 */

interface PromptCardProps {
  prompt: AIPrompt;
  /** Optional callback — parents that want the page list to update
   *  in lock-step with the card's local state can wire this in. */
  onChange?: (next: AIPrompt) => void;
}

const CATEGORY_BADGE: Record<AIPrompt["category"], string> = {
  note:
    "bg-navy-50 text-navy-700 ring-navy-200",
  vision:
    "bg-gold-50 text-gold-700 ring-gold-300",
  extraction:
    "bg-sky-50 text-sky-700 ring-sky-200",
  preview:
    "bg-emerald-50 text-emerald-700 ring-emerald-200",
};

export default function PromptCard({ prompt, onChange }: PromptCardProps) {
  const t = useTranslations("AIPrompts");
  const [expanded, setExpanded] = useState(false);
  const [editorOpen, setEditorOpen] = useState(false);
  const [current, setCurrent] = useState<AIPrompt>(prompt);

  const categoryClasses = CATEGORY_BADGE[current.category];
  // Expanded view shows the active prompt — the "what the LLM is
  // actually told today" view. Under replacement semantics this is
  // either the physician's saved user prompt OR the system default —
  // never a concatenation of both.
  const displayedText = current.active_prompt;

  function handleSaved(next: AIPrompt) {
    setCurrent(next);
    onChange?.(next);
  }

  return (
    <>
      <Card
        className="transition-shadow duration-short"
        title={
          <div className="flex items-start justify-between gap-3 w-full">
            <div className="min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3
                  className="text-aurion-headline truncate"
                  data-testid={`prompt-card-${current.id}-name`}
                >
                  {current.name}
                </h3>
                <span
                  className={
                    "text-aurion-micro rounded-aurion-xs px-2 py-0.5 ring-1 ring-inset " +
                    categoryClasses
                  }
                >
                  {t(`category.${current.category}`)}
                </span>
                {current.is_overridden && (
                  <span
                    className="inline-flex items-center gap-1 rounded-aurion-xs bg-emerald-50 px-2 py-0.5 text-aurion-micro text-emerald-700 ring-1 ring-inset ring-emerald-200"
                    data-testid={`prompt-card-${current.id}-override-badge`}
                  >
                    <CheckCircle2 className="h-3 w-3" />
                    {t("userPrompt.activeBadge")}
                  </span>
                )}
              </div>
              <p className="mt-1 text-aurion-caption text-navy-500">
                <span className="font-medium text-navy-600">
                  {t("runsWhenLabel")}:
                </span>{" "}
                {current.runs_when}
              </p>
            </div>
            <button
              type="button"
              onClick={() => setEditorOpen(true)}
              className="inline-flex shrink-0 items-center gap-1.5 rounded-aurion-xs bg-navy-50 px-2 py-1 text-aurion-micro text-navy-600 ring-1 ring-inset ring-navy-200 hover:bg-navy-100 transition-colors duration-short"
              title={t("userPrompt.editButton")}
              data-testid={`prompt-card-${current.id}-edit-button`}
            >
              {current.is_overridden ? (
                <Edit3 className="h-3 w-3" />
              ) : (
                <Lock className="h-3 w-3" />
              )}
              {t("userPrompt.editButton")}
            </button>
          </div>
        }
      >
        <div className="space-y-3">
          {current.admin_publication && (
            <div
              className={
                "flex items-start gap-2 rounded-aurion-sm px-3 py-2 text-aurion-caption ring-1 ring-inset " +
                (current.is_overridden
                  ? "bg-amber-50 text-amber-800 ring-amber-200"
                  : "bg-sky-50 text-sky-800 ring-sky-200")
              }
              data-testid={`prompt-card-${current.id}-publication`}
            >
              <Megaphone
                className="h-3.5 w-3.5 shrink-0 mt-0.5"
                aria-hidden="true"
              />
              <span>
                {current.is_overridden
                  ? t("adminPublication.shadowed", {
                      name: current.admin_publication.name,
                    })
                  : t("adminPublication.active", {
                      name: current.admin_publication.name,
                      version: current.admin_publication.version_no,
                      date: new Date(
                        current.admin_publication.published_at,
                      ).toLocaleDateString(),
                    })}
              </span>
            </div>
          )}
          <div>
            <p className="aurion-micro text-gold-600">{t("purposeLabel")}</p>
            <p className="text-aurion-callout text-navy-700 mt-1">
              {current.purpose}
            </p>
          </div>

          {current.schema_note && (
            <div>
              <p className="aurion-micro text-gold-600">
                {t("outputShapeLabel")}
              </p>
              <p className="text-aurion-caption text-navy-500 mt-1">
                {current.schema_note}
              </p>
            </div>
          )}

          <div className="flex items-center justify-between gap-3 pt-1">
            <span
              className="text-aurion-micro text-navy-400"
              data-testid={`prompt-card-${current.id}-provider-field`}
            >
              {t("poweredByLabel")}:{" "}
              <span className="font-mono text-navy-600">
                {current.provider_field}
              </span>
            </span>
            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              aria-expanded={expanded}
              aria-controls={`prompt-card-${current.id}-pre`}
              className="inline-flex items-center gap-1.5 rounded-aurion-sm border border-hairline px-3 py-1.5 text-aurion-caption text-navy-700 hover:bg-canvas/60 transition-colors duration-short"
              data-testid={`prompt-card-${current.id}-toggle`}
            >
              {expanded ? (
                <>
                  <ChevronUp className="h-3.5 w-3.5" />
                  {t("collapseLabel")}
                </>
              ) : (
                <>
                  <ChevronDown className="h-3.5 w-3.5" />
                  {t("expandLabel")}
                </>
              )}
            </button>
          </div>

          {expanded && (
            <div>
              <p className="aurion-micro text-gold-600 mb-1">
                {t("instructionsLabel")}
              </p>
              <pre
                id={`prompt-card-${current.id}-pre`}
                data-testid={`prompt-card-${current.id}-pre`}
                className="whitespace-pre-wrap break-words rounded-aurion-sm bg-navy-50 px-3 py-2 text-aurion-caption text-navy-800 font-mono leading-relaxed ring-1 ring-inset ring-navy-100"
              >
                {displayedText}
              </pre>
            </div>
          )}
        </div>
      </Card>
      <PromptUserPromptEditor
        key={`${current.id}:${editorOpen}`}
        prompt={current}
        isOpen={editorOpen}
        onClose={() => setEditorOpen(false)}
        onSaved={handleSaved}
      />
    </>
  );
}
