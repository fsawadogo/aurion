"use client";

import { Code2, Download, LayoutGrid } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useRouteSegment } from "@/lib/use-route-segment";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import TemplateDraftPreview from "@/components/portal/TemplateDraftPreview";
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
  const router = useRouter();
  // Static-export gotcha — see web/lib/use-route-segment.ts. `useParams()`
  // returns the build-time "_" sentinel under `output: "export"`; the hook
  // reads from the URL bar so the real template ID wins at runtime.
  const templateId = useRouteSegment("id");

  const [row, setRow] = useState<CustomTemplate | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"preview" | "json">("preview");
  const [draftJson, setDraftJson] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // No GET-by-id endpoint exists — list and find. Acceptable at
      // pilot scale; a follow-up PR could add a dedicated endpoint
      // if the list grows beyond a few hundred templates.
      const xs = await listMyCustomTemplates();
      const found = xs.find((t) => t.id === templateId);
      if (!found) {
        setError("Template not found.");
        return;
      }
      setRow(found);
      setDraftJson(JSON.stringify(found.template, null, 2));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load template.");
    } finally {
      setLoading(false);
    }
  }, [templateId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSave() {
    if (!row) return;
    let parsed: TemplateDefinition;
    try {
      parsed = JSON.parse(draftJson);
    } catch (e) {
      setError("JSON didn't parse: " + (e instanceof Error ? e.message : ""));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await updateMyCustomTemplate(row.id, parsed);
      setRow(updated);
      setDraftJson(JSON.stringify(updated.template, null, 2));
      setMode("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  async function onDelete() {
    if (!row) return;
    if (!confirm(`Delete custom template "${row.display_name}"?`)) return;
    setDeleting(true);
    try {
      await deleteMyCustomTemplate(row.id);
      router.push("/portal/templates");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed.");
      setDeleting(false);
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
          { label: "Templates", href: "/portal/templates" },
          { label: row?.display_name ?? "Template" },
        ]}
        eyebrow="Custom template"
        title={row?.display_name ?? "Template"}
        description={
          row
            ? <><span className="font-mono">{row.key}</span> · v{row.version} · {row.template.sections.length} section{row.template.sections.length === 1 ? "" : "s"}</>
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
            Retry
          </Button>
        </Card>
      ) : row ? (
        <div className="space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1 rounded-lg border border-gray-200 p-1">
              <ModeButton
                active={mode === "preview"}
                onClick={() => setMode("preview")}
                icon={<LayoutGrid className="h-4 w-4" />}
                label="Preview"
              />
              <ModeButton
                active={mode === "json"}
                onClick={() => setMode("json")}
                icon={<Code2 className="h-4 w-4" />}
                label="JSON"
              />
            </div>
            <div className="flex items-center gap-2">
              <Button variant="secondary" size="sm" onClick={onExportJson}>
                <Download className="h-4 w-4 mr-1" />
                Export
              </Button>
              <Button
                variant="secondary"
                size="sm"
                onClick={() => void onDelete()}
                loading={deleting}
                disabled={deleting}
              >
                Delete
              </Button>
            </div>
          </div>

          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          {mode === "preview" ? (
            <TemplateDraftPreview template={row.template} />
          ) : (
            <Card>
              <p className="text-xs text-gray-500 mb-2">
                Edit the template JSON directly. Save validates against
                the schema; an invalid shape surfaces inline.
              </p>
              <textarea
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
                  Save changes
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={saving}
                  onClick={() =>
                    setDraftJson(JSON.stringify(row.template, null, 2))
                  }
                >
                  Reset to saved
                </Button>
              </div>
            </Card>
          )}
        </div>
      ) : null}
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
        "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-colors " +
        (active
          ? "bg-navy-50 text-navy-800"
          : "text-gray-500 hover:bg-gray-50 hover:text-gray-700")
      }
      aria-pressed={active}
    >
      {icon}
      {label}
    </button>
  );
}
