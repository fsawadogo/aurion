"use client";

/**
 * Admin Shared/Org Templates — author OR edit a note template (structure + AI
 * instructions) and share it to every clinician (tpl-04, tpl-07). Extracted
 * from the page (#579) so it renders BOTH standalone
 * (/portal/admin/shared-templates) and as a section of the unified admin
 * Library (/portal/admin/library). No PageHeader — the host supplies the
 * heading; the "New" action lives in a section toolbar so it sits atop the list
 * it creates into in either context.
 */

import { LayoutTemplate, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
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
  updateSharedTemplate,
} from "@/lib/api";
import type { CustomTemplate, TemplateDefinition } from "@/types";

/** Coerce a stored template into a fully-shaped editor draft — defensive against
 *  older rows missing optional section fields so the editor never crashes. */
function toDraft(tpl: TemplateDefinition): TemplateDefinition {
  return {
    key: tpl.key,
    display_name: tpl.display_name,
    version: tpl.version,
    system_prompt: tpl.system_prompt ?? "",
    sections: (tpl.sections ?? []).map((s) => ({
      id: s.id,
      title: s.title,
      required: s.required ?? true,
      description: s.description ?? "",
      visual_trigger_keywords: s.visual_trigger_keywords ?? [],
    })),
  };
}

export default function AdminSharedTemplatesSection() {
  const t = useTranslations("AdminSharedTemplates");
  const te = useTranslations("TemplateEditor");

  const [items, setItems] = useState<CustomTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  // null = creating a new template; an id = editing that existing one.
  const [editingId, setEditingId] = useState<string | null>(null);
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
    setEditingId(null);
    setError(null);
    setEditorOpen(true);
  }

  function startEdit(tpl: CustomTemplate) {
    setDraft(toDraft(tpl.template));
    setEditingId(tpl.id);
    setError(null);
    setEditorOpen(true);
  }

  function closeEditor() {
    setEditorOpen(false);
    setEditingId(null);
  }

  async function onSave() {
    // Section length/count caps are create-time only — the backend skips them on
    // update so a pre-cap template stays editable; mirror that here.
    const vk = validateTemplate(draft, { enforceSectionCaps: editingId === null });
    if (vk) {
      setError(te(vk));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = normalizeTemplate(draft);
      if (editingId) {
        await updateSharedTemplate(editingId, payload);
      } else {
        await createSharedTemplate(payload);
      }
      closeEditor();
      await load();
    } catch (e) {
      setError(humanizeError(e, editingId ? t("editError") : t("saveError")));
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
    <div data-testid="shared-templates-section">
      {!editorOpen && (
        <div className="mb-4 flex justify-end">
          <Button onClick={startCreate} data-testid="new-shared-template">
            <Plus className="h-4 w-4 mr-1.5" aria-hidden="true" />
            {t("createButton")}
          </Button>
        </div>
      )}

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
          data-testid="shared-templates-error"
        >
          {error}
        </div>
      )}

      {editorOpen && (
        <Card className="mb-5">
          <p className="mb-4 text-aurion-callout text-navy-500">
            {editingId ? t("editHint") : t("createHint")}
          </p>
          <TemplateSectionEditor value={draft} onChange={setDraft} disabled={saving} />
          <div className="mt-4 flex items-center justify-end gap-2">
            <Button variant="ghost" onClick={closeEditor} disabled={saving}>
              {t("cancel")}
            </Button>
            <Button onClick={onSave} loading={saving} data-testid="save-shared-template">
              {editingId ? t("saveChanges") : t("save")}
            </Button>
          </div>
        </Card>
      )}

      {loading ? (
        <Card>
          <LoadingSkeleton lines={5} />
        </Card>
      ) : items.length === 0 && !editorOpen ? (
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
                  <div className="flex shrink-0 items-center gap-0.5">
                    <button
                      type="button"
                      onClick={() => startEdit(tpl)}
                      aria-label={t("edit")}
                      title={t("edit")}
                      data-testid={`edit-shared-${tpl.id}`}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-aurion-xs text-navy-500 transition-colors hover:bg-canvas hover:text-navy-700"
                    >
                      <Pencil className="h-4 w-4" />
                    </button>
                    <button
                      type="button"
                      onClick={() => void onDelete(tpl.id)}
                      aria-label={t("delete")}
                      title={t("delete")}
                      data-testid={`delete-shared-${tpl.id}`}
                      className="inline-flex h-8 w-8 items-center justify-center rounded-aurion-xs text-navy-500 transition-colors hover:bg-canvas hover:text-red-600"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                </div>
              </Card>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
