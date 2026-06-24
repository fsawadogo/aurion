"use client";

import {
  AlertTriangle,
  CheckCircle2,
  Edit3,
  Eye,
  FileText,
  Info,
  Radio,
  RotateCcw,
  ScanLine,
  Search,
  Sparkles,
  Stethoscope,
} from "lucide-react";
import { humanizeError, parseDetailError } from "@/lib/api";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import PromptCard from "@/components/portal/PromptCard";
import {
  clearSpecialtyGuidance,
  getSpecialtyPrompts,
  listMyPrompts,
  saveSpecialtyGuidance,
} from "@/lib/portal-api";
import type { AIPrompt, PromptCategory, SpecialtyPrompt } from "@/types";

/**
 * /portal/prompts — AI Prompts Transparency.
 *
 * Read-only catalog of the LLM instructions the encounter pipeline uses.
 * Two views:
 *   • "Global prompts" — the registry system prompts (one per category),
 *     overridable per-physician.
 *   • "By specialty" — the specialty layer injected on top of the note
 *     prompt: style guidance + template sections + worked-example summaries.
 */

const CATEGORY_ORDER: readonly PromptCategory[] = [
  "note",
  "vision",
  "extraction",
  "preview",
] as const;

const CATEGORY_ICON: Record<PromptCategory, typeof FileText> = {
  note: FileText,
  vision: Eye,
  extraction: ScanLine,
  preview: Radio,
};

type View = "global" | "specialty";

export default function AIPromptsPage() {
  const t = useTranslations("AIPrompts");
  const [prompts, setPrompts] = useState<AIPrompt[]>([]);
  const [specialties, setSpecialties] = useState<SpecialtyPrompt[]>([]);
  const [view, setView] = useState<View>("global");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [xs, sp] = await Promise.all([
        listMyPrompts(),
        getSpecialtyPrompts(),
      ]);
      setPrompts(xs);
      setSpecialties(sp);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

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
    for (const p of filtered) buckets[p.category].push(p);
    return buckets;
  }, [filtered]);

  const filteredSpecialties = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return specialties;
    return specialties.filter(
      (s) =>
        s.display_name.toLowerCase().includes(needle) ||
        s.key.toLowerCase().includes(needle) ||
        s.guidance.toLowerCase().includes(needle),
    );
  }, [specialties, query]);

  const empty =
    view === "global" ? filtered.length === 0 : filteredSpecialties.length === 0;

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
        className="mb-5 flex items-start gap-3 rounded-aurion-md border border-gold-200 bg-gold-50 px-4 py-3"
        data-testid="descriptive-mode-callout"
        role="note"
      >
        <Info className="h-5 w-5 text-gold-600 shrink-0 mt-0.5" />
        <div className="space-y-1 text-aurion-callout text-navy-700">
          <p>{t("descriptiveModeCallout")}</p>
          <p className="text-aurion-caption text-navy-500">{t("phaseBHint")}</p>
        </div>
      </div>

      {/* View toggle: Global prompts ↔ By specialty */}
      <div
        className="mb-5 inline-flex rounded-aurion-md border border-hairline bg-white p-0.5"
        role="tablist"
        aria-label={t("title")}
      >
        {(["global", "specialty"] as const).map((v) => {
          const active = view === v;
          const Icon = v === "global" ? FileText : Stethoscope;
          return (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setView(v)}
              data-testid={`prompts-view-${v}`}
              className={
                "flex items-center gap-1.5 rounded-aurion-sm px-3 py-1.5 text-aurion-callout font-medium transition-colors " +
                (active
                  ? "bg-navy-50 text-navy-800"
                  : "text-navy-400 hover:text-navy-700")
              }
            >
              <Icon className="h-4 w-4" aria-hidden="true" />
              {t(`view.${v}`)}
            </button>
          );
        })}
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
      ) : empty ? (
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
      ) : view === "global" ? (
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
                  <span className="h-px flex-1 bg-hairline" aria-hidden="true" />
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
      ) : (
        <div className="space-y-4" data-testid="prompts-by-specialty">
          {filteredSpecialties.map((s) => (
            <SpecialtyCard key={s.key} specialty={s} />
          ))}
        </div>
      )}
    </div>
  );
}

function SpecialtyCard({ specialty }: { specialty: SpecialtyPrompt }) {
  const t = useTranslations("AIPrompts.bySpecialty");
  const [current, setCurrent] = useState<SpecialtyPrompt>(specialty);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(specialty.active_guidance);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const s = current;

  function openEditor() {
    setDraft(s.active_guidance);
    setError(null);
    setEditing(true);
  }

  async function onSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await saveSpecialtyGuidance(s.key, draft.trim());
      setCurrent(updated);
      setEditing(false);
    } catch (e) {
      setError(parseDetailError(e, t("errorSaving")));
    } finally {
      setSaving(false);
    }
  }

  async function onClear() {
    setSaving(true);
    setError(null);
    try {
      const updated = await clearSpecialtyGuidance(s.key);
      setCurrent(updated);
      setDraft(updated.active_guidance);
      setEditing(false);
    } catch (e) {
      setError(parseDetailError(e, t("errorSaving")));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div data-testid={`specialty-card-${s.key}`}>
    <Card>
      <div className="flex items-center gap-2.5">
        <Stethoscope className="h-4 w-4 shrink-0 text-gold-600" aria-hidden="true" />
        <h3 className="aurion-headline text-navy-800">{s.display_name}</h3>
        <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-500">
          {s.key}
        </code>
        {s.is_overridden && (
          <span data-testid={`specialty-card-${s.key}-override-badge`}>
            <Badge variant="success">{t("customBadge")}</Badge>
          </span>
        )}
        <span className="ml-auto flex items-center gap-2">
          {s.examples_count > 0 && (
            <Badge variant="neutral">
              {t("exampleCount", { count: s.examples_count })}
            </Badge>
          )}
          {!editing && (
            <button
              type="button"
              onClick={openEditor}
              data-testid={`specialty-card-${s.key}-edit`}
              className="inline-flex items-center gap-1.5 rounded-aurion-xs bg-navy-50 px-2 py-1 text-aurion-micro text-navy-600 ring-1 ring-inset ring-navy-200 hover:bg-navy-100 transition-colors duration-short"
            >
              <Edit3 className="h-3 w-3" aria-hidden="true" />
              {t("editButton")}
            </button>
          )}
        </span>
      </div>

      {/* When the specialty-style layer is not wired into live note generation,
          edits are saved but dormant — say so plainly. */}
      {!s.enabled && (
        <div
          className="mt-3 flex items-start gap-2 rounded-aurion-md border border-gold-200 bg-gold-50 px-3 py-2"
          data-testid={`specialty-card-${s.key}-inactive`}
          role="note"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 text-gold-600 mt-0.5" aria-hidden="true" />
          <p className="text-aurion-caption text-navy-600">{t("inactiveWarning")}</p>
        </div>
      )}

      {/* Style guidance — the specialty-specific instruction layered onto
          the note prompt. Editable (CLINICIAN-only on the server). */}
      <div className="mt-3">
        <div className="mb-1.5 flex items-center gap-2">
          <p className="aurion-micro text-gold-600">{t("guidanceLabel")}</p>
          {s.is_overridden && !editing && (
            <span className="inline-flex items-center gap-1 text-aurion-micro text-emerald-600">
              <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
              {t("activeCustom")}
            </span>
          )}
        </div>

        {editing ? (
          <div className="space-y-2">
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              rows={6}
              aria-label={t("guidanceLabel")}
              data-testid={`specialty-guidance-input-${s.key}`}
              className="w-full rounded-aurion-md border border-hairline bg-white px-3 py-2 text-aurion-callout leading-relaxed text-navy-800 focus:outline-none focus:ring-2 focus:ring-gold-300/40 font-mono"
              disabled={saving}
            />
            {error && (
              <p
                role="alert"
                className="text-aurion-caption text-red-700"
                data-testid={`specialty-guidance-error-${s.key}`}
              >
                {error}
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <Button
                variant="primary"
                size="sm"
                loading={saving}
                disabled={saving || !draft.trim()}
                onClick={() => void onSave()}
                data-testid={`specialty-guidance-save-${s.key}`}
              >
                {t("save")}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={saving}
                onClick={() => setDraft(s.guidance)}
              >
                <RotateCcw className="h-3.5 w-3.5 mr-1" aria-hidden="true" />
                {t("resetToDefault")}
              </Button>
              {s.is_overridden && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={saving}
                  onClick={() => void onClear()}
                  data-testid={`specialty-guidance-clear-${s.key}`}
                  className="text-navy-500 hover:text-navy-700"
                >
                  {t("useDefault")}
                </Button>
              )}
              <Button
                variant="ghost"
                size="sm"
                disabled={saving}
                onClick={() => {
                  setEditing(false);
                  setError(null);
                }}
              >
                {t("cancel")}
              </Button>
            </div>
          </div>
        ) : s.active_guidance ? (
          <p className="rounded-aurion-md border border-hairline bg-gray-50 px-3 py-2 text-aurion-callout leading-relaxed text-navy-700">
            {s.active_guidance}
          </p>
        ) : (
          <p className="text-aurion-caption text-navy-400">{t("noGuidance")}</p>
        )}
      </div>

      {/* Template sections + their visual-trigger keywords. */}
      <div className="mt-4">
        <p className="aurion-micro text-gold-600 mb-1.5">{t("sectionsLabel")}</p>
        <ul className="space-y-2">
          {s.sections.map((sec) => (
            <li key={sec.id} className="rounded-aurion-md border border-hairline px-3 py-2">
              <div className="flex items-center gap-2">
                <span className="text-aurion-callout font-medium text-navy-800">
                  {sec.title}
                </span>
                <Badge variant={sec.required ? "warning" : "neutral"}>
                  {sec.required ? t("required") : t("optional")}
                </Badge>
              </div>
              {sec.description && (
                <p className="mt-0.5 text-aurion-caption text-navy-500">
                  {sec.description}
                </p>
              )}
              {sec.visual_trigger_keywords.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {sec.visual_trigger_keywords.map((kw) => (
                    <span
                      key={kw}
                      className="rounded bg-navy-50 px-1.5 py-0.5 text-[10px] text-navy-500"
                    >
                      {kw}
                    </span>
                  ))}
                </div>
              )}
            </li>
          ))}
        </ul>
      </div>

      {/* Worked-example summaries. */}
      {s.examples.length > 0 && (
        <div className="mt-4">
          <p className="aurion-micro text-gold-600 mb-1.5">{t("examplesLabel")}</p>
          <ul className="space-y-1">
            {s.examples.map((ex, i) => (
              <li key={i} className="text-aurion-caption text-navy-600">
                • {ex.description}
                {ex.populated_sections.length > 0 && (
                  <span className="text-navy-400">
                    {" "}
                    — {t("populates")}: {ex.populated_sections.join(", ")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
    </div>
  );
}
