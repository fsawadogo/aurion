"use client";

import { Code2, Download, LayoutGrid, SlidersHorizontal } from "lucide-react";
import { getMe, humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useRouteSegment } from "@/lib/use-route-segment";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import Modal from "@/components/ui/Modal";
import PageHeader from "@/components/portal/PageHeader";
import TemplateDraftPreview from "@/components/portal/TemplateDraftPreview";
import TemplateSectionEditor, {
  normalizeTemplate,
  validateTemplate,
} from "@/components/portal/TemplateSectionEditor";
import {
  deleteMyCustomTemplate,
  listMyCustomTemplates,
  updateMyCustomTemplate,
} from "@/lib/portal-api";
import type { CustomTemplate, TemplateDefinition } from "@/types";

/**
 * /portal/templates/[id] — view + edit a custom template.
 *
 * Two viewing modes: a structured preview (read-only) and a raw-JSON
 * editor for when the physician wants to tweak directly. Save goes
 * through PATCH /me/custom-templates/{id}; the backend re-validates
 * the entire template against the Pydantic schema, so an invalid
 * edit surfaces as a 400 inline.
 *
 * Export downloads the template JSON (just the inner Template shape,
 * not the row metadata) — useful for the upload flow if the
 * physician wants to share the JSON with a colleague offline.
 */
export default function TemplateDetailPage() {
  const t = useTranslations("TemplateDetail");
  const te = useTranslations("TemplateEditor");
  const router = useRouter();
  // Static-export gotcha — see web/lib/use-route-segment.ts. `useParams()`
  // returns the build-time "_" sentinel under `output: "export"`; the hook
  // reads from the URL bar so the real template ID wins at runtime.
  const templateId = useRouteSegment("id");

  const [row, setRow] = useState<CustomTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"preview" | "edit" | "json">("preview");
  const [draftJson, setDraftJson] = useState<string>("");
  // Structured-editor draft, initialized from the loaded template.
  const [draftEdit, setDraftEdit] = useState<TemplateDefinition | null>(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // Ownership: the list can surface shared templates owned by others, whose
  // PATCH/DELETE are owner-scoped server-side (404). Gate Edit/JSON/Delete to
  // the owner; non-owners get read-only Preview. Null until resolved.
  const [meId, setMeId] = useState<string | null>(null);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const owned = meId !== null && row !== null && row.owner_id === meId;

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // No GET-by-id endpoint exists — list and find. Acceptable at
      // pilot scale; a follow-up PR could add a dedicated endpoint
      // if the list grows beyond a few hundred templates.
      const xs = await listMyCustomTemplates();
      const found = xs.find((x) => x.id === templateId);
      if (!found) {
        setError(t("notFound"));
        return;
      }
      setRow(found);
      setDraftJson(JSON.stringify(found.template, null, 2));
      setDraftEdit(found.template);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [templateId, t]);

  useEffect(() => {
    void load();
    void getMe()
      .then((u) => setMeId(u.user_id))
      .catch(() => {});
  }, [load]);

  async function onSave() {
    if (!row) return;
    let parsed: TemplateDefinition;
    try {
      parsed = JSON.parse(draftJson);
    } catch (e) {
      setError(
        t("invalidJson", { error: humanizeError(e, "") }),
      );
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateMyCustomTemplate(row.id, parsed);
      setRow(updated);
      setDraftJson(JSON.stringify(updated.template, null, 2));
      // Keep the structured-editor draft in step with the just-saved content
      // so a later switch to the Edit tab + Save can't silently revert this.
      setDraftEdit(updated.template);
      setMode("preview");
    } catch (e) {
      setError(humanizeError(e, t("saveError")));
    } finally {
      setSaving(false);
    }
  }

  async function onSaveStructured() {
    if (!row || !draftEdit) return;
    // enforceSectionCaps:false mirrors the backend's update path so editing a
    // template whose sections predate the caps isn't blocked (the raw-JSON
    // tab is the escape hatch for the always-on rules).
    const validationKey = validateTemplate(draftEdit, { enforceSectionCaps: false });
    if (validationKey) {
      setError(te(validationKey));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateMyCustomTemplate(row.id, normalizeTemplate(draftEdit));
      setRow(updated);
      setDraftEdit(updated.template);
      setDraftJson(JSON.stringify(updated.template, null, 2));
      setMode("preview");
    } catch (e) {
      setError(humanizeError(e, t("saveError")));
    } finally {
      setSaving(false);
    }
  }

  async function confirmDelete() {
    if (!row) return;
    setDeleting(true);
    try {
      await deleteMyCustomTemplate(row.id);
      router.push("/portal/templates");
    } catch (e) {
      setError(humanizeError(e, t("deleteError")));
      setDeleting(false);
      setConfirmingDelete(false);
    }
  }

  function onExportJson() {
    if (!row) return;
    const blob = new Blob([JSON.stringify(row.template, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${row.template.key}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="aurion-page-padded aurion-container-narrow">
      <PageHeader
        breadcrumb={[
          { label: t("breadcrumbTemplates"), href: "/portal/templates" },
          { label: row?.display_name ?? t("breadcrumbFallback") },
        ]}
        eyebrow={t("eyebrow")}
        title={row?.display_name ?? t("fallbackTitle")}
        description={
          row
            ? <><code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] tracking-tight text-gray-500">{row.key}</code> · {t("metadata", { version: row.version, sections: t("sectionCount", { count: row.template.sections.length }) })}</>
            : undefined
        }
      />

      {loading ? (
        <Card>
          <LoadingSkeleton lines={8} />
        </Card>
      ) : error && !row ? (
        <Card>
          <p className="text-sm text-red-600">{error}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void load()}>
            {t("retry")}
          </Button>
        </Card>
      ) : row ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1 rounded-aurion-md border border-gray-200 p-1">
              <ModeButton
                active={mode === "preview"}
                onClick={() => setMode("preview")}
                icon={<LayoutGrid className="h-4 w-4" />}
                label={t("modePreview")}
              />
              {/* Edit/JSON only for the owner — PATCH is owner-scoped (404). */}
              {owned && (
                <>
                  <ModeButton
                    active={mode === "edit"}
                    onClick={() => setMode("edit")}
                    icon={<SlidersHorizontal className="h-4 w-4" />}
                    label={t("modeEdit")}
                  />
                  <ModeButton
                    active={mode === "json"}
                    onClick={() => setMode("json")}
                    icon={<Code2 className="h-4 w-4" />}
                    label={t("modeJson")}
                  />
                </>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={onExportJson}>
                <Download className="h-4 w-4 mr-1" />
                {t("exportButton")}
              </Button>
              {owned && (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => setConfirmingDelete(true)}
                  loading={deleting}
                  disabled={deleting}
                >
                  {t("deleteButton")}
                </Button>
              )}
            </div>
          </div>

          {error && (
            <div
              role="alert"
              className="rounded-aurion-md bg-red-50 border border-red-200 px-4 py-3 text-aurion-callout text-red-700"
            >
              {error}
            </div>
          )}

          {mode === "preview" ? (
            <TemplateDraftPreview template={row.template} />
          ) : mode === "edit" ? (
            <Card>
              <p className="text-aurion-caption text-navy-500 mb-3">{t("editHint")}</p>
              {draftEdit && (
                <TemplateSectionEditor
                  value={draftEdit}
                  onChange={setDraftEdit}
                  disabled={saving}
                />
              )}
              {error && (
                <p role="alert" className="mt-3 text-aurion-callout text-red-700">
                  {error}
                </p>
              )}
              <div className="mt-4 flex gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  loading={saving}
                  disabled={saving}
                  onClick={() => void onSaveStructured()}
                >
                  {t("saveChanges")}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={saving}
                  onClick={() => setDraftEdit(row.template)}
                >
                  {t("resetToSaved")}
                </Button>
              </div>
            </Card>
          ) : (
            <Card>
              <p id="json-hint" className="text-aurion-caption text-navy-500 mb-2">{t("jsonHint")}</p>
              <textarea
                aria-label={t("jsonLabel")}
                aria-describedby="json-hint"
                className="form-input w-full h-[60vh] font-mono text-xs leading-snug resize-y"
                value={draftJson}
                onChange={(e) => setDraftJson(e.target.value)}
                spellCheck={false}
              />
              <div className="mt-3 flex gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  loading={saving}
                  disabled={saving}
                  onClick={() => void onSave()}
                >
                  {t("saveChanges")}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={saving}
                  onClick={() =>
                    setDraftJson(JSON.stringify(row.template, null, 2))
                  }
                >
                  {t("resetToSaved")}
                </Button>
              </div>
            </Card>
          )}
        </div>
      ) : null}

      <Modal
        isOpen={confirmingDelete}
        onClose={() => {
          if (!deleting) setConfirmingDelete(false);
        }}
        title={t("deleteTitle")}
        footer={
          <>
            <Button
              variant="secondary"
              size="sm"
              disabled={deleting}
              onClick={() => setConfirmingDelete(false)}
            >
              {t("deleteCancel")}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              loading={deleting}
              disabled={deleting}
              onClick={() => void confirmDelete()}
            >
              {t("deleteConfirmButton")}
            </Button>
          </>
        }
      >
        <p className="text-aurion-callout text-navy-600">
          {row ? t("deleteConfirm", { name: row.display_name }) : ""}
        </p>
      </Modal>
    </div>
  );
}

function ModeButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean;
  onClick: () => void;
  icon: React.ReactNode;
  label: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "inline-flex items-center gap-1.5 rounded-aurion-xs px-3 py-1.5 text-xs font-medium transition-colors duration-short " +
        (active
          ? "bg-navy-50 text-navy-800"
          : "text-navy-500 hover:bg-canvas hover:text-navy-700")
      }
      aria-pressed={active}
    >
      {icon}
      {label}
    </button>
  );
}
