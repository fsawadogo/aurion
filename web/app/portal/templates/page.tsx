"use client";

import { Copy, LayoutGrid, MessagesSquare, Plus, SquarePen, Trash2, Upload } from "lucide-react";
import { getMe, humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import Modal from "@/components/ui/Modal";
import PageHeader from "@/components/portal/PageHeader";
import {
  deleteMyCustomTemplate,
  duplicateMyCustomTemplate,
  listMyCustomTemplates,
  uploadTemplateDocument,
} from "@/lib/portal-api";
import { formatRelative } from "@/lib/session-format";
import type { CustomTemplate } from "@/types";

/**
 * /portal/templates — the clinician's templates, split across two tabs:
 *
 *   • My Templates — the clinician's own (is_shared=false): editable + deletable.
 *   • Library      — shared org templates (is_shared=true): read-only here, each
 *                    with a "Save to My Templates" button that forks a personal
 *                    copy (POST /me/custom-templates/{id}/duplicate).
 *
 * `listMyCustomTemplates` returns the union of the caller's own private rows and
 * shared rows; the tabs are a disjoint split on `is_shared`. Only the active
 * tab's list is mounted, so the clinician's own templates are never buried under
 * a growing org Library (and vice-versa). A count badge on each tab signals
 * what's in the other tab without a click.
 *
 * Built-in specialty templates aren't shown here — they live in the backend's
 * file-based loader (admin "System Templates"); folding them into this Library
 * is a follow-up (#579).
 */
type TemplatesTab = "mine" | "library";

export default function PortalTemplatesPage() {
  const t = useTranslations("TemplatesList");
  const router = useRouter();
  const [list, setList] = useState<CustomTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [duplicatingId, setDuplicatingId] = useState<string | null>(null);
  const [tab, setTab] = useState<TemplatesTab>("mine");
  // Current user id for ownership gating of the delete control (a row the caller
  // doesn't own would 404 server-side). Null until resolved; on getMe failure we
  // fall back to showing it and let the owner-scoped backend enforce.
  const [meId, setMeId] = useState<string | null>(null);
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
      router.push(`/portal/templates/new?session=${session.id}`);
    } catch (e) {
      setError(humanizeError(e, t("uploadError")));
    } finally {
      setUploading(false);
    }
  }

  async function onDuplicate(tpl: CustomTemplate) {
    setDuplicatingId(tpl.id);
    setError(null);
    try {
      await duplicateMyCustomTemplate(tpl.id);
      // The fork is owned (is_shared=false) + newest, so it lands at the top of
      // the My Templates tab after the reload; that tab's count badge ticks up.
      await load();
    } catch (e) {
      setError(humanizeError(e, t("duplicateError")));
    } finally {
      setDuplicatingId(null);
    }
  }

  async function confirmDelete() {
    const tpl = pendingDelete;
    if (!tpl) return;
    setDeletingId(tpl.id);
    try {
      await deleteMyCustomTemplate(tpl.id);
      // Functional updater: a Library fork's load() refresh can land mid-delete,
      // so filter the latest list, not the one captured when the modal opened.
      setList((prev) => prev.filter((x) => x.id !== tpl.id));
      setPendingDelete(null);
    } catch (e) {
      setError(humanizeError(e, t("deleteError")));
      setPendingDelete(null);
    } finally {
      setDeletingId(null);
    }
  }

  const mine = list.filter((tpl) => !tpl.is_shared);
  const library = list.filter((tpl) => tpl.is_shared);

  const rowClass =
    "group flex items-center gap-3 py-3 -mx-2 px-2 rounded-aurion-md hover:bg-canvas/40 transition-colors duration-short";

  const rowMeta = (tpl: CustomTemplate) => (
    <>
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
    </>
  );

  const tabs = [
    { id: "mine" as const, label: t("myTemplatesHeading"), count: mine.length },
    { id: "library" as const, label: t("libraryHeading"), count: library.length },
  ];

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
        <div className="mb-4 rounded-aurion-md bg-red-50 border border-red-200 px-4 py-3 text-aurion-callout text-red-700">
          {error}
        </div>
      )}

      {/* Tabs: My Templates ↔ Library — a disjoint split on is_shared. */}
      <div
        className="mb-5 inline-flex rounded-aurion-md border border-hairline bg-white p-0.5"
        role="tablist"
        aria-label={t("title")}
      >
        {tabs.map(({ id, label, count }) => {
          const active = tab === id;
          return (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={active}
              onClick={() => setTab(id)}
              data-testid={`templates-tab-${id}`}
              className={
                "flex items-center gap-2 rounded-aurion-sm px-3 py-1.5 text-aurion-callout font-medium transition-colors " +
                (active
                  ? "bg-navy-50 text-navy-800"
                  : "text-navy-400 hover:text-navy-700")
              }
            >
              {label}
              {!loading && (
                <span
                  className={
                    "rounded-full px-1.5 text-[11px] tabular-nums " +
                    (active
                      ? "bg-navy-100 text-navy-700"
                      : "bg-gray-100 text-navy-400")
                  }
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}
      </div>

      <Card>
        {loading ? (
          <LoadingSkeleton lines={6} />
        ) : tab === "mine" ? (
          <div role="tabpanel" aria-label={t("myTemplatesHeading")}>
            {mine.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-10 text-center">
                <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-gold-50 text-gold-600">
                  <MessagesSquare className="h-6 w-6" />
                </div>
                <p className="aurion-callout font-medium text-navy-700">
                  {t("myTemplatesEmpty")}
                </p>
                <div className="mt-4 flex items-center gap-4">
                  <Link href="/portal/templates/new">
                    <Button variant="primary" size="sm">
                      {t("startBuilding")}
                    </Button>
                  </Link>
                  {library.length > 0 && (
                    <button
                      type="button"
                      onClick={() => setTab("library")}
                      className="text-aurion-callout font-medium text-navy-500 hover:text-navy-800 transition-colors duration-short"
                    >
                      {t("browseLibrary")}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <ul className="divide-y divide-hairline">
                {mine.map((tpl) => (
                  <li key={tpl.id} className={rowClass}>
                    {rowMeta(tpl)}
                    <div className="flex items-center gap-1 shrink-0">
                      {/* Plain anchor for dynamic `/portal/templates/[id]` —
                          Next `<Link>` collapses the URL under static export. */}
                      <a
                        href={`/portal/templates/${tpl.id}`}
                        className="inline-flex items-center gap-1 rounded-aurion-xs px-2 py-1 text-aurion-caption font-medium text-navy-600 hover:bg-canvas hover:text-navy-800 transition-colors duration-short"
                      >
                        <SquarePen className="h-4 w-4" />
                        {t("open")}
                      </a>
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
          </div>
        ) : (
          <div role="tabpanel" aria-label={t("libraryHeading")}>
            {library.length === 0 ? (
              <p className="py-8 text-center text-aurion-caption text-navy-500">
                {t("libraryEmpty")}
              </p>
            ) : (
              <ul className="divide-y divide-hairline">
                {library.map((tpl) => (
                  <li key={tpl.id} className={rowClass}>
                    {rowMeta(tpl)}
                    <Button
                      variant="secondary"
                      size="sm"
                      className="shrink-0"
                      loading={duplicatingId === tpl.id}
                      disabled={!!duplicatingId}
                      onClick={() => void onDuplicate(tpl)}
                    >
                      <Copy className="h-4 w-4 mr-1" />
                      {t("saveToMine")}
                    </Button>
                  </li>
                ))}
              </ul>
            )}
          </div>
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
