"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header";
import {
  CheckCircleIcon,
  XCircleIcon,
} from "@heroicons/react/24/solid";
import { getMaskingReport } from "@/lib/api";
import type { MaskingReport } from "@/types";

export default function MaskingPage() {
  const [report, setReport] = useState<MaskingReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  useEffect(() => {
    async function fetchReport() {
      setLoading(true);
      setError(null);
      try {
        const filters: { date_from?: string; date_to?: string } = {};
        if (dateFrom) filters.date_from = dateFrom;
        if (dateTo) filters.date_to = dateTo;
        const data = await getMaskingReport(filters);
        setReport(data);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load masking report",
        );
      } finally {
        setLoading(false);
      }
    }
    fetchReport();
  }, [dateFrom, dateTo]);

  const displayReport = report ?? {
    total_sessions: 0,
    pass_count: 0,
    fail_count: 0,
    pass_rate: 100,
    sessions: [],
  };

  return (
    <>
      <Header
        title="PHI Masking Validation"
        subtitle="Per-session masking pass/fail status -- 100% target"
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

        {/* Date filters */}
        <div className="mb-6 flex flex-wrap items-end gap-4 rounded-xl border border-gray-200 bg-white p-4 shadow-sm">
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
        </div>

        {/* Summary cards */}
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
              Total Sessions
            </p>
            <p className="mt-1 text-2xl font-bold text-navy">
              {loading ? "--" : displayReport.total_sessions}
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
              Passed
            </p>
            <p className="mt-1 text-2xl font-bold text-green-600">
              {loading ? "--" : displayReport.pass_count}
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
              Failed
            </p>
            <p className="mt-1 text-2xl font-bold text-red-600">
              {loading ? "--" : displayReport.fail_count}
            </p>
          </div>
          <div
            className={`rounded-xl border p-5 shadow-sm ${
              displayReport.pass_rate === 100
                ? "border-green-200 bg-green-50"
                : "border-red-200 bg-red-50"
            }`}
          >
            <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
              Pass Rate
            </p>
            <p
              className={`mt-1 text-2xl font-bold ${
                displayReport.pass_rate === 100
                  ? "text-green-600"
                  : "text-red-600"
              }`}
            >
              {loading ? "--" : `${displayReport.pass_rate}%`}
            </p>
          </div>
        </div>

        {/* Per-session table */}
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
                    Date
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Total Frames
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Masked
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {loading ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-8 text-center text-sm text-gray-400"
                    >
                      Loading masking report...
                    </td>
                  </tr>
                ) : displayReport.sessions.length === 0 ? (
                  <tr>
                    <td
                      colSpan={6}
                      className="px-4 py-8 text-center text-sm text-gray-400"
                    >
                      No masking data available yet. Masking events will appear
                      here once sessions process video frames.
                    </td>
                  </tr>
                ) : (
                  displayReport.sessions.map((s) => (
                    <tr key={s.session_id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-500">
                        {s.session_id.length > 12
                          ? `${s.session_id.slice(0, 8)}...`
                          : s.session_id}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                        {s.clinician_name}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                        {s.date}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                        {s.total_frames}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                        {s.masked_frames}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {s.pass ? (
                          <span className="inline-flex items-center gap-1 text-green-600">
                            <CheckCircleIcon className="h-4 w-4" />
                            Pass
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-red-600">
                            <XCircleIcon className="h-4 w-4" />
                            Fail
                          </span>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}
