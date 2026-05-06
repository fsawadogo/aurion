"use client";

import { useEffect, useState, useCallback } from "react";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  FunnelIcon,
  ArrowDownTrayIcon,
  MagnifyingGlassIcon,
} from "@heroicons/react/24/outline";
import { getAuditLog, exportAuditCsv } from "@/lib/api";
import type { AuditEvent, AuditFilters, PaginatedResponse } from "@/types";

function eventBadgeVariant(
  eventType: string,
): "success" | "warning" | "error" | "info" | "neutral" {
  if (eventType.includes("consent") || eventType.includes("masking_confirmed"))
    return "info";
  if (eventType.includes("recording") || eventType.includes("paused") || eventType.includes("purged"))
    return "neutral";
  if (eventType.includes("masking_failed") || eventType === "session_failed")
    return "error";
  if (eventType.includes("config"))
    return "warning";
  if (eventType.includes("delivered") || eventType.includes("exported") || eventType.includes("complete"))
    return "success";
  return "info";
}

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  // Filters
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [eventType, setEventType] = useState("");
  const [clinician, setClinician] = useState("");
  const [sessionSearch, setSessionSearch] = useState("");

  const pageSize = 50;

  const fetchEvents = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const filters: AuditFilters = {
        page,
        page_size: pageSize,
      };
      if (dateFrom) filters.date_from = dateFrom;
      if (dateTo) filters.date_to = dateTo;
      if (eventType) filters.event_type = eventType;
      if (clinician) filters.clinician_id = clinician;
      if (sessionSearch) filters.session_id = sessionSearch;

      const data: PaginatedResponse<AuditEvent> = await getAuditLog(filters);
      setEvents(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }, [page, dateFrom, dateTo, eventType, clinician, sessionSearch]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  async function handleExportCsv() {
    setExporting(true);
    try {
      const filters: AuditFilters = {};
      if (dateFrom) filters.date_from = dateFrom;
      if (dateTo) filters.date_to = dateTo;
      if (eventType) filters.event_type = eventType;
      if (clinician) filters.clinician_id = clinician;
      if (sessionSearch) filters.session_id = sessionSearch;

      const blob = await exportAuditCsv(filters);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "aurion_audit_log.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "CSV export failed");
    } finally {
      setExporting(false);
    }
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <>
      <Header
        title="Audit Log"
        subtitle="Immutable session lifecycle events"
        actions={
          <Button
            variant="secondary"
            size="sm"
            loading={exporting}
            onClick={handleExportCsv}
          >
            <ArrowDownTrayIcon className="h-4 w-4" />
            Export CSV
          </Button>
        }
      />

      <div className="p-6 lg:p-8">
        {error && (
          <div className="mb-6 flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-600/10">
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 text-xs font-medium">
              Dismiss
            </button>
          </div>
        )}

        {/* Filters */}
        <Card className="mb-6">
          <div className="flex flex-wrap items-end gap-4">
            <div className="flex items-center gap-1.5 text-xs font-medium text-gray-400">
              <FunnelIcon className="h-3.5 w-3.5" />
              <span className="uppercase tracking-wider">Filters</span>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-500">Session ID</label>
              <div className="relative">
                <MagnifyingGlassIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  placeholder="Search session..."
                  value={sessionSearch}
                  onChange={(e) => { setSessionSearch(e.target.value); setPage(1); }}
                  className="rounded-lg border border-gray-200 bg-gray-50/50 py-2 pl-9 pr-3 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
                />
              </div>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-500">From</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
                className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-500">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
                className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-500">Clinician</label>
              <input
                type="text"
                placeholder="All clinicians"
                value={clinician}
                onChange={(e) => { setClinician(e.target.value); setPage(1); }}
                className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-500">Event Type</label>
              <select
                value={eventType}
                onChange={(e) => { setEventType(e.target.value); setPage(1); }}
                className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              >
                <option value="">All events</option>
                <option value="session_created">session_created</option>
                <option value="consent_confirmed">consent_confirmed</option>
                <option value="recording_started">recording_started</option>
                <option value="session_paused">session_paused</option>
                <option value="stage1_started">stage1_started</option>
                <option value="stage1_delivered">stage1_delivered</option>
                <option value="stage2_started">stage2_started</option>
                <option value="full_note_delivered">full_note_delivered</option>
                <option value="note_exported">note_exported</option>
                <option value="session_purged">session_purged</option>
                <option value="masking_confirmed">masking_confirmed</option>
                <option value="config_changed">config_changed</option>
              </select>
            </div>
          </div>
        </Card>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-gray-200/60 bg-white shadow-card">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80">
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    Timestamp
                  </th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    Session
                  </th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    Event
                  </th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                    Details
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {loading ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-6">
                      <LoadingSkeleton lines={5} />
                    </td>
                  </tr>
                ) : events.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-12 text-center">
                      <p className="text-sm text-gray-400">No audit events found matching the current filters.</p>
                    </td>
                  </tr>
                ) : (
                  events.map((evt, i) => (
                    <tr key={`${evt.session_id}-${evt.event_timestamp}-${i}`} className="transition-colors hover:bg-gray-50/80">
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                        {new Date(evt.event_timestamp).toLocaleString()}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                          {evt.session_id.length > 12
                            ? `${evt.session_id.slice(0, 8)}...`
                            : evt.session_id}
                        </code>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Badge variant={eventBadgeVariant(evt.event_type)}>
                          {evt.event_type}
                        </Badge>
                      </td>
                      <td className="max-w-xs truncate px-4 py-3 text-sm text-gray-400">
                        {evt.details && Object.keys(evt.details).length > 0
                          ? JSON.stringify(evt.details).slice(0, 80)
                          : "--"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-between">
            <p className="text-xs text-gray-400">
              Page {page} of {totalPages} &middot; {total} events
            </p>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
