"use client";

/**
 * Structured editor for a custom note template (#318 follow-up).
 *
 * A controlled component: the parent owns the `TemplateDefinition` draft and
 * the Save call. Produces a deterministic template client-side — no LLM — so
 * it's reused by both the manual "Build it" tab on /portal/templates/new
 * (→ createMyCustomTemplate) and the structured "Edit" mode on
 * /portal/templates/[id] (→ updateMyCustomTemplate).
 *
 * Field limits mirror the backend custom-template caps
 * (app/modules/custom_templates/service.py): key<=50 / display_name<=100 /
 * section title<=100 / description<=500 / <=50 sections. Keyword chips are
 * kept as a comma-separated string while editing (empties preserved so a
 * trailing comma works); the parent strips empties via `normalizeTemplate`
 * before saving.
 */

import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import Button from "@/components/ui/Button";
import type { TemplateDefinition, TemplateSection } from "@/types";

export const MAX_SECTIONS = 50;

/** Lowercase snake_case slug, capped at the backend key length. */
export function slugify(s: string): string {
  return s
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 50);
}

/** A blank starter template for the manual-create flow (one empty section). */
export function blankTemplate(): TemplateDefinition {
  return {
    key: "",
    display_name: "",
    version: "1.0",
    sections: [
      { id: "", title: "", required: true, visual_trigger_keywords: [], description: "" },
    ],
  };
}

/** Strip transient empty keywords (kept while typing) before save. */
export function normalizeTemplate(t: TemplateDefinition): TemplateDefinition {
  return {
    ...t,
    key: t.key.trim(),
    display_name: t.display_name.trim(),
    version: t.version.trim() || "1.0",
    sections: t.sections.map((s) => ({
      ...s,
      id: s.id.trim(),
      title: s.title.trim(),
      visual_trigger_keywords: s.visual_trigger_keywords
        .map((k) => k.trim())
        .filter(Boolean),
    })),
  };
}

/** Client-side validation mirroring the backend caps — returns the first
 *  problem (a TemplateEditor i18n key) or null when the draft is saveable.
 *
 *  `enforceSectionCaps` (default true, the create path) gates the non-DB-backed
 *  section length/count caps. The UPDATE path passes false to mirror the
 *  backend, which deliberately skips those on update so a clinician isn't
 *  locked out of editing a template whose sections predate the caps. The
 *  always-on checks (key/name format, >=1 section, section id/title required,
 *  duplicate ids) match the backend's update-time rules. */
export function validateTemplate(
  t: TemplateDefinition,
  opts: { enforceSectionCaps?: boolean } = {},
): string | null {
  const enforceSectionCaps = opts.enforceSectionCaps ?? true;
  const key = t.key.trim();
  if (!key) return "errKeyRequired";
  if (!/^[a-z][a-z0-9_]*$/.test(key)) return "errKeyShape";
  if (key.length > 50) return "errKeyLong";
  if (!t.display_name.trim()) return "errNameRequired";
  if (t.display_name.trim().length > 100) return "errNameLong";
  if (t.sections.length === 0) return "errNoSections";
  if (enforceSectionCaps && t.sections.length > MAX_SECTIONS) return "errTooManySections";
  for (const s of t.sections) {
    if (!s.id.trim()) return "errSectionId";
    if (!s.title.trim()) return "errSectionTitle";
    if (enforceSectionCaps) {
      if ((s.description ?? "").length > 500) return "errSectionDesc";
      const kws = s.visual_trigger_keywords.map((k) => k.trim()).filter(Boolean);
      if (kws.length > 50) return "errTooManyKeywords";
      if (kws.some((k) => k.length > 50)) return "errKeywordLong";
    }
  }
  // Duplicate section ids would silently collapse downstream — always checked.
  const ids = t.sections.map((s) => s.id.trim());
  if (new Set(ids).size !== ids.length) return "errDuplicateId";
  return null;
}

interface Props {
  value: TemplateDefinition;
  onChange: (next: TemplateDefinition) => void;
  disabled?: boolean;
}

export default function TemplateSectionEditor({
  value,
  onChange,
  disabled = false,
}: Props) {
  const t = useTranslations("TemplateEditor");

  const setMeta = (patch: Partial<TemplateDefinition>) =>
    onChange({ ...value, ...patch });

  const setSection = (idx: number, patch: Partial<TemplateSection>) =>
    onChange({
      ...value,
      sections: value.sections.map((s, i) => (i === idx ? { ...s, ...patch } : s)),
    });

  const addSection = () => {
    if (value.sections.length >= MAX_SECTIONS) return;
    onChange({
      ...value,
      sections: [
        ...value.sections,
        { id: "", title: "", required: true, visual_trigger_keywords: [], description: "" },
      ],
    });
  };

  const removeSection = (idx: number) =>
    onChange({ ...value, sections: value.sections.filter((_, i) => i !== idx) });

  const move = (idx: number, dir: -1 | 1) => {
    const j = idx + dir;
    if (j < 0 || j >= value.sections.length) return;
    const sections = [...value.sections];
    [sections[idx], sections[j]] = [sections[j], sections[idx]];
    onChange({ ...value, sections });
  };

  const fieldLabel = "block text-aurion-caption font-medium text-navy-600 mb-1";
  const last = value.sections.length - 1;

  return (
    <div className="space-y-5">
      {/* ── Template metadata ─────────────────────────────────────────── */}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <label className="sm:col-span-2">
          <span className={fieldLabel}>{t("displayName")}</span>
          <input
            className="form-input w-full"
            value={value.display_name}
            onChange={(e) => setMeta({ display_name: e.target.value })}
            placeholder={t("displayNamePlaceholder")}
            disabled={disabled}
            maxLength={100}
          />
        </label>
        <label>
          <span className={fieldLabel}>{t("version")}</span>
          <input
            className="form-input w-full"
            value={value.version}
            onChange={(e) => setMeta({ version: e.target.value })}
            placeholder="1.0"
            disabled={disabled}
            maxLength={20}
          />
        </label>
        <label className="sm:col-span-3">
          <span className={fieldLabel}>{t("key")}</span>
          <input
            className="form-input w-full font-mono"
            value={value.key}
            onChange={(e) => setMeta({ key: e.target.value })}
            onBlur={(e) => e.target.value && setMeta({ key: slugify(e.target.value) })}
            placeholder={t("keyPlaceholder")}
            disabled={disabled}
            maxLength={50}
          />
          <span className="mt-1 block text-aurion-caption text-navy-400">
            {t("keyHint")}
          </span>
        </label>
      </div>

      {/* ── Sections ──────────────────────────────────────────────────── */}
      <div>
        <h3 className="aurion-micro mb-2 text-gold-600">{t("sectionsHeading")}</h3>
        <div className="space-y-3">
          {value.sections.map((sec, idx) => (
            <div
              key={idx}
              className="rounded-aurion-md border border-gray-200 bg-white p-3"
              data-testid={`section-row-${idx}`}
            >
              <div className="mb-2 flex items-center justify-between">
                <span className="inline-flex h-5 w-5 items-center justify-center rounded-full bg-navy-50 text-[10px] font-semibold text-navy-700">
                  {idx + 1}
                </span>
                <div className="flex items-center gap-0.5">
                  <IconBtn
                    onClick={() => move(idx, -1)}
                    disabled={disabled || idx === 0}
                    label={t("moveUp")}
                  >
                    <ArrowUp className="h-4 w-4" />
                  </IconBtn>
                  <IconBtn
                    onClick={() => move(idx, 1)}
                    disabled={disabled || idx === last}
                    label={t("moveDown")}
                  >
                    <ArrowDown className="h-4 w-4" />
                  </IconBtn>
                  <IconBtn
                    onClick={() => removeSection(idx)}
                    disabled={disabled}
                    label={t("removeSection")}
                    data-testid={`section-remove-${idx}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </IconBtn>
                </div>
              </div>

              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                <label>
                  <span className={fieldLabel}>{t("sectionTitle")}</span>
                  <input
                    className="form-input w-full"
                    value={sec.title}
                    onChange={(e) => setSection(idx, { title: e.target.value })}
                    placeholder={t("sectionTitlePlaceholder")}
                    disabled={disabled}
                    maxLength={100}
                    data-testid={`section-title-${idx}`}
                  />
                </label>
                <label>
                  <span className={fieldLabel}>{t("sectionId")}</span>
                  <input
                    className="form-input w-full font-mono"
                    value={sec.id}
                    onChange={(e) => setSection(idx, { id: e.target.value })}
                    onBlur={(e) =>
                      e.target.value && setSection(idx, { id: slugify(e.target.value) })
                    }
                    placeholder={t("sectionIdPlaceholder")}
                    disabled={disabled}
                    maxLength={50}
                  />
                </label>
              </div>

              <label className="mt-2 block">
                <span className={fieldLabel}>{t("sectionDescription")}</span>
                <textarea
                  className="form-input w-full resize-y"
                  rows={2}
                  value={sec.description}
                  onChange={(e) => setSection(idx, { description: e.target.value })}
                  placeholder={t("sectionDescriptionPlaceholder")}
                  disabled={disabled}
                  maxLength={500}
                />
              </label>

              <label className="mt-2 block">
                <span className={fieldLabel}>{t("sectionKeywords")}</span>
                <input
                  className="form-input w-full"
                  value={sec.visual_trigger_keywords.join(", ")}
                  onChange={(e) =>
                    setSection(idx, {
                      // keep empties while typing so a trailing comma works;
                      // normalizeTemplate strips them before save.
                      visual_trigger_keywords: e.target.value.split(",").map((k) => k.trimStart()),
                    })
                  }
                  placeholder={t("sectionKeywordsPlaceholder")}
                  disabled={disabled}
                />
                <span className="mt-1 block text-aurion-caption text-navy-400">
                  {t("sectionKeywordsHint")}
                </span>
              </label>

              <label className="mt-2 flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={sec.required}
                  onChange={(e) => setSection(idx, { required: e.target.checked })}
                  disabled={disabled}
                  className="h-4 w-4 rounded border-gray-300 text-gold-600 focus:ring-gold-300/40"
                />
                <span className="text-aurion-caption text-navy-600">
                  {t("sectionRequired")}
                </span>
              </label>
            </div>
          ))}
        </div>

        {value.sections.length >= MAX_SECTIONS ? (
          <p className="mt-3 text-aurion-caption text-navy-400">
            {t("sectionsLimit", { max: MAX_SECTIONS })}
          </p>
        ) : (
          <Button
            variant="secondary"
            size="sm"
            className="mt-3"
            onClick={addSection}
            disabled={disabled}
          >
            <Plus className="mr-1 h-4 w-4" />
            {t("addSection")}
          </Button>
        )}
      </div>
    </div>
  );
}

function IconBtn({
  onClick,
  disabled,
  label,
  children,
  ...rest
}: {
  onClick: () => void;
  disabled?: boolean;
  label: string;
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="inline-flex h-8 w-8 items-center justify-center rounded-aurion-xs text-navy-500 transition-colors duration-short hover:bg-canvas hover:text-navy-700 disabled:opacity-30 disabled:hover:bg-transparent"
      {...rest}
    >
      {children}
    </button>
  );
}
