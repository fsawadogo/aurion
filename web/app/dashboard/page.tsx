"use client";

import Header from "@/components/Header";

const metrics = [
  {
    name: "Template Section Completeness",
    value: "--",
    target: "90%",
    description: "Percentage of required sections populated per session",
  },
  {
    name: "Citation Traceability Rate",
    value: "--",
    target: "95%",
    description: "Percentage of note claims with valid source ID",
  },
  {
    name: "Physician Edit Rate",
    value: "--",
    target: "N/A",
    description: "Average diff between v1 draft and final approved note",
  },
  {
    name: "Conflict Rate",
    value: "--",
    target: "Low",
    description: "Percentage of frame citations classified as CONFLICTS",
  },
  {
    name: "Low Confidence Frame Rate",
    value: "--",
    target: "Low",
    description: "Percentage of frames discarded due to low confidence",
  },
  {
    name: "Stage 1 Latency",
    value: "--",
    target: "< 30s",
    description: "Time from record stop to Stage 1 draft delivery",
  },
  {
    name: "Stage 2 Latency",
    value: "--",
    target: "< 5 min",
    description: "Time from Stage 1 approval to full note delivery",
  },
  {
    name: "Session Completeness",
    value: "--",
    target: "100%",
    description: "Percentage of sessions with all 8 metrics logged",
  },
];

export default function DashboardPage() {
  return (
    <>
      <Header
        title="Pilot Metrics Dashboard"
        subtitle="Aggregate pilot performance across all sessions and clinicians"
      />

      <div className="p-6 lg:p-8">
        {/* Summary row */}
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard label="Total Sessions" value="0" />
          <SummaryCard label="Active Clinicians" value="0" />
          <SummaryCard label="Avg Completeness" value="--" />
          <SummaryCard label="Masking Pass Rate" value="--" />
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
              <div className="mt-2 rounded-full bg-gold-50 px-2.5 py-0.5 text-xs font-medium text-gold-700 inline-block">
                Target: {m.target}
              </div>
            </div>
          ))}
        </div>

        {/* Placeholder chart area */}
        <div className="mt-8 rounded-xl border border-dashed border-gray-300 bg-gray-50 p-12 text-center">
          <p className="text-sm text-gray-400">
            Time-series charts and specialty breakdown will appear here once
            pilot data is available.
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
