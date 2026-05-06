"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  CheckCircleIcon,
  XCircleIcon,
} from "@heroicons/react/24/solid";
import { getMaskingReport } from "@/lib/api";
import type { MaskingReport } from "@/types";

function ProgressRing({ value, size = 100 }: { value: number; size?: number }) {
  const strokeWidth = 7;
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (value / 100) * circumference;
  const color = value === 100 ? "#10b981" : "#ef4444";

  return (
    <div className="relative inline-flex items-center justify-center">
      <svg width={size} height={size} className="-rotate-90">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="#f3f4f6"
          strokeWidth={strokeWidth}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={offset}
          className="transition-all duration-700 ease-out"
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="text-xl font-bold" style={{ color }}>{value}%</span>
        <span className="text-[10px] font-medium text-gray-400">Pass Rate</span>
      </div>
    </div>
  );
}

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
        subtitle="100% pass rate target"
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

        {/* Date filters */}
        <Card className="mb-6">
          <div className="flex flex-wrap items-end gap-4">
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-500">From</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-gray-500">To</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              />
            </div>
          </div>
        </Card>

        {/* Summary cards */}
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 stagger-children">
          <Card hoverable>
            <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
              Total Sessions
            </p>
            {loading ? (
              <LoadingSkeleton lines={1} className="mt-2" />
            ) : (
              <p className="mt-1 text-2xl font-bold text-navy-700">
                {displayReport.total_sessions}
              </p>
            )}
          </Card>
          <Card hoverable>
            <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
              Passed
            </p>
            {loading ? (
              <LoadingSkeleton lines={1} className="mt-2" />
            ) : (
              <p className="mt-1 text-2xl font-bold text-emerald-600">
                {displayReport.pass_count}
              </p>
            )}
          </Card>
          <Card hoverable>
            <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
              Failed
            </p>
            {loading ? (
              <LoadingSkeleton lines={1} className="mt-2" />
            ) : (
              <p className="mt-1 text-2xl font-bold text-red-600">
                {displayReport.fail_count}
              </p>
            )}
          </Card>
          <Card hoverable>
            <div className="flex items-center justify-center py-1">
              {loading ? (
                <LoadingSkeleton lines={2} />
              ) : (
                <ProgressRing value={displayReport.pass_rate} />
              )}
            </div>
          </Card>
        </div>

        {/* Per-session table */}
        <div className="overflow-hidden rounded-xl border border-gray-200/60 bg-white shadow-card">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80">
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Session</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Clinician</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Date</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Total Frames</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Masked</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {loading ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-6">
                      <LoadingSkeleton lines={4} />
                    </td>
                  </tr>
                ) : displayReport.sessions.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center">
                      <p className="text-sm text-gray-400">
                        No masking data available yet. Events appear here once sessions process video frames.
                      </p>
                    </td>
                  </tr>
                ) : (
                  displayReport.sessions.map((s) => (
                    <tr key={s.session_id} className="transition-colors hover:bg-gray-50/80">
                      <td className="whitespace-nowrap px-4 py-3">
                        <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                          {s.session_id.length > 12
                            ? `${s.session_id.slice(0, 8)}...`
                            : s.session_id}
                        </code>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                        {s.clinician_name}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                        {s.date}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600 font-medium">
                        {s.total_frames}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600 font-medium">
                        {s.masked_frames}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {s.pass ? (
                          <Badge variant="success" dot>
                            <span className="inline-flex items-center gap-1">
                              <CheckCircleIcon className="h-3 w-3" />
                              Pass
                            </span>
                          </Badge>
                        ) : (
                          <Badge variant="error" dot>
                            <span className="inline-flex items-center gap-1">
                              <XCircleIcon className="h-3 w-3" />
                              Fail
                            </span>
                          </Badge>
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
