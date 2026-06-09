"use client";

/**
 * Preview card for a draft / saved template.
 *
 * Renders the structural shape — sections, required toggles, visual
 * triggers, descriptions — without any clinical content (because
 * there isn't any in a template; it's all scaffold). Used in two
 * places:
 *   * The conversational builder, alongside the chat pane, showing
 *     the latest LLM-emitted draft.
 *   * The /portal/templates/[id] view page (read-only).
 *
 * Pure presentational — no callbacks, no state. The builder owns
 * the "Save" button at the page level.
 */

import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import type { TemplateDefinition } from "@/types";

interface TemplateDraftPreviewProps {
  template: TemplateDefinition;
  showDescription?: boolean;
}

export default function TemplateDraftPreview({
  template,
  showDescription = true,
}: TemplateDraftPreviewProps) {
  const t = useTranslations("TemplateDraftPreview");
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-3">
        <h3 className="text-base font-semibold text-navy-800">
          {template.display_name}
        </h3>
        <p className="mt-0.5 text-xs text-gray-500">
          <span className="font-mono">{template.key}</span> · v{template.version}
        </p>
      </div>
      {template.sections.length === 0 ? (
        <p className="text-sm text-gray-500 italic">{t("noSections")}</p>
      ) : (
        <ol className="space-y-3">
          {template.sections.map((section, idx) => (
            <li key={section.id || idx} className="relative pl-7">
              <span className="absolute left-0 top-0.5 inline-flex h-5 w-5 items-center justify-center rounded-full bg-navy-50 text-[10px] font-semibold text-navy-700">
                {idx + 1}
              </span>
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-navy-800">
                  {section.title || section.id}
                </span>
                {section.required ? (
                  <Badge variant="success" dot>{t("required")}</Badge>
                ) : (
                  <Badge variant="neutral">{t("optional")}</Badge>
                )}
                {section.visual_trigger_keywords.length > 0 && (
                  <Badge variant="info">
                    {t("triggerCount", {
                      count: section.visual_trigger_keywords.length,
                    })}
                  </Badge>
                )}
              </div>
              {showDescription && section.description && (
                <p className="mt-1 text-xs text-gray-600">
                  {section.description}
                </p>
              )}
              {section.visual_trigger_keywords.length > 0 && (
                <p className="mt-1 text-[11px] text-gray-500">
                  {t("triggersLabel")}:{" "}
                  {section.visual_trigger_keywords
                    .map((k) => `“${k}”`)
                    .join(", ")}
                </p>
              )}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
