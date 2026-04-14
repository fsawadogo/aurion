"use client";

import { useEffect, useState, useCallback } from "react";
import Header from "@/components/Header";
import {
  FunnelIcon,
  ArrowDownTrayIcon,
} from "@heroicons/react/24/outline";
import { getAuditLog, exportAuditCsv } from "@/lib/api";
import type { AuditEvent, AuditFilters, PaginatedResponse } from "@/types";

const eventTypeColors: Record<string, string> = {
  session_created: "bg-blue-100 text-blue-700",
  consent_confirmed: "bg-green-100 text-green-700",
  recording_started: "bg-indigo-100 text-indigo-700",
  session_paused: "bg-yellow-100 text-yellow-700",
  stage1_started: "bg-purple-100 text-purple-700",
  stage1_delivered: "bg-purple-100 text-purple-700",
  stage2_started: "bg-violet-100 text-violet-700",
  full_note_delivered: "bg-emerald-100 text-emerald-700",
  note_exported: "bg-teal-100 text-teal-700",
  session_purged: "bg-gray-100 text-gray-700",
  user_created: "bg-blue-100 text-blue-700",
  user_updated: "bg-amber-100 text-amber-700",
  config_changed: "bg-orange-100 text-orange-700",
  masking_confirmed: "bg-green-100 text-green-700",
  masking_failed: "bg-red-100 text-red-700",
  eval_score_submitted: "bg-purple-100 text-purple-700",
};

export default function AuditPage() {
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [eventType, setEventType] = useState("");
  const [clinician, setClinician] = useState("");

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

      const data: PaginatedResponse<AuditEvent> = await getAuditLog(filters);
      setEvents(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit log");
    } finally {
      setLoading(false);
    }
  }, [page, dateFrom, dateTo, eventType, clinician]);

  useEffect(() => {
    fetchEvents();
  }, [fetchEvents]);

  async function handleExportCsv() {
    try {
      const filters: AuditFilters = {};
      if (dateFrom) filters.date_from = dateFrom;
      if (dateTo) filters.date_to = dateTo;
      if (eventType) filters.event_type = eventType;
      if (clinician) filters.clinician_id = clinician;

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
    }
  }

  const totalPages = Math.ceil(total / pageSize);

  return (
    <>
      <Header
        title="Audit Log"
        subtitle="Immutable session lifecycle events"
      />

      <div className="p-6 lg:p-8">
        {error && (
          <div className="mb-4 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
            <button
              onClick={() => setError(null)}
              className="ml-2 text-red-500 underline"
            >
              dismiss
            </button>
          </div>
        )}

        {/* Filters */}
        <div className="mb-6 flex flex-wrap items-end gap-4 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
          <div className="flex items-center gap-2 text-sm font-medium text-gray-500">
            <FunnelIcon className="h-4 w-4" />
            Filters
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">From</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => { setDateFrom(e.target.value); setPage(1); }}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">To</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => { setDateTo(e.target.value); setPage(1); }}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">
              Clinician
            </label>
            <input
              type="text"
              placeholder="All clinicians"
              value={clinician}
              onChange={(e) => { setClinician(e.target.value); setPage(1); }}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">
              Event Type
            </label>
            <select
              value={eventType}
              onChange={(e) => { setEventType(e.target.value); setPage(1); }}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
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
          <button
            onClick={handleExportCsv}
            className="flex items-center gap-2 rounded-lg bg-gold px-4 py-2 text-sm font-medium text-navy transition-colors hover:bg-gold-600"
          >
            <ArrowDownTrayIcon className="h-4 w-4" />
            Export CSV
          </button>
        </div>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Timestamp
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Session
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Event
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Details
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">
                      Loading audit events...
                    </td>
                  </tr>
                ) : events.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">
                      No audit events found matching the current filters.
                    </td>
                  </tr>
                ) : (
                  events.map((evt, i) => (
                    <tr key={`${evt.session_id}-${evt.event_timestamp}-${i}`} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                        {new Date(evt.event_timestamp).toLocaleString()}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-500">
                        {evt.session_id.length > 12
                          ? `${evt.session_id.slice(0, 8)}...`
                          : evt.session_id}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <span
                          className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                            eventTypeColors[evt.event_type] ??
                            "bg-gray-100 text-gray-700"
                          }`}
                        >
                          {evt.event_type}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-400">
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
            <p className="text-sm text-gray-500">
              Page {page} of {totalPages} ({total} events)
            </p>
            <div className="flex gap-2">
              <button
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40"
              >
                Previous
              </button>
              <button
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
                className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50 disabled:opacity-40"
              >
                Next
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
