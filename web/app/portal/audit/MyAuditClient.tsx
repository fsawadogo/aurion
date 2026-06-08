"use client";

import { Download, ExternalLink, Filter, Search, X } from "lucide-react";
import { humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import { getMyAuditLog } from "@/lib/portal-api";
import { shortSessionId } from "@/lib/session-format";
import type { AuditEvent, AuditFilters, PaginatedResponse } from "@/types";

/**
 * /portal/audit — clinician's self-audit log (#162).
 *
 * Paginated table over `GET /api/v1/me/audit` (scoped server-side to
 * the caller's own actor_id). Filter bar mirrors the admin /audit
 * page's affordances but drops the clinician filter — the row set is
 * already self-scoped.
 *
 * CSV export covers the currently-visible page (NOT the full history)
 * — mirrors the admin /audit page's scope and keeps the export bounded
 * and predictable. Bulk full-history export is a follow-up.
 *
 * Event display strings resolve through the shared `AuditEvents.*`
 * namespace so this page and the dashboard `ActivityFeed` render the
 * same human label for any event type.
 */

const PAGE_SIZE = 50;

/* ── Event type → label key + badge tint ───────────────────────────── */

/** Catalog of audit event types this clinician can generate. Drives
 *  the filter <select>, the badge labels, and the CSV export header
 *  semantics. Keep alphabetised by group to make additions easy.
 *
 *  Source of truth for the backend enum: `app/core/audit_events.py`
 *  (AuditEventType). The clinician self-audit surface only ever sees
 *  events with their own actor_id, so admin-only event types
 *  (`config_changed`, `feature_flag_set`, etc.) are filtered out by
 *  the backend before reaching this page.
 */
type BadgeTint = "info" | "neutral" | "warning" | "success" | "error";

interface EventMeta {
  /** Key under `AuditEvents.*`. */
  labelKey: string;
  badge: BadgeTint;
}

const EVENT_META: Record<string, EventMeta> = {
  // Lifecycle
  session_created: { labelKey: "sessionCreated", badge: "info" },
  consent_confirmed: { labelKey: "consentConfirmed", badge: "info" },
  recording_started: { labelKey: "recordingStarted", badge: "neutral" },
  session_paused: { labelKey: "sessionPaused", badge: "neutral" },
  session_purged: { labelKey: "sessionPurged", badge: "neutral" },
  session_discarded: { labelKey: "sessionDiscarded", badge: "neutral" },
  // Stage 1
  stage1_started: { labelKey: "stage1Started", badge: "info" },
  stage1_delivered: { labelKey: "stage1Delivered", badge: "info" },
  stage1_approved: { labelKey: "stage1Approved", badge: "success" },
  stage1_failed: { labelKey: "stage1Failed", badge: "error" },
  // Stage 2
  stage2_started: { labelKey: "stage2Started", badge: "info" },
  stage2_complete: { labelKey: "stage2Complete", badge: "success" },
  stage2_failed: { labelKey: "stage2Failed", badge: "error" },
  full_note_delivered: { labelKey: "fullNoteDelivered", badge: "success" },
  // Conflicts + masking
  conflict_resolved: { labelKey: "conflictResolved", badge: "info" },
  masking_confirmed: { labelKey: "maskingConfirmed", badge: "info" },
  // Export
  note_exported: { labelKey: "noteExported", badge: "success" },
  bulk_note_export: { labelKey: "bulkNoteExport", badge: "success" },
  // EMR
  emr_write_back_sent: { labelKey: "emrSent", badge: "success" },
  emr_write_back_failed: { labelKey: "emrFailed", badge: "error" },
  // Patient summary / orders / coding / macros / live preview
  patient_summary_generated: { labelKey: "patientSummaryGenerated", badge: "info" },
  patient_summary_edited: { labelKey: "patientSummaryEdited", badge: "info" },
  orders_extracted: { labelKey: "ordersExtracted", badge: "info" },
  order_confirmed: { labelKey: "orderConfirmed", badge: "success" },
  order_edited: { labelKey: "orderEdited", badge: "info" },
  order_cancelled: { labelKey: "orderCancelled", badge: "neutral" },
  coding_suggestions_extracted: { labelKey: "codingSuggestionsExtracted", badge: "info" },
  coding_suggestion_confirmed: { labelKey: "codingSuggestionConfirmed", badge: "success" },
  coding_suggestion_rejected: { labelKey: "codingSuggestionRejected", badge: "neutral" },
  coding_suggestion_edited: { labelKey: "codingSuggestionEdited", badge: "info" },
  macro_created: { labelKey: "macroCreated", badge: "info" },
  macro_updated: { labelKey: "macroUpdated", badge: "info" },
  macro_deleted: { labelKey: "macroDeleted", badge: "neutral" },
  external_reference_id_set: { labelKey: "externalReferenceIdSet", badge: "info" },
  live_preview_generated: { labelKey: "livePreviewGenerated", badge: "info" },
};

/** Sorted list of filterable event types — drives the <select> options. */
const FILTERABLE_EVENT_TYPES: readonly string[] =
  Object.keys(EVENT_META).sort();

/* ── Component ─────────────────────────────────────────────────────── */

export default function MyAuditClient() {
  const t = useTranslations("Audit");
  const tFilters = useTranslations("Audit.filters");
  const tTable = useTranslations("Audit.table");
  const tPagination = useTranslations("Audit.pagination");
  const tEvents = useTranslations("AuditEvents");

  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Filters — controlled inputs.
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [eventType, setEventType] = useState("");
  const [sessionId, setSessionId] = useState("");

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const filters: AuditFilters = {
        page,
        page_size: PAGE_SIZE,
      };
      if (dateFrom) filters.date_from = dateFrom;
      if (dateTo) filters.date_to = dateTo;
      if (eventType) filters.event_type = eventType;
      if (sessionId.trim()) filters.session_id = sessionId.trim();

      const data = (await getMyAuditLog(filters)) as PaginatedResponse<AuditEvent>;
      setEvents(data.items ?? []);
      setTotal(data.total ?? 0);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [page, dateFrom, dateTo, eventType, sessionId, t]);

  useEffect(() => {
    void fetchEvents();
  }, [fetchEvents]);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(total / PAGE_SIZE)),
    [total],
  );

  const anyFilterActive =
    dateFrom !== "" || dateTo !== "" || eventType !== "" || sessionId !== "";

  function clearFilters() {
    setDateFrom("");
    setDateTo("");
    setEventType("");
    setSessionId("");
    setPage(1);
  }

  /**
   * Build a CSV string from the visible-page rows and trigger a browser
   * download. We intentionally stringify `details` rather than flattening
   * it — the audit table is heterogeneous and a different connector or
   * EMR system can add novel keys we don't want to silently drop.
   *
   * No PHI in the export: backend's `ALLOWED_AUDIT_KWARGS`
   * (`app/core/audit_events.py`) constrains what lands in `details` to
   * non-PHI fields (session-id-prefixes, latencies, counters, etc.).
   */
  function exportCsv() {
    setExporting(true);
    try {
      const body = buildAuditCsv(events);
      // UTF-8 BOM so Excel opens accented characters cleanly.
      const blob = new Blob(["﻿" + body], {
        type: "text/csv;charset=utf-8",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const today = new Date();
      const yyyymmdd =
        today.getFullYear().toString() +
        String(today.getMonth() + 1).padStart(2, "0") +
        String(today.getDate()).padStart(2, "0");
      a.download = `aurion_my_audit_${yyyymmdd}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
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
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => void fetchEvents()}
            >
              {t("refresh")}
            </Button>
            <Button
              variant="primary"
              size="sm"
              loading={exporting}
              disabled={events.length === 0}
              onClick={exportCsv}
            >
              <Download className="h-4 w-4 mr-1" />
              {exporting ? t("exporting") : t("exportCsv")}
            </Button>
          </div>
        }
      />

      {error && (
        <div className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700">
          {error}
        </div>
      )}

      {/* ── Filter bar ──────────────────────────────────────────────── */}
      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex items-center gap-1.5 text-xs font-medium text-aurion-tertiary">
            <Filter className="h-3.5 w-3.5" />
            <span className="uppercase tracking-wider">
              {tFilters("label")}
            </span>
          </div>

          <FilterField label={tFilters("sessionId")}>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder={tFilters("sessionIdPlaceholder")}
                value={sessionId}
                onChange={(e) => {
                  setSessionId(e.target.value);
                  setPage(1);
                }}
                className="rounded-lg border border-gray-200 bg-gray-50/50 py-2 pl-9 pr-3 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              />
            </div>
          </FilterField>

          <FilterField label={tFilters("dateFrom")}>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => {
                setDateFrom(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
            />
          </FilterField>

          <FilterField label={tFilters("dateTo")}>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => {
                setDateTo(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
            />
          </FilterField>

          <FilterField label={tFilters("eventType")}>
            <select
              value={eventType}
              onChange={(e) => {
                setEventType(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
            >
              <option value="">{tFilters("allEvents")}</option>
              {FILTERABLE_EVENT_TYPES.map((evt) => (
                <option key={evt} value={evt}>
                  {tEvents(EVENT_META[evt].labelKey)}
                </option>
              ))}
            </select>
          </FilterField>

          {anyFilterActive && (
            <button
              type="button"
              onClick={clearFilters}
              aria-label={tFilters("clearAria")}
              className="inline-flex items-center gap-1 self-end rounded-full border border-hairline px-3 py-1.5 text-xs font-medium text-aurion-secondary transition-colors hover:bg-canvas hover:text-aurion-primary"
            >
              <X className="h-3 w-3" />
              {tFilters("clear")}
            </button>
          )}
        </div>
      </Card>

      {/* ── Table ───────────────────────────────────────────────────── */}
      <div className="overflow-hidden rounded-aurion-lg border border-hairline bg-surface shadow-card">
        <div className="overflow-x-auto">
          <table className="min-w-full">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/80">
                <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {tTable("timestamp")}
                </th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {tTable("session")}
                </th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {tTable("event")}
                </th>
                <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {tTable("details")}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {loading ? (
                <tr>
                  <td colSpan={4} className="px-4 py-6">
                    <LoadingSkeleton lines={6} />
                  </td>
                </tr>
              ) : events.length === 0 ? (
                <tr>
                  <td colSpan={4} className="px-4 py-12 text-center">
                    <p className="text-sm font-medium text-aurion-primary">
                      {t("noMatches")}
                    </p>
                    <p className="mt-1 text-xs text-aurion-tertiary">
                      {t("noMatchesHint")}
                    </p>
                  </td>
                </tr>
              ) : (
                events.map((event) => (
                  <AuditRow
                    key={rowKey(event)}
                    event={event}
                    openSessionLabel={tTable("openSession")}
                    noDetailsLabel={t("noDetails")}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Pagination ──────────────────────────────────────────────── */}
      {totalPages > 1 && (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs text-aurion-tertiary">
            {tPagination("summary", { page, totalPages, total })}
          </p>
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              disabled={page <= 1 || loading}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              {tPagination("previous")}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={page >= totalPages || loading}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              {tPagination("next")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Sub-components ────────────────────────────────────────────────── */

function FilterField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium text-gray-500">
        {label}
      </label>
      {children}
    </div>
  );
}

function AuditRow({
  event,
  openSessionLabel,
  noDetailsLabel,
}: {
  event: AuditEvent;
  openSessionLabel: string;
  noDetailsLabel: string;
}) {
  const tEvents = useTranslations("AuditEvents");
  const meta = EVENT_META[event.event_type] ?? {
    labelKey: "generic",
    badge: "neutral" as const,
  };
  // Local clinician time for the timestamp (not UTC) so review feels
  // natural. Falls back to the raw ISO string if parsing fails.
  const timestamp = formatLocalTimestamp(event.event_timestamp);
  const sessionIdShort = shortSessionId(event.session_id);
  const detailsPreview = formatDetailsPreview(event.details, noDetailsLabel);

  return (
    <tr className="transition-colors hover:bg-gray-50/80">
      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
        {timestamp}
      </td>
      <td className="whitespace-nowrap px-4 py-3">
        {/* Plain anchor for dynamic-route nav — see
            web/lib/use-route-segment.ts. Next `<Link>` under
            static export collapses dynamic `[id]` segments. */}
        <a
          href={`/portal/notes/${event.session_id}`}
          title={event.session_id}
          aria-label={`${openSessionLabel} ${sessionIdShort}`}
          className="inline-flex items-center gap-1 rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs text-navy-700 transition-colors hover:bg-gold-50 hover:text-navy-900"
        >
          {sessionIdShort}
          <ExternalLink className="h-3 w-3 opacity-60" />
        </a>
      </td>
      <td className="whitespace-nowrap px-4 py-3 text-sm">
        <Badge variant={meta.badge}>{tEvents(meta.labelKey)}</Badge>
      </td>
      <td className="max-w-xs truncate px-4 py-3 text-xs text-aurion-tertiary">
        {detailsPreview}
      </td>
    </tr>
  );
}

/* ── Helpers ───────────────────────────────────────────────────────── */

/** Build a stable React key for an event row. */
function rowKey(event: AuditEvent): string {
  if (event.event_id) return event.event_id;
  return `${event.session_id}:${event.event_timestamp}:${event.event_type}`;
}

/** Render a server ISO-8601 timestamp in clinician-local format.
 *  Falls back to the raw string if parsing fails (defensive — backend
 *  always returns ISO timestamps but old rows from dev seeds can carry
 *  legacy shapes). */
function formatLocalTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString();
}

/** One-line truncated preview of the JSON details blob. Returns a
 *  placeholder dash when no details are present. */
function formatDetailsPreview(
  details: Record<string, unknown> | undefined,
  empty: string,
): string {
  if (!details || Object.keys(details).length === 0) return empty;
  const json = JSON.stringify(details);
  return json.length > 80 ? json.slice(0, 80) + "…" : json;
}

/** RFC 4180-style CSV cell escape: wrap in quotes when the value
 *  contains a comma, newline, or double-quote; double internal quotes. */
function csvCell(value: string): string {
  if (value == null) return "";
  const needsQuote = /[",\n\r]/.test(value);
  const escaped = value.replace(/"/g, '""');
  return needsQuote ? `"${escaped}"` : escaped;
}

/** Build the CSV body (without the UTF-8 BOM) from the visible rows.
 *  Exported separately from the click handler so tests can assert on
 *  the exact byte sequence without going through Blob/URL APIs that
 *  jsdom doesn't fully implement. */
export function buildAuditCsv(events: AuditEvent[]): string {
  const headers = [
    "timestamp_utc",
    "event_type",
    "session_id",
    "details_json",
  ];
  const lines = [headers.join(",")];
  for (const ev of events) {
    const details =
      ev.details && Object.keys(ev.details).length > 0
        ? JSON.stringify(ev.details)
        : "";
    lines.push(
      [
        csvCell(ev.event_timestamp),
        csvCell(ev.event_type),
        csvCell(ev.session_id),
        csvCell(details),
      ].join(","),
    );
  }
  return lines.join("\n");
}
