"use client";

import { useEffect, useState, useCallback } from "react";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { FunnelIcon } from "@heroicons/react/24/outline";
import { getSessions } from "@/lib/api";
import type { Session, SessionFilters, PaginatedResponse } from "@/types";

const stateBadgeVariant: Record<string, "success" | "warning" | "error" | "info" | "neutral"> = {
  IDLE: "neutral",
  CONSENT_PENDING: "warning",
  RECORDING: "error",
  PAUSED: "warning",
  PROCESSING_STAGE1: "info",
  AWAITING_REVIEW: "info",
  PROCESSING_STAGE2: "info",
  REVIEW_COMPLETE: "success",
  EXPORTED: "success",
  PURGED: "neutral",
  FAILED: "error",
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
        subtitle="Per-session scores and section coverage"
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
              <label className="mb-1 block text-[11px] font-medium text-gray-500">Specialty</label>
              <select
                value={specialty}
                onChange={(e) => { setSpecialty(e.target.value); setPage(1); }}
                className="rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
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
        </Card>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-gray-200/60 bg-white shadow-card">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80">
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Session</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Clinician</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Specialty</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">State</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Sections</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Completeness</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Provider</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-6">
                      <LoadingSkeleton lines={5} />
                    </td>
                  </tr>
                ) : sessions.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center">
                      <p className="text-sm text-gray-400">No sessions found.</p>
                    </td>
                  </tr>
                ) : (
                  sessions.map((s) => {
                    const pct = Math.round(s.completeness_score * 100);
                    const belowTarget = pct < 90;
                    return (
                      <tr key={s.id} className="transition-colors hover:bg-gray-50/80">
                        <td className="whitespace-nowrap px-4 py-3">
                          <code className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                            {s.id.length > 12 ? `${s.id.slice(0, 8)}...` : s.id}
                          </code>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                          {s.clinician_name}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm capitalize text-gray-500">
                          {s.specialty.replace(/_/g, " ")}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <Badge variant={stateBadgeVariant[s.state] ?? "neutral"} dot>
                            {s.state.replace(/_/g, " ")}
                          </Badge>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                          <span className="font-medium">{s.sections_populated}</span>
                          <span className="text-gray-400"> / {s.sections_required}</span>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          <div className="flex items-center gap-3">
                            <div className="h-1.5 w-20 overflow-hidden rounded-full bg-gray-100">
                              <div
                                className={`h-full rounded-full transition-all duration-500 ${
                                  belowTarget
                                    ? "bg-red-400"
                                    : "bg-gradient-to-r from-gold-400 to-gold-500"
                                }`}
                                style={{ width: `${pct}%` }}
                              />
                            </div>
                            <span
                              className={`text-xs font-semibold ${
                                belowTarget ? "text-red-600" : "text-emerald-600"
                              }`}
                            >
                              {pct}%
                            </span>
                          </div>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                          {s.provider_used || "--"}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-400">
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
            <p className="text-xs text-gray-400">
              Page {page} of {totalPages} &middot; {total} sessions
            </p>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
                Previous
              </Button>
              <Button variant="secondary" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
                Next
              </Button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
