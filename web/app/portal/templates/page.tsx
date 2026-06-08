"use client";

import { MessagesSquare, Plus, SquarePen, Trash2, Upload } from "lucide-react";
import { humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import {
  deleteMyCustomTemplate,
  listMyCustomTemplates,
  uploadTemplateDocument,
} from "@/lib/portal-api";
import { formatRelative } from "@/lib/session-format";
import type { CustomTemplate } from "@/types";

/**
 * /portal/templates — list of custom + shared specialty templates.
 *
 * Two top-of-page actions: New (kicks off the conversational builder)
 * and Upload (file picker → LLM extracts the structure → resumes in
 * chat with the extracted draft).
 *
 * Built-in templates are not shown here — they live in the backend's
 * file-based loader and aren't editable per-physician. PR-F may add
 * a separate "system templates" section if it's useful for context.
 */
export default function PortalTemplatesPage() {
  const t = useTranslations("TemplatesList");
  const router = useRouter();
  const [list, setList] = useState<CustomTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const xs = await listMyCustomTemplates();
      xs.sort((a, b) => b.updated_at.localeCompare(a.updated_at));
      setList(xs);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onUpload(file: File) {
    setUploading(true);
    setError(null);
    try {
      const session = await uploadTemplateDocument(file);
      // Land directly in the conversational view of the just-created
      // authoring session — the LLM-extracted draft is pre-rendered
      // there and the physician can keep refining it.
      router.push(`/portal/templates/new?session=${session.id}`);
    } catch (e) {
      setError(humanizeError(e, t("uploadError")));
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(tpl: CustomTemplate) {
    if (!confirm(t("deleteConfirm", { name: tpl.display_name }))) return;
    setDeletingId(tpl.id);
    try {
      await deleteMyCustomTemplate(tpl.id);
      setList(list.filter((x) => x.id !== tpl.id));
    } catch (e) {
      setError(humanizeError(e, t("deleteError")));
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="aurion-page-padded aurion-container-narrow">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={
          <>
            <label className="inline-flex">
              <input
                type="file"
                accept=".txt,.json,.md,.docx"
                className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) void onUpload(f);
                  e.target.value = "";
                }}
                disabled={uploading}
              />
              <Button
                variant="secondary"
                size="sm"
                loading={uploading}
                disabled={uploading}
                onClick={(ev) => (ev.currentTarget.parentElement as HTMLLabelElement)?.click()}
              >
                <Upload className="h-4 w-4 mr-1" />
                {t("upload")}
              </Button>
            </label>
            <Link href="/portal/templates/new">
              <Button variant="primary" size="sm">
                <Plus className="h-4 w-4 mr-1" />
                {t("newTemplate")}
              </Button>
            </Link>
          </>
        }
      />

      {error && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      <Card>
        {loading ? (
          <LoadingSkeleton lines={6} />
        ) : list.length === 0 ? (
          <div className="py-8 text-center">
            <MessagesSquare className="mx-auto h-10 w-10 text-gray-300 mb-2" />
            <p className="text-sm text-gray-500">
              {t("emptyTitle")}
            </p>
            <Link href="/portal/templates/new">
              <Button variant="primary" size="sm" className="mt-3">
                {t("startBuilding")}
              </Button>
            </Link>
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {list.map((tpl) => (
              <li key={tpl.id} className="py-3 flex items-center gap-4">
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-navy-800 truncate">
                    {tpl.display_name}
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    <span className="font-mono">{tpl.key}</span> ·{" "}
                    {t("metadata", {
                      version: tpl.version,
                      sections: t("sectionCount", { count: tpl.template.sections.length }),
                      updated: formatRelative(tpl.updated_at),
                    })}
                  </p>
                </div>
                {tpl.is_shared && <Badge variant="info">{t("sharedBadge")}</Badge>}
                {/* Plain anchor for dynamic `/portal/templates/[id]` —
                    Next `<Link>` collapses the URL under static export.
                    See web/lib/use-route-segment.ts. */}
                <a
                  href={`/portal/templates/${tpl.id}`}
                  className="inline-flex items-center gap-1 text-sm text-navy-700 hover:text-navy-900"
                >
                  <SquarePen className="h-4 w-4" />
                  {t("open")}
                </a>
                <button
                  type="button"
                  onClick={() => void onDelete(tpl)}
                  className="inline-flex items-center text-gray-400 hover:text-red-600 disabled:opacity-50"
                  disabled={deletingId === tpl.id}
                  aria-label={t("deleteAria", { name: tpl.display_name })}
                >
                  <Trash2 className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
