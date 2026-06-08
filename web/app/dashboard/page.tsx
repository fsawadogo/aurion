"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getMe, getMetrics, getMetricsTimeseries, getSessions, humanizeError} from "@/lib/api";
import type {
  MetricTimeseriesBucket,
  MetricTimeseriesResponse,
  PilotMetric,
  Session,
} from "@/types";

function metricStatus(
  value: string,
  target: string,
): "success" | "warning" | "error" | "info" {
  if (value === "--") return "info";
  const num = parseFloat(value);
  if (isNaN(num)) return "info";

  if (target === "90%") return num >= 90 ? "success" : num >= 75 ? "warning" : "error";
  if (target === "95%") return num >= 95 ? "success" : num >= 85 ? "warning" : "error";
  if (target === "100%") return num >= 100 ? "success" : num >= 90 ? "warning" : "error";
  if (target === "< 30s") {
    const ms = value.endsWith("ms") ? num : value.endsWith("s") ? num * 1000 : num;
    return ms <= 30000 ? "success" : ms <= 60000 ? "warning" : "error";
  }
  if (target === "< 5 min") {
    const ms = value.endsWith("ms") ? num : value.endsWith("s") ? num * 1000 : num;
    return ms <= 300000 ? "success" : ms <= 600000 ? "warning" : "error";
  }
  if (target === "Low") return num <= 5 ? "success" : num <= 15 ? "warning" : "error";
  return "info";
}

const summaryIcons = [
  <svg key="sessions" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm.75-13a.75.75 0 00-1.5 0v5c0 .414.336.75.75.75h4a.75.75 0 000-1.5h-3.25V5z" clipRule="evenodd"/></svg>,
  <svg key="clinicians" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path d="M10 8a3 3 0 100-6 3 3 0 000 6zM3.465 14.493a1.23 1.23 0 00.41 1.412A9.957 9.957 0 0010 18c2.31 0 4.438-.784 6.131-2.1.43-.333.604-.903.408-1.41a7.002 7.002 0 00-13.074.003z"/></svg>,
  <svg key="completeness" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.857-9.809a.75.75 0 00-1.214-.882l-3.483 4.79-1.88-1.88a.75.75 0 10-1.06 1.061l2.5 2.5a.75.75 0 001.137-.089l4-5.5z" clipRule="evenodd"/></svg>,
  <svg key="citation" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor"><path fillRule="evenodd" d="M4.25 2A2.25 2.25 0 002 4.25v11.5A2.25 2.25 0 004.25 18h11.5A2.25 2.25 0 0018 15.75V4.25A2.25 2.25 0 0015.75 2H4.25zm4.03 6.28a.75.75 0 00-1.06-1.06L4.97 9.47a.75.75 0 000 1.06l2.25 2.25a.75.75 0 001.06-1.06L6.56 10l1.72-1.72zm3.44-1.06a.75.75 0 10-1.06 1.06L12.44 10l-1.72 1.72a.75.75 0 101.06 1.06l2.25-2.25a.75.75 0 000-1.06l-2.25-2.25z" clipRule="evenodd"/></svg>,
];

export default function DashboardPage() {
  const router = useRouter();
  const [metricsData, setMetricsData] = useState<PilotMetric[]>([]);
  const [sessionsData, setSessionsData] = useState<Session[]>([]);
  const [timeseries, setTimeseries] = useState<MetricTimeseriesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [authChecked, setAuthChecked] = useState(false);

  // Role guard: clinicians who land here (root redirect, bookmark, etc.)
  // get bounced to /portal/dashboard. The admin metrics endpoints are
  // ADMIN/EVAL_TEAM only, so a CLINICIAN would otherwise see a wall of
  // 403s in the network tab.
  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => {
        if (cancelled) return;
        if (me.role === "CLINICIAN") {
          router.replace("/portal/dashboard");
        } else {
          setAuthChecked(true);
        }
      })
      .catch(() => {
        // 401 already routes to /login via fetchWithAuth; treat
        // anything else as "let the page render and surface its own
        // error" rather than blocking.
        if (!cancelled) setAuthChecked(true);
      });
    return () => {
      cancelled = true;
    };
  }, [router]);

  useEffect(() => {
    if (!authChecked) return;
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const [metricsRes, sessionsRes, timeseriesRes] = await Promise.all([
          getMetrics({ page: 1, page_size: 200 }),
          getSessions({ page: 1, page_size: 200 }),
          getMetricsTimeseries(), // default window: last 14 days
        ]);
        setMetricsData(metricsRes.items);
        setSessionsData(sessionsRes.items);
        setTimeseries(timeseriesRes);
      } catch (err) {
        setError(
          humanizeError(err, "Failed to load dashboard data"),
        );
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, [authChecked]);

  const totalSessions = sessionsData.length;
  const uniqueClinicians = new Set(sessionsData.map((s) => s.clinician_id)).size;

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

  const avgCompleteness = avgPct(metricsData.map((m) => m.template_section_completeness));
  const avgCitation = avgPct(metricsData.map((m) => m.citation_traceability_rate));
  const avgEditRate = avgPct(metricsData.map((m) => m.physician_edit_rate));
  const avgConflict = avgPct(metricsData.map((m) => m.conflict_rate));
  const avgLowConf = avgPct(metricsData.map((m) => m.low_confidence_frame_rate));
  const avgStage1 = avgMs(metricsData.map((m) => m.stage1_latency_ms));
  const avgStage2 = avgMs(metricsData.map((m) => m.stage2_latency_ms));
  const sessionCompletenessRate =
    metricsData.length > 0
      ? `${Math.round((metricsData.filter((m) => m.session_completeness).length / metricsData.length) * 100)}%`
      : "--";

  const summaryCards = [
    { label: "Total Sessions", value: totalSessions.toString() },
    { label: "Active Clinicians", value: uniqueClinicians.toString() },
    { label: "Avg Completeness", value: avgCompleteness },
    { label: "Avg Citation Rate", value: avgCitation },
  ];

  const metrics = [
    { name: "Template Completeness", value: avgCompleteness, target: "90%", description: "Required sections populated per session" },
    { name: "Citation Traceability", value: avgCitation, target: "95%", description: "Claims with valid source ID" },
    { name: "Physician Edit Rate", value: avgEditRate, target: "N/A", description: "Diff between v1 draft and final note" },
    { name: "Conflict Rate", value: avgConflict, target: "Low", description: "Frame citations classified as CONFLICTS" },
    { name: "Low Confidence Frames", value: avgLowConf, target: "Low", description: "Frames discarded due to low confidence" },
    { name: "Stage 1 Latency", value: avgStage1, target: "< 30s", description: "Record stop to Stage 1 delivery" },
    { name: "Stage 2 Latency", value: avgStage2, target: "< 5 min", description: "Stage 1 approval to full note" },
    { name: "Session Completeness", value: sessionCompletenessRate, target: "100%", description: "Sessions with all 8 metrics logged" },
  ];

  // Compute specialty breakdown for chart
  const specialtyMap: Record<string, number> = {};
  sessionsData.forEach((s) => {
    const key = s.specialty.replace(/_/g, " ");
    specialtyMap[key] = (specialtyMap[key] || 0) + 1;
  });
  const specialties = Object.entries(specialtyMap).slice(0, 5);
  const maxSpecialty = Math.max(...specialties.map(([, v]) => v), 1);

  // Volume bar chart now drives off `timeseries.buckets` directly,
  // so the prior local weeklyBuckets / weeklyLabels block is gone.

  return (
    <>
      <Header title="Dashboard" subtitle="Pilot performance overview" />

      <div className="p-6 lg:p-8">
        {error && (
          <div className="mb-6 flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-600/10">
            <svg className="mt-0.5 h-4 w-4 shrink-0 text-red-500" viewBox="0 0 16 16" fill="currentColor">
              <path fillRule="evenodd" d="M8 15A7 7 0 108 1a7 7 0 000 14zm1-4a1 1 0 11-2 0 1 1 0 012 0zm0-3V5a1 1 0 10-2 0v3a1 1 0 102 0z" clipRule="evenodd"/>
            </svg>
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600">
              <svg className="h-4 w-4" viewBox="0 0 16 16" fill="currentColor"><path d="M4.28 3.22a.75.75 0 00-1.06 1.06L6.94 8l-3.72 3.72a.75.75 0 101.06 1.06L8 9.06l3.72 3.72a.75.75 0 101.06-1.06L9.06 8l3.72-3.72a.75.75 0 00-1.06-1.06L8 6.94 4.28 3.22z"/></svg>
            </button>
          </div>
        )}

        {/* Summary row */}
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4 stagger-children">
          {summaryCards.map((card, i) => (
            <div
              key={card.label}
              className="group relative overflow-hidden rounded-xl bg-navy p-5 shadow-card"
            >
              <div className="pointer-events-none absolute -right-3 -top-3 h-16 w-16 rounded-full bg-white/[0.04]" />
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
                    {card.label}
                  </p>
                  {loading ? (
                    <div className="mt-2 h-8 w-16 animate-shimmer rounded" />
                  ) : (
                    <p className="mt-1 text-3xl font-bold text-gradient-gold">{card.value}</p>
                  )}
                </div>
                <div className="rounded-lg bg-white/[0.06] p-2 text-gold-400">
                  {summaryIcons[i]}
                </div>
              </div>
            </div>
          ))}
        </div>

        {/* Metric cards */}
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Behaviour Metrics
        </h2>
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 stagger-children">
          {metrics.map((m) => {
            const status = metricStatus(m.value, m.target);
            return (
              <Card key={m.name} hoverable>
                <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
                  {m.name}
                </p>
                {loading ? (
                  <LoadingSkeleton lines={2} className="mt-3" />
                ) : (
                  <>
                    <p className="mt-2 text-2xl font-bold text-navy-700">{m.value}</p>
                    <p className="mt-1.5 text-xs text-gray-400">{m.description}</p>
                    <div className="mt-3">
                      <Badge variant={status} dot>
                        Target: {m.target}
                      </Badge>
                    </div>
                  </>
                )}
              </Card>
            );
          })}
        </div>

        {/* Trend (last 14 days) — 8 sparkline panels, one per pilot metric. */}
        <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
          Trend ({timeseries ? `${timeseries.from} → ${timeseries.to}` : "last 14 days"})
        </h2>
        {loading ? (
          <Card>
            <LoadingSkeleton lines={4} />
          </Card>
        ) : timeseries === null || timeseries.buckets.length === 0 ? (
          <Card>
            <p className="py-6 text-center text-sm text-gray-400">
              No time-series data available yet.
            </p>
          </Card>
        ) : (
          <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 stagger-children">
            <Sparkline
              title="Template completeness"
              buckets={timeseries.buckets}
              field="template_section_completeness"
              fmt={(v) => `${Math.round(v * 100)}%`}
              targetLabel="≥ 90%"
            />
            <Sparkline
              title="Citation traceability"
              buckets={timeseries.buckets}
              field="citation_traceability_rate"
              fmt={(v) => `${Math.round(v * 100)}%`}
              targetLabel="≥ 95%"
            />
            <Sparkline
              title="Conflict rate"
              buckets={timeseries.buckets}
              field="conflict_rate"
              fmt={(v) => `${Math.round(v * 100)}%`}
              targetLabel="Low"
              lowerIsBetter
            />
            <Sparkline
              title="Low confidence frames"
              buckets={timeseries.buckets}
              field="low_confidence_frame_rate"
              fmt={(v) => `${Math.round(v * 100)}%`}
              targetLabel="Low"
              lowerIsBetter
            />
            <Sparkline
              title="Stage 1 latency"
              buckets={timeseries.buckets}
              field="stage1_latency_ms"
              fmt={(v) => (v < 1000 ? `${Math.round(v)}ms` : `${(v / 1000).toFixed(1)}s`)}
              targetLabel="< 30s"
              lowerIsBetter
            />
            <Sparkline
              title="Stage 2 latency"
              buckets={timeseries.buckets}
              field="stage2_latency_ms"
              fmt={(v) => (v < 1000 ? `${Math.round(v)}ms` : `${(v / 1000).toFixed(1)}s`)}
              targetLabel="< 5 min"
              lowerIsBetter
            />
            <Sparkline
              title="Session completeness"
              buckets={timeseries.buckets}
              field="session_completeness"
              fmt={(v) => `${Math.round(v)}%`}
              targetLabel="100%"
            />
            <Sparkline
              title="Sessions / day"
              buckets={timeseries.buckets}
              field="session_count"
              fmt={(v) => `${Math.round(v)}`}
              targetLabel=""
            />
          </div>
        )}

        {/* Charts area */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card title={`Volume (${timeseries ? timeseries.buckets.length : 0} days)`}>
            {loading || !timeseries || timeseries.buckets.length === 0 ? (
              <div className="flex h-48 items-center justify-center">
                <p className="text-sm text-gray-400">
                  {loading ? "Loading..." : "No session data available yet."}
                </p>
              </div>
            ) : (
              <div className="flex h-48 items-end justify-around gap-1 pt-4">
                {timeseries.buckets.map((b, i) => {
                  const maxV = Math.max(
                    1,
                    ...timeseries.buckets.map((x) => x.session_count),
                  );
                  const height = (b.session_count / maxV) * 100;
                  const isToday = i === timeseries.buckets.length - 1;
                  // Only label every other day if window is long.
                  const showLabel =
                    timeseries.buckets.length <= 14 ||
                    i % Math.ceil(timeseries.buckets.length / 7) === 0;
                  return (
                    <div
                      key={b.date}
                      className="group flex flex-1 flex-col items-center gap-1.5"
                      title={`${b.date}: ${b.session_count} session${b.session_count === 1 ? "" : "s"}`}
                    >
                      <span className="text-[10px] font-semibold text-navy-600 opacity-0 transition-opacity group-hover:opacity-100">
                        {b.session_count}
                      </span>
                      <div
                        className="w-full overflow-hidden rounded-t-md transition-all duration-500 ease-out"
                        style={{ height: `${Math.max(height, 4)}%` }}
                      >
                        <div className="h-full w-full rounded-t-md bg-gradient-to-t from-gold-500 to-gold-300" />
                      </div>
                      <span
                        className={`text-[9px] font-medium ${isToday ? "text-navy-600" : "text-gray-400"}`}
                      >
                        {showLabel ? b.date.slice(5) : ""}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>

          <Card title="By Specialty">
            {loading || specialties.length === 0 ? (
              <div className="flex h-48 items-center justify-center">
                <p className="text-sm text-gray-400">
                  {loading ? "Loading..." : "No specialty data available yet."}
                </p>
              </div>
            ) : (
              <div className="space-y-3 py-2">
                {specialties.map(([name, count]) => {
                  const pct = (count / maxSpecialty) * 100;
                  return (
                    <div key={name} className="group">
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-xs font-medium capitalize text-gray-600">{name}</span>
                        <span className="text-xs font-semibold text-navy-600">{count}</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-gray-100">
                        <div
                          className="h-full rounded-full bg-gradient-to-r from-navy-400 to-navy-600 transition-all duration-500"
                          style={{ width: `${Math.max(pct, 4)}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </Card>
        </div>
      </div>
    </>
  );
}

// ── Sparkline — CSS-only mini bar chart per metric ─────────────────────────
//
// Renders one short bar per bucket. Bars share a single max so the
// proportions are honest within one card. A separate chart library
// (recharts / ECharts) is a follow-up — keeping CSS-only here keeps
// the dependency surface stable for the pilot.

type SparklineField = keyof Pick<
  MetricTimeseriesBucket,
  | "template_section_completeness"
  | "citation_traceability_rate"
  | "physician_edit_rate"
  | "conflict_rate"
  | "low_confidence_frame_rate"
  | "stage1_latency_ms"
  | "stage2_latency_ms"
  | "session_completeness"
  | "session_count"
>;

function Sparkline({
  title,
  buckets,
  field,
  fmt,
  targetLabel,
  lowerIsBetter,
}: {
  title: string;
  buckets: MetricTimeseriesBucket[];
  field: SparklineField;
  fmt: (v: number) => string;
  targetLabel: string;
  lowerIsBetter?: boolean;
}) {
  const values: Array<number | null> = buckets.map((b) => {
    const v = b[field];
    return v === null || v === undefined ? null : Number(v);
  });
  const nonNull = values.filter((v): v is number => v !== null);
  const max = nonNull.length === 0 ? 1 : Math.max(...nonNull);
  const min = nonNull.length === 0 ? 0 : Math.min(...nonNull);
  const span = Math.max(max - min, 1e-6);
  const latest = nonNull.length === 0 ? null : nonNull[nonNull.length - 1];
  const avg =
    nonNull.length === 0
      ? null
      : nonNull.reduce((a, b) => a + b, 0) / nonNull.length;

  return (
    <Card>
      <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
        {title}
      </p>
      <div className="mt-1 flex items-baseline justify-between">
        <p className="text-2xl font-bold text-navy-700 tabular-nums">
          {latest === null ? "—" : fmt(latest)}
        </p>
        {targetLabel && (
          <span className="text-[10px] font-medium text-gray-400">
            target {targetLabel}
          </span>
        )}
      </div>
      <p className="mt-0.5 text-[11px] text-gray-400">
        avg {avg === null ? "—" : fmt(avg)}
      </p>
      <div className="mt-3 flex h-12 items-end gap-0.5">
        {values.map((v, i) => {
          if (v === null) {
            return (
              <div
                key={i}
                className="flex-1 self-stretch rounded-sm bg-gray-100"
                title={`${buckets[i].date}: no data`}
              />
            );
          }
          // Normalize to [0..1] of (v - min) / span so flat regions look
          // flat, not all zero or all max.
          const norm = (v - min) / span;
          // Floor at 8% so a real-but-low value still shows a sliver.
          const pct = Math.max(8, Math.round(norm * 100));
          const colorClass = lowerIsBetter
            ? "from-emerald-300 to-emerald-500"
            : "from-gold-300 to-gold-500";
          return (
            <div
              key={i}
              className={`flex-1 rounded-sm bg-gradient-to-t ${colorClass}`}
              style={{ height: `${pct}%` }}
              title={`${buckets[i].date}: ${fmt(v)}`}
            />
          );
        })}
      </div>
    </Card>
  );
}
