"use client";

import { LayoutGrid, MessagesSquare, Plus, SquarePen, Trash2, Upload } from "lucide-react";
import { getMe, humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import Modal from "@/components/ui/Modal";
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
  // Current user id for ownership gating. The list can include shared
  // templates owned by others (is_shared) — those aren't deletable by the
  // caller (the backend DELETE is owner-scoped → 404), so the Delete control
  // is shown only for rows the caller owns. Null until resolved (gate stays
  // closed). Latent today since nothing is ever is_shared, correct once
  // community sharing ships.
  const [meId, setMeId] = useState<string | null>(null);
  // True once getMe() has settled (success OR failure). On failure meId stays
  // null and we fall back to SHOWING the delete control — the backend DELETE
  // is owner-scoped (404) so it's safe to defer enforcement to the server
  // rather than lock the real owner out of their own template.
  const [meResolved, setMeResolved] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<CustomTemplate | null>(null);

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
    void getMe()
      .then((u) => setMeId(u.user_id))
      .catch(() => {})
      .finally(() => setMeResolved(true));
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

  async function confirmDelete() {
    const tpl = pendingDelete;
    if (!tpl) return;
    setDeletingId(tpl.id);
    try {
      await deleteMyCustomTemplate(tpl.id);
      setList(list.filter((x) => x.id !== tpl.id));
      setPendingDelete(null);
    } catch (e) {
      setError(humanizeError(e, t("deleteError")));
      // Close the modal on error too, so the page-level error banner isn't
      // obscured behind the still-open overlay (matches the detail page).
      setPendingDelete(null);
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
                // .docx is parsed server-side via python-docx; the rest are
                // decoded as UTF-8 text.
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
        <div className="mb-4 rounded-aurion-md bg-red-50 border border-red-200 px-4 py-3 text-aurion-callout text-red-700">
          {error}
        </div>
      )}

      <Card>
        {loading ? (
          <LoadingSkeleton lines={6} />
        ) : list.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-gold-50 text-gold-600">
              <MessagesSquare className="h-6 w-6" />
            </div>
            <p className="aurion-callout font-medium text-navy-700">
              {t("emptyTitle")}
            </p>
            <Link href="/portal/templates/new">
              <Button variant="primary" size="sm" className="mt-4">
                {t("startBuilding")}
              </Button>
            </Link>
          </div>
        ) : (
          <ul className="divide-y divide-hairline">
            {list.map((tpl) => (
              <li
                key={tpl.id}
                className="group flex items-center gap-3 py-3 -mx-2 px-2 rounded-aurion-md hover:bg-canvas/40 transition-colors duration-short"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-aurion-md bg-navy-50 text-navy-600 ring-1 ring-inset ring-navy-100">
                  <LayoutGrid className="h-4 w-4" />
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-aurion-callout font-medium text-navy-800 truncate">
                    {tpl.display_name}
                  </p>
                  <p className="mt-0.5 text-aurion-caption text-navy-500">
                    <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] tracking-tight text-gray-500">
                      {tpl.key}
                    </code>{" "}
                    ·{" "}
                    {t("metadata", {
                      version: tpl.version,
                      sections: t("sectionCount", { count: tpl.template.sections.length }),
                      updated: formatRelative(tpl.updated_at),
                    })}
                  </p>
                </div>
                {tpl.is_shared && (
                  <Badge variant="info" className="shrink-0">
                    {t("sharedBadge")}
                  </Badge>
                )}
                <div className="flex items-center gap-1 shrink-0">
                  {/* Plain anchor for dynamic `/portal/templates/[id]` —
                      Next `<Link>` collapses the URL under static export.
                      See web/lib/use-route-segment.ts. */}
                  <a
                    href={`/portal/templates/${tpl.id}`}
                    className="inline-flex items-center gap-1 rounded-aurion-xs px-2 py-1 text-aurion-caption font-medium text-navy-600 hover:bg-canvas hover:text-navy-800 transition-colors duration-short"
                  >
                    <SquarePen className="h-4 w-4" />
                    {t("open")}
                  </a>
                  {/* Delete only for owned rows — a shared row's DELETE is
                      owner-scoped server-side (404). On getMe failure (meId
                      null after resolution) fall back to showing it. */}
                  {meResolved && (meId === null || tpl.owner_id === meId) && (
                    <button
                      type="button"
                      onClick={() => setPendingDelete(tpl)}
                      className="inline-flex items-center justify-center rounded-aurion-xs p-1.5 text-navy-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 transition-colors duration-short"
                      disabled={deletingId === tpl.id}
                      aria-label={t("deleteAria", { name: tpl.display_name })}
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Modal
        isOpen={pendingDelete !== null}
        onClose={() => {
          if (!deletingId) setPendingDelete(null);
        }}
        title={t("deleteTitle")}
        footer={
          <>
            <Button
              variant="secondary"
              size="sm"
              disabled={!!deletingId}
              onClick={() => setPendingDelete(null)}
            >
              {t("deleteCancel")}
            </Button>
            <Button
              variant="destructive"
              size="sm"
              loading={!!deletingId}
              disabled={!!deletingId}
              onClick={() => void confirmDelete()}
            >
              {t("deleteConfirmButton")}
            </Button>
          </>
        }
      >
        <p className="text-aurion-callout text-navy-600">
          {pendingDelete
            ? t("deleteConfirm", { name: pendingDelete.display_name })
            : ""}
        </p>
      </Modal>
    </div>
  );
}
