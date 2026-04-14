"use client";

import { useEffect, useState, useCallback } from "react";
import Header from "@/components/Header";
import { FunnelIcon } from "@heroicons/react/24/outline";
import { getSessions } from "@/lib/api";
import type { Session, SessionFilters, PaginatedResponse } from "@/types";

const stateColors: Record<string, string> = {
  IDLE: "bg-gray-100 text-gray-600",
  CONSENT_PENDING: "bg-yellow-100 text-yellow-700",
  RECORDING: "bg-red-100 text-red-700",
  PAUSED: "bg-orange-100 text-orange-700",
  PROCESSING_STAGE1: "bg-blue-100 text-blue-700",
  AWAITING_REVIEW: "bg-purple-100 text-purple-700",
  PROCESSING_STAGE2: "bg-indigo-100 text-indigo-700",
  REVIEW_COMPLETE: "bg-emerald-100 text-emerald-700",
  EXPORTED: "bg-teal-100 text-teal-700",
  PURGED: "bg-gray-100 text-gray-500",
  FAILED: "bg-red-100 text-red-700",
};

export default function SessionsPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [specialty, setSpecialty] = useState("");
  const [clinician, setClinician] = useState("");

  const pageSize = 50;

  const fetchSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const filters: SessionFilters = { page, page_size: pageSize };
      if (specialty) filters.specialty = specialty;
      if (clinician) filters.clinician_id = clinician;

      const data: PaginatedResponse<Session> = await getSessions(filters);
      setSessions(data.items);
      setTotal(data.total);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load sessions",
      );
    } finally {
      setLoading(false);
    }
  }, [page, specialty, clinician]);

  useEffect(() => {
    fetchSessions();
  }, [fetchSessions]);

  const totalPages = Math.ceil(total / pageSize);

  return (
    <>
      <Header
        title="Session Completeness"
        subtitle="Per-session completeness scores and section coverage"
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
            <label className="mb-1 block text-xs text-gray-500">
              Clinician
            </label>
            <input
              type="text"
              placeholder="All clinicians"
              value={clinician}
              onChange={(e) => {
                setClinician(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-500">
              Specialty
            </label>
            <select
              value={specialty}
              onChange={(e) => {
                setSpecialty(e.target.value);
                setPage(1);
              }}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
            >
              <option value="">All specialties</option>
              <option value="orthopedic_surgery">Orthopedic Surgery</option>
              <option value="plastic_surgery">Plastic Surgery</option>
              <option value="musculoskeletal">Musculoskeletal</option>
              <option value="emergency_medicine">Emergency Medicine</option>
              <option value="general">General</option>
            </select>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Session
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Clinician
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Specialty
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    State
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Sections
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Completeness
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Provider
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Created
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr>
                    <td
                      colSpan={8}
                      className="px-4 py-8 text-center text-sm text-gray-400"
                    >
                      Loading sessions...
                    </td>
                  </tr>
                ) : sessions.length === 0 ? (
                  <tr>
                    <td
                      colSpan={8}
                      className="px-4 py-8 text-center text-sm text-gray-400"
                    >
                      No sessions found.
                    </td>
                  </tr>
                ) : (
                  sessions.map((s) => {
                    const pct = Math.round(s.completeness_score * 100);
                    const belowTarget = pct < 90;
                    return (
                      <tr key={s.id} className="hover:bg-gray-50">
                        <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-500">
                          {s.id.length > 12
                            ? `${s.id.slice(0, 8)}...`
                            : s.id}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                          {s.clinician_name}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                          {s.specialty.replace(/_/g, " ")}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <span
                            className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                              stateColors[s.state] ??
                              "bg-gray-100 text-gray-600"
                            }`}
                          >
                            {s.state}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                          {s.sections_populated} / {s.sections_required}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <span
                            className={`font-semibold ${
                              belowTarget ? "text-red-600" : "text-green-600"
                            }`}
                          >
                            {pct}%
                          </span>
                          {belowTarget && (
                            <span className="ml-2 rounded bg-red-50 px-1.5 py-0.5 text-xs text-red-500">
                              Below target
                            </span>
                          )}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                          {s.provider_used || "--"}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-400">
                          {new Date(s.created_at).toLocaleDateString()}
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="mt-4 flex items-center justify-between">
            <p className="text-sm text-gray-500">
              Page {page} of {totalPages} ({total} sessions)
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
