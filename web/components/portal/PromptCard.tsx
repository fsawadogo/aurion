"use client";

import { ChevronDown, ChevronUp, Lock } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";
import Card from "@/components/ui/Card";
import type { AIPrompt } from "@/types";

/**
 * One row on the AI Prompts Transparency page.
 *
 * The card is intentionally dense at rest (name + purpose + when-it-
 * runs) and expands on demand to show the full system prompt in a
 * monospace `<pre>` block. Most physicians won't expand; the ones
 * who care about the safety boundary will, and they'll see the same
 * text the LLM does.
 *
 * Phase A only. The "Phase A: read-only" chip + the locked icon
 * telegraph that customization is coming but not here yet. Phase B
 * will swap the expanded view for a textarea bound to
 * `override_text`; no other component-level changes needed.
 */
interface PromptCardProps {
  prompt: AIPrompt;
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

export default function PromptCard({ prompt }: PromptCardProps) {
  const t = useTranslations("AIPrompts");
  const [expanded, setExpanded] = useState(false);
  const categoryClasses = CATEGORY_BADGE[prompt.category];
  const displayedText = prompt.override_text ?? prompt.system_prompt;

  return (
    <Card
      className="transition-shadow duration-short"
      title={
        <div className="flex items-start justify-between gap-3 w-full">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3
                className="text-aurion-headline truncate"
                data-testid={`prompt-card-${prompt.id}-name`}
              >
                {prompt.name}
              </h3>
              <span
                className={
                  "text-aurion-micro rounded-aurion-xs px-2 py-0.5 ring-1 ring-inset " +
                  categoryClasses
                }
              >
                {t(`category.${prompt.category}`)}
              </span>
            </div>
            <p className="mt-1 text-aurion-caption text-navy-500">
              <span className="font-medium text-navy-600">
                {t("runsWhenLabel")}:
              </span>{" "}
              {prompt.runs_when}
            </p>
          </div>
          <span
            className="inline-flex shrink-0 items-center gap-1 rounded-aurion-xs bg-navy-50 px-2 py-1 text-aurion-micro text-navy-600 ring-1 ring-inset ring-navy-200"
            title={t("phaseBHint")}
            data-testid={`prompt-card-${prompt.id}-readonly-chip`}
          >
            <Lock className="h-3 w-3" />
            {t("phaseAReadOnlyChip")}
          </span>
        </div>
      }
    >
      <div className="space-y-3">
        <div>
          <p className="aurion-micro text-gold-600">{t("purposeLabel")}</p>
          <p className="text-aurion-callout text-navy-700 mt-1">
            {prompt.purpose}
          </p>
        </div>

        {prompt.schema_note && (
          <div>
            <p className="aurion-micro text-gold-600">
              {t("outputShapeLabel")}
            </p>
            <p className="text-aurion-caption text-navy-500 mt-1">
              {prompt.schema_note}
            </p>
          </div>
        )}

        <div className="flex items-center justify-between gap-3 pt-1">
          <span
            className="text-aurion-micro text-navy-400"
            data-testid={`prompt-card-${prompt.id}-provider-field`}
          >
            {t("poweredByLabel")}:{" "}
            <span className="font-mono text-navy-600">
              {prompt.provider_field}
            </span>
          </span>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            aria-controls={`prompt-card-${prompt.id}-pre`}
            className="inline-flex items-center gap-1.5 rounded-aurion-sm border border-hairline px-3 py-1.5 text-aurion-caption text-navy-700 hover:bg-canvas/60 transition-colors duration-short"
            data-testid={`prompt-card-${prompt.id}-toggle`}
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
              id={`prompt-card-${prompt.id}-pre`}
              data-testid={`prompt-card-${prompt.id}-pre`}
              className="whitespace-pre-wrap break-words rounded-aurion-sm bg-navy-50 px-3 py-2 text-aurion-caption text-navy-800 font-mono leading-relaxed ring-1 ring-inset ring-navy-100"
            >
              {displayedText}
            </pre>
          </div>
        )}
      </div>
    </Card>
  );
}
