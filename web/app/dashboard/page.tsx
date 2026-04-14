"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header";
import { getMetrics, getSessions } from "@/lib/api";
import type { PilotMetric, Session, PaginatedResponse } from "@/types";

export default function DashboardPage() {
  const [metricsData, setMetricsData] = useState<PilotMetric[]>([]);
  const [sessionsData, setSessionsData] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const [metricsRes, sessionsRes] = await Promise.all([
          getMetrics({ page: 1, page_size: 200 }),
          getSessions({ page: 1, page_size: 200 }),
        ]);
        setMetricsData(metricsRes.items);
        setSessionsData(sessionsRes.items);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load dashboard data",
        );
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  // Compute aggregates
  const totalSessions = sessionsData.length;
  const uniqueClinicians = new Set(sessionsData.map((s) => s.clinician_id)).size;

  function avg(values: (number | null | undefined)[]): string {
    const valid = values.filter((v): v is number => v != null);
    if (valid.length === 0) return "--";
    return `${Math.round((valid.reduce((a, b) => a + b, 0) / valid.length) * 100) / 100}`;
  }

  function avgPct(values: (number | null | undefined)[]): string {
    const valid = values.filter((v): v is number => v != null);
    if (valid.length === 0) return "--";
    const mean = valid.reduce((a, b) => a + b, 0) / valid.length;
    return `${Math.round(mean * 100)}%`;
  }

  function avgMs(values: (number | null | undefined)[]): string {
    const valid = values.filter((v): v is number => v != null);
    if (valid.length === 0) return "--";
    const mean = valid.reduce((a, b) => a + b, 0) / valid.length;
    if (mean < 1000) return `${Math.round(mean)}ms`;
    return `${(mean / 1000).toFixed(1)}s`;
  }

  const avgCompleteness = avgPct(
    metricsData.map((m) => m.template_section_completeness),
  );
  const avgCitation = avgPct(
    metricsData.map((m) => m.citation_traceability_rate),
  );
  const avgEditRate = avgPct(
    metricsData.map((m) => m.physician_edit_rate),
  );
  const avgConflict = avgPct(metricsData.map((m) => m.conflict_rate));
  const avgLowConf = avgPct(
    metricsData.map((m) => m.low_confidence_frame_rate),
  );
  const avgStage1 = avgMs(metricsData.map((m) => m.stage1_latency_ms));
  const avgStage2 = avgMs(metricsData.map((m) => m.stage2_latency_ms));
  const sessionCompletenessRate =
    metricsData.length > 0
      ? `${Math.round(
          (metricsData.filter((m) => m.session_completeness).length /
            metricsData.length) *
            100,
        )}%`
      : "--";

  const metrics = [
    {
      name: "Template Section Completeness",
      value: avgCompleteness,
      target: "90%",
      description: "Percentage of required sections populated per session",
    },
    {
      name: "Citation Traceability Rate",
      value: avgCitation,
      target: "95%",
      description: "Percentage of note claims with valid source ID",
    },
    {
      name: "Physician Edit Rate",
      value: avgEditRate,
      target: "N/A",
      description: "Average diff between v1 draft and final approved note",
    },
    {
      name: "Conflict Rate",
      value: avgConflict,
      target: "Low",
      description: "Percentage of frame citations classified as CONFLICTS",
    },
    {
      name: "Low Confidence Frame Rate",
      value: avgLowConf,
      target: "Low",
      description: "Percentage of frames discarded due to low confidence",
    },
    {
      name: "Stage 1 Latency",
      value: avgStage1,
      target: "< 30s",
      description: "Time from record stop to Stage 1 draft delivery",
    },
    {
      name: "Stage 2 Latency",
      value: avgStage2,
      target: "< 5 min",
      description: "Time from Stage 1 approval to full note delivery",
    },
    {
      name: "Session Completeness",
      value: sessionCompletenessRate,
      target: "100%",
      description: "Percentage of sessions with all 8 metrics logged",
    },
  ];

  return (
    <>
      <Header
        title="Pilot Metrics Dashboard"
        subtitle="Aggregate pilot performance across all sessions and clinicians"
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

        {/* Summary row */}
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard
            label="Total Sessions"
            value={loading ? "--" : String(totalSessions)}
          />
          <SummaryCard
            label="Active Clinicians"
            value={loading ? "--" : String(uniqueClinicians)}
          />
          <SummaryCard label="Avg Completeness" value={avgCompleteness} />
          <SummaryCard label="Avg Citation Rate" value={avgCitation} />
        </div>

        {/* Metric cards */}
        <h2 className="mb-4 text-base font-semibold text-navy">
          Behaviour Metrics
        </h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {metrics.map((m) => (
            <div
              key={m.name}
              className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
            >
              <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
                {m.name}
              </p>
              <p className="mt-2 text-2xl font-bold text-navy">{m.value}</p>
              <div className="mt-3 flex items-center justify-between">
                <span className="text-xs text-gray-500">{m.description}</span>
              </div>
              <div className="mt-2 inline-block rounded-full bg-gold-50 px-2.5 py-0.5 text-xs font-medium text-gold-700">
                Target: {m.target}
              </div>
            </div>
          ))}
        </div>

        {/* Placeholder chart area */}
        <div className="mt-8 rounded-xl border border-dashed border-gray-300 bg-gray-50 p-12 text-center">
          <p className="text-sm text-gray-400">
            {loading
              ? "Loading pilot data..."
              : metricsData.length === 0
                ? "No pilot data available yet. Time-series charts and specialty breakdown will appear here once sessions are processed."
                : `Showing aggregates from ${metricsData.length} sessions. Time-series charts coming in next update.`}
          </p>
        </div>
      </div>
    </>
  );
}

function SummaryCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-navy p-5 text-white shadow">
      <p className="text-xs font-medium uppercase tracking-wider text-gray-300">
        {label}
      </p>
      <p className="mt-1 text-2xl font-bold text-gold">{value}</p>
    </div>
  );
}
