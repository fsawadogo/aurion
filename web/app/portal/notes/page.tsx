"use client";

import { ArrowRight, Download, Search } from "lucide-react";
import { humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import { bulkExport, listMySessions } from "@/lib/portal-api";
import { formatRelative, humanSpecialty } from "@/lib/session-format";
import type { Session, SessionState } from "@/types";

/**
 * /portal/notes — the clinician's sessions inbox.
 *
 * Mirrors iOS SessionsInboxView filter chips (All / Pending / Completed
 * / Exported) plus a text search and a date-range select. Pagination
 * is client-side at pilot scale; the backend returns the full list of
 * the caller's own sessions.
 *
 * Clicking a row navigates to /portal/notes/[id] for the review pane.
 */

type StatusFilter = "all" | "pending" | "completed" | "exported";
type DateFilter = "all" | "today" | "7d" | "30d";

const PENDING_STATES: ReadonlySet<SessionState> = new Set<SessionState>([
  "AWAITING_REVIEW",
  "PROCESSING_STAGE1",
  "PROCESSING_STAGE2",
  "RECORDING",
  "PAUSED",
]);

export default function PortalSessionsInboxPage() {
  const t = useTranslations("NotesList");
  const tFilters = useTranslations("NotesList.filters");
  const tSelection = useTranslations("NotesList.selection");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [dateFilter, setDateFilter] = useState<DateFilter>("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listMySessions();
      // Backend returns newest-first already; if it ever stops we'd
      // see the order swap here — sort defensively.
      list.sort((a, b) => b.created_at.localeCompare(a.created_at));
      setSessions(list);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const filtered = useMemo(
    () => filterSessions(sessions, statusFilter, dateFilter, search),
    [sessions, statusFilter, dateFilter, search],
  );

  const counts = useMemo(() => countByStatus(sessions), [sessions]);
  const exportable = useMemo(
    () =>
      filtered.filter(
        (s) => s.state === "REVIEW_COMPLETE" || s.state === "EXPORTED",
      ),
    [filtered],
  );
  const selectableIds = useMemo(
    () => new Set(exportable.map((s) => s.id)),
    [exportable],
  );

  function toggleSelected(id: string) {
    const next = new Set(selected);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    setSelected(next);
  }

  function selectAllExportable() {
    setSelected(new Set(selectableIds));
  }

  function clearSelected() {
    setSelected(new Set());
  }

  async function onBulkExport() {
    const ids = Array.from(selected).filter((id) => selectableIds.has(id));
    if (ids.length === 0) return;
    setExporting(true);
    setExportError(null);
    try {
      const blob = await bulkExport(ids);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aurion_bulk_${ids.length}_notes.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      clearSelected();
    } catch (e) {
      setExportError(humanizeError(e, t("exportError")));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="aurion-page-padded aurion-container">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            {t("refresh")}
          </Button>
        }
      />

      <Card>
        <div className="flex flex-wrap gap-3 items-center mb-4">
          <StatusChip
            label={tFilters("all", { count: counts.all })}
            active={statusFilter === "all"}
            onClick={() => setStatusFilter("all")}
          />
          <StatusChip
            label={tFilters("pending", { count: counts.pending })}
            active={statusFilter === "pending"}
            onClick={() => setStatusFilter("pending")}
          />
          <StatusChip
            label={tFilters("completed", { count: counts.completed })}
            active={statusFilter === "completed"}
            onClick={() => setStatusFilter("completed")}
          />
          <StatusChip
            label={tFilters("exported", { count: counts.exported })}
            active={statusFilter === "exported"}
            onClick={() => setStatusFilter("exported")}
          />
          <div className="ml-auto flex items-center gap-3">
            <select
              className="form-select w-36"
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value as DateFilter)}
              aria-label={tFilters("dateRangeAria")}
            >
              <option value="all">{tFilters("dateAll")}</option>
              <option value="today">{tFilters("dateToday")}</option>
              <option value="7d">{tFilters("date7d")}</option>
              <option value="30d">{tFilters("date30d")}</option>
            </select>
            <div className="relative">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
              <input
                className="form-input pl-8 w-56"
                placeholder={tFilters("searchPlaceholder")}
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                aria-label={tFilters("searchAria")}
              />
            </div>
          </div>
        </div>

        {exportable.length > 0 && (
          <div className="mb-3 flex flex-wrap items-center gap-2 rounded-md border border-gray-100 bg-gray-50/50 px-3 py-2 text-xs text-gray-600">
            <span>{tSelection("count", { count: selected.size })}</span>
            {selected.size > 0 ? (
              <button
                type="button"
                onClick={clearSelected}
                className="underline hover:text-navy-700"
              >
                {tSelection("clear")}
              </button>
            ) : (
              <button
                type="button"
                onClick={selectAllExportable}
                className="underline hover:text-navy-700"
              >
                {tSelection("selectAll", { count: exportable.length })}
              </button>
            )}
            {exportError && (
              <span className="text-red-600">{exportError}</span>
            )}
            <Button
              variant="primary"
              size="sm"
              className="ml-auto"
              onClick={() => void onBulkExport()}
              disabled={selected.size === 0 || exporting}
              loading={exporting}
            >
              <Download className="h-4 w-4 mr-1" />
              {selected.size > 0
                ? tSelection("exportN", { count: selected.size })
                : tSelection("exportSelected")}
            </Button>
          </div>
        )}

        {loading ? (
          <LoadingSkeleton lines={6} />
        ) : error ? (
          <div className="text-sm text-red-600">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="text-center text-sm text-gray-500 py-8">
            {t("noMatches")}
          </div>
        ) : (
          <ul className="divide-y divide-gray-100">
            {filtered.map((s) => {
              const isSelectable = selectableIds.has(s.id);
              const isChecked = selected.has(s.id);
              return (
              <li key={s.id} className="flex items-center gap-2">
                {isSelectable && (
                  <input
                    type="checkbox"
                    className="ml-1 h-4 w-4 rounded border-gray-300 text-gold-500 focus:ring-gold-400"
                    checked={isChecked}
                    onChange={() => toggleSelected(s.id)}
                    aria-label={tSelection("selectAria", { id: s.id.slice(0, 8) })}
                  />
                )}
                {!isSelectable && <span className="w-6 shrink-0" aria-hidden />}
                {/* Plain anchor for dynamic-route nav — see
                    web/lib/use-route-segment.ts header. Next `<Link>`
                    under `output: "export"` + `dynamicParams = false`
                    collapses the URL bar to `/portal/notes`. */}
                <a
                  href={`/portal/notes/${s.id}`}
                  className="flex flex-1 items-center gap-4 py-3 px-1 hover:bg-gray-50 transition-colors rounded-md"
                >
                  <div className="flex-1 min-w-0">
                    <p className="font-medium text-navy-800 truncate flex items-center gap-2">
                      {humanSpecialty(s.specialty)}
                      {s.external_reference_id && (
                        <span className="inline-flex items-center rounded-full bg-gold-50 px-2 py-0.5 text-[10px] font-mono font-semibold text-navy-700 ring-1 ring-inset ring-gold-600/20">
                          {s.external_reference_id}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {formatRelative(s.created_at, { withYear: true })} ·{" "}
                      <span className="font-mono text-[10px]">
                        {s.id.slice(0, 8)}
                      </span>
                    </p>
                  </div>
                  <div className="hidden sm:block w-32 shrink-0">
                    <StateBadge state={s.state} />
                  </div>
                  <ArrowRight className="h-4 w-4 text-gray-300 shrink-0" />
                </a>
              </li>
              );
            })}
          </ul>
        )}
      </Card>
    </div>
  );
}

/* ── Sub-components ────────────────────────────────────────────────────── */

function StatusChip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "rounded-full border px-3.5 py-1.5 text-[13px] font-medium transition-all duration-short ease-aurion " +
        (active
          ? "border-gold-400 bg-gold-50 text-navy-900 shadow-card"
          : "border-hairline text-navy-600 hover:border-navy-200 hover:bg-canvas")
      }
    >
      {label}
    </button>
  );
}

function StateBadge({ state }: { state: SessionState }) {
  const t = useTranslations("NotesList.stateBadge");
  if (state === "RECORDING") return <Badge variant="info" dot>{t("recording")}</Badge>;
  if (state === "PAUSED") return <Badge variant="info" dot>{t("paused")}</Badge>;
  if (
    state === "PROCESSING_STAGE1" ||
    state === "PROCESSING_STAGE2"
  )
    return <Badge variant="info" dot>{t("processing")}</Badge>;
  if (state === "AWAITING_REVIEW")
    return <Badge variant="warning" dot>{t("review")}</Badge>;
  if (state === "REVIEW_COMPLETE")
    return <Badge variant="success" dot>{t("approved")}</Badge>;
  if (state === "EXPORTED") return <Badge variant="success">{t("exported")}</Badge>;
  if (state === "PURGED") return <Badge variant="neutral">{t("purged")}</Badge>;
  if (state === "FAILED") return <Badge variant="error" dot>{t("failed")}</Badge>;
  return <Badge variant="neutral">{state}</Badge>;
}

/* ── Filtering + formatting ────────────────────────────────────────────── */

function countByStatus(list: Session[]) {
  const counts = { all: list.length, pending: 0, completed: 0, exported: 0 };
  for (const s of list) {
    if (PENDING_STATES.has(s.state)) counts.pending += 1;
    else if (s.state === "REVIEW_COMPLETE") counts.completed += 1;
    else if (s.state === "EXPORTED" || s.state === "PURGED") counts.exported += 1;
  }
  return counts;
}

function filterSessions(
  list: Session[],
  status: StatusFilter,
  date: DateFilter,
  search: string,
): Session[] {
  const cutoff = dateCutoff(date);
  const q = search.trim().toLowerCase();
  return list.filter((s) => {
    if (status === "pending" && !PENDING_STATES.has(s.state)) return false;
    if (status === "completed" && s.state !== "REVIEW_COMPLETE") return false;
    if (
      status === "exported" &&
      s.state !== "EXPORTED" &&
      s.state !== "PURGED"
    )
      return false;
    if (cutoff && new Date(s.created_at).getTime() < cutoff) return false;
    if (q) {
      // Searches across specialty / state / session-id prefix AND the
      // patient identifier when set. The identifier is the most useful
      // search axis day-to-day ("find Mrs Jones's last visit") so it
      // gets equal-billing with the other fields rather than a separate
      // search box.
      const haystack = [
        s.specialty,
        s.state,
        s.id,
        s.external_reference_id ?? "",
      ]
        .join(" ")
        .toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });
}

function dateCutoff(d: DateFilter): number | null {
  const now = Date.now();
  switch (d) {
    case "today":
      return new Date(new Date().setHours(0, 0, 0, 0)).getTime();
    case "7d":
      return now - 7 * 24 * 60 * 60 * 1000;
    case "30d":
      return now - 30 * 24 * 60 * 60 * 1000;
    case "all":
    default:
      return null;
  }
}
