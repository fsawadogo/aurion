"use client";

/**
 * /portal/admin/templates — built-in specialty template management (#72).
 * ADMIN + COMPLIANCE_OFFICER (mirrors the backend `_ROLES` gate).
 *
 * Lists the bundled templates (+ override badge), and edits one in place
 * via the shared TemplateSectionEditor (sections, required flags, and the
 * per-section visual-trigger keywords that CLAUDE.md schedules for
 * post-pilot population). Saves write an admin override that the note
 * pipeline honours at runtime (immediately on the serving task, ~10s
 * fleet-wide — PR #403); Revert deletes the override and restores the
 * disk default.
 *
 * The template key is immutable here — it's the path identity of a
 * bundled template (the editor's key field is forced back on change).
 */

import { LayoutGrid, RotateCcw, Save, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import Modal from "@/components/ui/Modal";
import PageHeader from "@/components/portal/PageHeader";
import TemplateSectionEditor, {
  normalizeTemplate,
  validateTemplate,
} from "@/components/portal/TemplateSectionEditor";
import {
  getAdminTemplateDetail,
  getAdminTemplates,
  humanizeError,
  putAdminTemplate,
  revertAdminTemplate,
} from "@/lib/api";
import type { AdminTemplateSummary, TemplateDefinition } from "@/types";

export default function AdminTemplatesPage() {
  const t = useTranslations("AdminTemplates");
  const tEditor = useTranslations("TemplateEditor");

  const [list, setList] = useState<AdminTemplateSummary[] | null>(null);
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const [draft, setDraft] = useState<TemplateDefinition | null>(null);
  const [isOverride, setIsOverride] = useState(false);
  const [loading, setLoading] = useState(true);
  const [detailLoading, setDetailLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [reverting, setReverting] = useState(false);
  const [confirmRevert, setConfirmRevert] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const loadList = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await getAdminTemplates();
      setList(res.items);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  async function openTemplate(key: string) {
    setSelectedKey(key);
    setDraft(null);
    setDetailLoading(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await getAdminTemplateDetail(key);
      setDraft(res.template);
      setIsOverride(res.is_override);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
      setSelectedKey(null);
    } finally {
      setDetailLoading(false);
    }
  }

  async function onSave() {
    if (!draft || !selectedKey) return;
    const normalized = normalizeTemplate({ ...draft, key: selectedKey });
    const problem = validateTemplate(normalized);
    if (problem) {
      setError(tEditor(problem));
      return;
    }
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const res = await putAdminTemplate(selectedKey, normalized);
      setDraft(res.template);
      setIsOverride(true);
      setSuccess(t("saveSuccess"));
      await loadList();
    } catch (e) {
      setError(humanizeError(e, t("saveError")));
    } finally {
      setSaving(false);
    }
  }

  async function onRevert() {
    if (!selectedKey) return;
    setReverting(true);
    setError(null);
    setSuccess(null);
    try {
      await revertAdminTemplate(selectedKey);
      setConfirmRevert(false);
      setSuccess(t("revertSuccess"));
      await loadList();
      // Reload the now-default detail.
      const res = await getAdminTemplateDetail(selectedKey);
      setDraft(res.template);
      setIsOverride(res.is_override);
    } catch (e) {
      setError(humanizeError(e, t("revertError")));
      setConfirmRevert(false);
    } finally {
      setReverting(false);
    }
  }

  const busy = saving || reverting || detailLoading;

  // Client-side filter by display name or template key (Stitch search).
  const q = query.trim().toLowerCase();
  const filtered = (list ?? []).filter(
    (i) =>
      !q ||
      i.display_name.toLowerCase().includes(q) ||
      i.template_key.toLowerCase().includes(q),
  );

  return (
    <div className="aurion-page-padded aurion-container-narrow" data-testid="admin-templates-page">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} description={t("description")} />

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          {error}
        </div>
      )}
      {success && (
        <div
          className="mb-4 rounded-aurion-md border border-green-200 bg-green-50 px-4 py-3 text-aurion-callout text-green-800"
          role="status"
        >
          {success}
        </div>
      )}

      {/* Search (Stitch) — filters the bundled-template list by name or key. */}
      {!loading && list && (
        <div className="relative mb-4">
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
            data-testid="template-search"
            className="w-full rounded-aurion-md border border-navy-200 bg-surface py-2 pl-9 pr-3 text-aurion-callout text-navy-800 placeholder:text-navy-300 focus:outline-none focus:ring-2 focus:ring-gold-300/40"
          />
        </div>
      )}

      <Card>
        {loading || !list ? (
          <LoadingSkeleton lines={6} />
        ) : filtered.length === 0 ? (
          <p className="py-8 text-center text-aurion-callout text-navy-500">
            {t("noMatches")}
          </p>
        ) : (
          <ul className="divide-y divide-hairline">
            {filtered.map((item) => {
              const active = item.template_key === selectedKey;
              return (
                <li key={item.template_key}>
                  <button
                    type="button"
                    onClick={() => void openTemplate(item.template_key)}
                    disabled={busy && !active}
                    aria-expanded={active}
                    data-testid={`template-item-${item.template_key}`}
                    className={
                      "flex w-full items-center gap-3 py-3 -mx-2 px-2 text-left rounded-aurion-md transition-colors duration-short " +
                      (active ? "bg-canvas/60" : "hover:bg-canvas/40")
                    }
                  >
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-aurion-md bg-navy-50 text-navy-600 ring-1 ring-inset ring-navy-100">
                      <LayoutGrid className="h-4 w-4" />
                    </span>
                    <span className="flex-1 min-w-0">
                      <span className="block truncate text-aurion-callout font-medium text-navy-800">
                        {item.display_name}
                      </span>
                      <span className="mt-0.5 block text-aurion-caption text-navy-500">
                        <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] tracking-tight text-gray-500">
                          {item.template_key}
                        </code>{" "}
                        · {t("metadata", { version: item.version, count: item.section_count })}
                      </span>
                    </span>
                    {item.is_override && (
                      <Badge variant="info" className="shrink-0">
                        {t("overrideBadge")}
                      </Badge>
                    )}
                  </button>

                  {active && (
                    <div className="pb-4 pl-2 pr-2" data-testid="template-editor-panel">
                      {detailLoading || !draft ? (
                        <LoadingSkeleton lines={5} />
                      ) : (
                        <>
                          <TemplateSectionEditor
                            value={draft}
                            onChange={(next) =>
                              // The key is the bundled template's identity —
                              // immutable here regardless of editor input.
                              setDraft({ ...next, key: selectedKey ?? next.key })
                            }
                            disabled={busy}
                          />
                          <div className="mt-3 flex items-center justify-between gap-3">
                            <p className="text-aurion-caption text-navy-400">
                              {isOverride ? t("liveOverrideHint") : t("liveDefaultHint")}
                            </p>
                            <div className="flex gap-2">
                              {isOverride && (
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  disabled={busy}
                                  onClick={() => setConfirmRevert(true)}
                                >
                                  <RotateCcw className="h-3.5 w-3.5 mr-1" />
                                  {t("revert")}
                                </Button>
                              )}
                              <Button
                                variant="primary"
                                size="sm"
                                loading={saving}
                                disabled={busy}
                                onClick={() => void onSave()}
                              >
                                <Save className="h-4 w-4 mr-1" />
                                {t("save")}
                              </Button>
                            </div>
                          </div>
                        </>
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      <Modal
        isOpen={confirmRevert}
        onClose={() => {
          if (!reverting) setConfirmRevert(false);
        }}
        title={t("revertTitle")}
        footer={
          <>
            <Button
              variant="secondary"
              size="sm"
              disabled={reverting}
              onClick={() => setConfirmRevert(false)}
            >
              {t("revertCancel")}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              loading={reverting}
              disabled={reverting}
              onClick={() => void onRevert()}
            >
              {t("revertConfirm")}
            </Button>
          </>
        }
      >
        <p className="text-aurion-callout text-navy-600">
          {selectedKey ? t("revertBody", { key: selectedKey }) : ""}
        </p>
      </Modal>
    </div>
  );
}
