"use client";

import { useState } from "react";
import Header from "@/components/Header";
import {
  FunnelIcon,
  ArrowDownTrayIcon,
} from "@heroicons/react/24/outline";

const placeholderEvents = [
  {
    session_id: "sess_001",
    event_timestamp: "2026-04-10T09:12:34Z",
    event_type: "session_created",
    actor_id: "dr_perry",
    actor_role: "CLINICIAN",
    details: {},
  },
  {
    session_id: "sess_001",
    event_timestamp: "2026-04-10T09:12:40Z",
    event_type: "consent_confirmed",
    actor_id: "dr_perry",
    actor_role: "CLINICIAN",
    details: {},
  },
  {
    session_id: "sess_001",
    event_timestamp: "2026-04-10T09:12:45Z",
    event_type: "recording_started",
    actor_id: "dr_perry",
    actor_role: "CLINICIAN",
    details: {},
  },
  {
    session_id: "sess_001",
    event_timestamp: "2026-04-10T09:28:10Z",
    event_type: "stage1_started",
    actor_id: "system",
    actor_role: "ADMIN",
    details: { provider: "anthropic" },
  },
  {
    session_id: "sess_001",
    event_timestamp: "2026-04-10T09:28:35Z",
    event_type: "stage1_delivered",
    actor_id: "system",
    actor_role: "ADMIN",
    details: { latency_ms: 24500 },
  },
];

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
};

export default function AuditPage() {
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [eventType, setEventType] = useState("");
  const [clinician, setClinician] = useState("");

  return (
    <>
      <Header
        title="Audit Log"
        subtitle="Immutable session lifecycle events"
      />

      <div className="p-6 lg:p-8">
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
              onChange={(e) => setDateFrom(e.target.value)}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">To</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
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
              onChange={(e) => setClinician(e.target.value)}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">
              Event Type
            </label>
            <select
              value={eventType}
              onChange={(e) => setEventType(e.target.value)}
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
            </select>
          </div>
          <button className="flex items-center gap-2 rounded-lg bg-gold px-4 py-2 text-sm font-medium text-navy transition-colors hover:bg-gold-600">
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
                    Actor
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Role
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Details
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {placeholderEvents.map((evt, i) => (
                  <tr key={i} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                      {new Date(evt.event_timestamp).toLocaleString()}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-500">
                      {evt.session_id}
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
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                      {evt.actor_id}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {evt.actor_role}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-400">
                      {Object.keys(evt.details).length > 0
                        ? JSON.stringify(evt.details)
                        : "--"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <p className="mt-4 text-center text-xs text-gray-400">
          Showing placeholder data. Connect to the FastAPI backend to display
          live audit events.
        </p>
      </div>
    </>
  );
}
