"use client";

/**
 * /portal/admin/shared-templates — admin org/shared templates (tpl-04).
 *
 * Prompt-Studio-style admin surface: author a note template (structure + AI
 * instructions, via the shared TemplateSectionEditor) and share it to every
 * clinician. Shared templates appear read-only in each clinician's Templates
 * library + the upload/visit pickers and drive note generation when picked.
 * ADMIN-only (the nav link + the backend /admin/shared-templates are gated).
 */

import { LayoutTemplate, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import TemplateSectionEditor, {
  blankTemplate,
  normalizeTemplate,
  validateTemplate,
} from "@/components/portal/TemplateSectionEditor";
import {
  createSharedTemplate,
  deleteSharedTemplate,
  humanizeError,
  listSharedTemplates,
} from "@/lib/api";
import type { CustomTemplate, TemplateDefinition } from "@/types";

export default function SharedTemplatesPage() {
  const t = useTranslations("AdminSharedTemplates");
  const te = useTranslations("TemplateEditor");

  const [items, setItems] = useState<CustomTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<TemplateDefinition>(() => blankTemplate());
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setItems(await listSharedTemplates());
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  function startCreate() {
    setDraft(blankTemplate());
    setError(null);
    setCreating(true);
  }

  async function onSave() {
    const vk = validateTemplate(draft);
    if (vk) {
      setError(te(vk));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await createSharedTemplate(normalizeTemplate(draft));
      setCreating(false);
      await load();
    } catch (e) {
      setError(humanizeError(e, t("saveError")));
    } finally {
      setSaving(false);
    }
  }

  async function onDelete(id: string) {
    setError(null);
    try {
      await deleteSharedTemplate(id);
      await load();
    } catch (e) {
      setError(humanizeError(e, t("deleteError")));
    }
  }

  return (
    <div className="aurion-page-padded" data-testid="shared-templates-page">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={
          creating ? undefined : (
            <Button onClick={startCreate} data-testid="new-shared-template">
              <Plus className="h-4 w-4 mr-1.5" aria-hidden="true" />
              {t("createButton")}
            </Button>
          )
        }
      />

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
          data-testid="shared-templates-error"
        >
          {error}
        </div>
      )}

      {creating && (
        <Card className="mb-5">
          <p className="mb-4 text-aurion-callout text-navy-500">{t("createHint")}</p>
          <TemplateSectionEditor value={draft} onChange={setDraft} disabled={saving} />
          <div className="mt-4 flex items-center justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => setCreating(false)}
              disabled={saving}
            >
              {t("cancel")}
            </Button>
            <Button onClick={onSave} loading={saving} data-testid="save-shared-template">
              {t("save")}
            </Button>
          </div>
        </Card>
      )}

      {loading ? (
        <Card>
          <LoadingSkeleton lines={5} />
        </Card>
      ) : items.length === 0 && !creating ? (
        <Card>
          <div className="py-10 text-center" data-testid="shared-templates-empty">
            <LayoutTemplate
              className="mx-auto h-9 w-9 text-gold-300 mb-2"
              aria-hidden="true"
            />
            <p className="aurion-callout text-navy-500">{t("empty")}</p>
          </div>
        </Card>
      ) : (
        <ul className="space-y-2" data-testid="shared-template-list">
          {items.map((tpl) => (
            <li key={tpl.id}>
              <Card>
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="aurion-callout font-medium text-navy-800">
                        {tpl.display_name}
                      </span>
                      <Badge variant="neutral">v{tpl.version}</Badge>
                    </div>
                    <code className="text-[11px] font-mono text-navy-400">
                      {tpl.key}
                    </code>
                  </div>
                  <button
                    type="button"
                    onClick={() => void onDelete(tpl.id)}
                    aria-label={t("delete")}
                    title={t("delete")}
                    data-testid={`delete-shared-${tpl.id}`}
                    className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-aurion-xs text-navy-500 transition-colors hover:bg-canvas hover:text-red-600"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
