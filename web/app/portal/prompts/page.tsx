"use client";

import { Eye, FileText, Info, Radio, ScanLine, Search, Sparkles } from "lucide-react";
import { humanizeError } from "@/lib/api";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import PromptCard from "@/components/portal/PromptCard";
import { listMyPrompts } from "@/lib/portal-api";
import type { AIPrompt, PromptCategory } from "@/types";

/**
 * /portal/prompts — AI Prompts Transparency (Phase A).
 *
 * Read-only catalog of every LLM system prompt the encounter pipeline
 * uses. The page is the safety boundary made legible: physicians can
 * see the EXACT instructions any model receives before describing
 * their patient's encounter.
 *
 * Layout:
 *   • Page header + descriptive-mode callout
 *   • Search filter (name + purpose)
 *   • One section per category (Notes / Vision / Extraction / Live
 *     preview). Cards inside follow the registry's insertion order.
 *
 * Phase B will add per-physician overlays. The card component already
 * prefers `override_text` when present, so the page itself doesn't
 * need to change when that lands.
 */

const CATEGORY_ORDER: readonly PromptCategory[] = [
  "note",
  "vision",
  "extraction",
  "preview",
] as const;

// Each category gets a glyph so the section rules read at a glance,
// mirroring the icon + gold micro-label idiom used elsewhere in the
// portal. Purely decorative — labels still come from t().
const CATEGORY_ICON: Record<PromptCategory, typeof FileText> = {
  note: FileText,
  vision: Eye,
  extraction: ScanLine,
  preview: Radio,
};

export default function AIPromptsPage() {
  const t = useTranslations("AIPrompts");
  const [prompts, setPrompts] = useState<AIPrompt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const xs = await listMyPrompts();
      setPrompts(xs);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  // Filter on lowercase name + purpose. Server stays read-only and
  // returns the full catalog every time (it's small + cacheable on
  // a future revision). The cost of filtering 8 cards client-side is
  // a noop.
  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return prompts;
    return prompts.filter(
      (p) =>
        p.name.toLowerCase().includes(needle) ||
        p.purpose.toLowerCase().includes(needle),
    );
  }, [prompts, query]);

  const grouped = useMemo(() => {
    const buckets: Record<PromptCategory, AIPrompt[]> = {
      note: [],
      vision: [],
      extraction: [],
      preview: [],
    };
    for (const p of filtered) {
      buckets[p.category].push(p);
    }
    return buckets;
  }, [filtered]);

  return (
    <div
      className="aurion-page-padded aurion-container-narrow"
      data-testid="ai-prompts-page"
    >
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("subtitle")}
      />

      <div
        className="mb-6 flex items-start gap-3 rounded-aurion-md border border-gold-200 bg-gold-50 px-4 py-3"
        data-testid="descriptive-mode-callout"
        role="note"
      >
        <Info className="h-5 w-5 text-gold-600 shrink-0 mt-0.5" />
        <div className="space-y-1 text-aurion-callout text-navy-700">
          <p>{t("descriptiveModeCallout")}</p>
          <p className="text-aurion-caption text-navy-500">
            {t("phaseBHint")}
          </p>
        </div>
      </div>

      <div className="mb-5 relative">
        <Search
          className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-navy-300"
          aria-hidden="true"
        />
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder={t("searchPlaceholder")}
          aria-label={t("searchPlaceholder")}
          data-testid="prompts-filter-input"
          className="w-full rounded-aurion-md border border-hairline bg-white py-2.5 pl-9 pr-3 text-aurion-callout text-navy-800 placeholder:text-navy-300 focus:outline-none focus:ring-2 focus:ring-gold-300/40"
        />
      </div>

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          {error}
        </div>
      )}

      {loading ? (
        <Card>
          <LoadingSkeleton lines={8} />
        </Card>
      ) : filtered.length === 0 ? (
        <Card>
          <div className="py-10 text-center">
            <Sparkles className="mx-auto h-10 w-10 text-gold-300 mb-2" />
            <p
              className="aurion-callout text-navy-500"
              data-testid="prompts-no-results"
            >
              {t("noResults")}
            </p>
          </div>
        </Card>
      ) : (
        <div className="space-y-8">
          {CATEGORY_ORDER.map((category) => {
            const inCategory = grouped[category];
            if (inCategory.length === 0) return null;
            const CategoryIcon = CATEGORY_ICON[category];
            return (
              <section
                key={category}
                aria-labelledby={`ai-prompts-category-${category}`}
                data-testid={`prompts-category-${category}`}
              >
                <div className="mb-3 flex items-center gap-2.5">
                  <CategoryIcon
                    className="h-4 w-4 shrink-0 text-gold-600"
                    aria-hidden="true"
                  />
                  <h2
                    id={`ai-prompts-category-${category}`}
                    className="aurion-micro text-gold-600"
                  >
                    {t(`category.${category}`)}
                  </h2>
                  <span
                    className="h-px flex-1 bg-hairline"
                    aria-hidden="true"
                  />
                </div>
                <div className="space-y-4">
                  {inCategory.map((p) => (
                    <PromptCard key={p.id} prompt={p} />
                  ))}
                </div>
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}
