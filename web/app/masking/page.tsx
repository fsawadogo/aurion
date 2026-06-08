"use client";

import { CheckCircle2, ShieldCheck, XCircle } from "lucide-react";
import { useEffect, useState } from "react";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getMaskingReport, humanizeError } from "@/lib/api";
import {
  abbreviateName,
  nameInitials,
  shortSessionId,
} from "@/lib/session-format";
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
        setError(humanizeError(err, "Failed to load masking report"));
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
              <p className="mt-1 text-2xl font-bold tabular-nums text-navy-700">
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
              <p className="mt-1 text-2xl font-bold tabular-nums text-emerald-600">
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
              <p
                className={`mt-1 text-2xl font-bold tabular-nums ${
                  displayReport.fail_count > 0
                    ? "text-red-600"
                    : "text-gray-300"
                }`}
              >
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
                  <th className="px-4 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-gray-400">Attempts</th>
                  <th className="px-4 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-gray-400">Masked</th>
                  <th className="px-4 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-gray-400">Failed</th>
                  <th className="px-4 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-gray-400">Skipped</th>
                  <th className="px-4 py-3 text-right text-[11px] font-semibold uppercase tracking-wider text-gray-400">Uploaded</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {loading ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-6">
                      <LoadingSkeleton lines={4} />
                    </td>
                  </tr>
                ) : displayReport.sessions.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-4 py-14 text-center">
                      <div className="mx-auto flex max-w-sm flex-col items-center gap-2">
                        <span className="flex h-10 w-10 items-center justify-center rounded-full bg-navy-50 ring-1 ring-inset ring-navy-100">
                          <ShieldCheck className="h-5 w-5 text-navy-300" />
                        </span>
                        <p className="text-sm font-medium text-gray-500">
                          No masking data available yet
                        </p>
                        <p className="text-xs text-gray-400">
                          Events appear here once sessions process video frames.
                        </p>
                      </div>
                    </td>
                  </tr>
                ) : (
                  displayReport.sessions.map((s) => (
                    <tr
                      key={s.session_id}
                      // Hard navigation for dynamic `/audit/[sessionId]` —
                      // Next router collapses the URL under static export.
                      // See web/lib/use-route-segment.ts.
                      onClick={() =>
                        window.location.assign(
                          `/audit/${encodeURIComponent(s.session_id)}`,
                        )
                      }
                      className="cursor-pointer transition-colors hover:bg-gray-50/80"
                    >
                      <td className="whitespace-nowrap px-4 py-3">
                        <code
                          title={s.session_id}
                          className="rounded-md bg-gray-100 px-2 py-0.5 font-mono text-xs tracking-tight text-gray-500"
                        >
                          {shortSessionId(s.session_id)}
                        </code>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <div
                          className="flex items-center gap-2.5"
                          title={s.clinician_name || undefined}
                        >
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-navy-50 text-[10px] font-semibold text-navy-700 ring-1 ring-inset ring-navy-100">
                            {nameInitials(s.clinician_name || "—")}
                          </span>
                          <span className="text-sm font-medium text-navy-800">
                            {s.clinician_name
                              ? abbreviateName(s.clinician_name)
                              : "—"}
                          </span>
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                        {s.date}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right text-gray-600 font-medium tabular-nums">
                        {s.total_frames}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right text-emerald-600 font-medium tabular-nums">
                        {s.masked_frames}
                      </td>
                      <td className={`whitespace-nowrap px-4 py-3 text-sm text-right font-medium tabular-nums ${s.failed_frames > 0 ? "text-red-600" : "text-gray-300"}`}>
                        {s.failed_frames}
                      </td>
                      <td className={`whitespace-nowrap px-4 py-3 text-sm text-right font-medium tabular-nums ${s.skipped_frames > 0 ? "text-amber-600" : "text-gray-300"}`}>
                        {s.skipped_frames}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-right text-gray-600 font-medium tabular-nums">
                        {s.uploaded_frames}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {s.pass ? (
                          <Badge variant="success" dot>
                            <span className="inline-flex items-center gap-1">
                              <CheckCircle2 className="h-3 w-3" />
                              Pass
                            </span>
                          </Badge>
                        ) : (
                          <Badge variant="error" dot>
                            <span className="inline-flex items-center gap-1">
                              <XCircle className="h-3 w-3" />
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
