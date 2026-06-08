"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getMe, getMetrics, getMetricsTimeseries, getSessions, humanizeError} from "@/lib/api";
import { humanSpecialty } from "@/lib/session-format";
import type {
  MetricTimeseriesBucket,
  MetricTimeseriesResponse,
  PilotMetric,
  Session,
} from "@/types";

// Single placeholder for any metric without data — an em dash, rendered
// muted so an empty pilot dashboard reads as "awaiting data", not broken.
const EMPTY = "—";

type MetricTone = "success" | "warning" | "error" | "neutral";

const pctFmt = (v: number) => `${Math.round(v * 100)}%`;
const msFmt = (v: number) =>
  v < 1000 ? `${Math.round(v)}ms` : `${(v / 1000).toFixed(1)}s`;

function metricTone(value: string, target: string): MetricTone {
  if (value === EMPTY) return "neutral";
  const num = parseFloat(value);
  if (isNaN(num)) return "neutral";
  if (target === "90%") return num >= 90 ? "success" : num >= 75 ? "warning" : "error";
  if (target === "95%") return num >= 95 ? "success" : num >= 85 ? "warning" : "error";
  if (target === "100%") return num >= 100 ? "success" : num >= 90 ? "warning" : "error";
  if (target === "< 30s") {
    const ms = value.endsWith("ms") ? num : num * 1000;
    return ms <= 30000 ? "success" : ms <= 60000 ? "warning" : "error";
  }
  if (target === "< 5 min") {
    const ms = value.endsWith("ms") ? num : num * 1000;
    return ms <= 300000 ? "success" : ms <= 600000 ? "warning" : "error";
  }
  if (target === "Low") return num <= 5 ? "success" : num <= 15 ? "warning" : "error";
  return "neutral";
}

const toneDot: Record<MetricTone, string> = {
  success: "bg-emerald-400",
  warning: "bg-amber-400",
  error: "bg-red-400",
  neutral: "bg-gray-200",
};

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
        setError(humanizeError(err, "Failed to load dashboard data"));
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
    if (valid.length === 0) return EMPTY;
    const mean = valid.reduce((a, b) => a + b, 0) / valid.length;
    return `${Math.round(mean * 100)}%`;
  }

  function avgMs(values: (number | null | undefined)[]): string {
    const valid = values.filter((v): v is number => v != null);
    if (valid.length === 0) return EMPTY;
    const mean = valid.reduce((a, b) => a + b, 0) / valid.length;
    return mean < 1000 ? `${Math.round(mean)}ms` : `${(mean / 1000).toFixed(1)}s`;
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
      : EMPTY;

  const summaryCards = [
    { label: "Total Sessions", value: totalSessions.toString(), caption: "captured in the pilot" },
    { label: "Active Clinicians", value: uniqueClinicians.toString(), caption: "recording sessions" },
    { label: "Avg Completeness", value: avgCompleteness, caption: "target ≥ 90%" },
    { label: "Avg Citation Rate", value: avgCitation, caption: "target ≥ 95%" },
  ];

  // The 8 pilot behaviour metrics — each shows its headline value, target,
  // and (where the timeseries carries it) an inline 14-day trend. Merges
  // what used to be two separate sections (value cards + sparklines).
  const metrics: MetricRow[] = [
    { name: "Template Completeness", value: avgCompleteness, target: "90%", description: "Required sections populated per session", field: "template_section_completeness", fmt: pctFmt },
    { name: "Citation Traceability", value: avgCitation, target: "95%", description: "Claims with a valid source ID", field: "citation_traceability_rate", fmt: pctFmt },
    { name: "Physician Edit Rate", value: avgEditRate, target: "N/A", description: "Diff between v1 draft and final note", field: null },
    { name: "Conflict Rate", value: avgConflict, target: "Low", description: "Frame citations flagged CONFLICTS", field: "conflict_rate", fmt: pctFmt, lowerIsBetter: true },
    { name: "Low Confidence Frames", value: avgLowConf, target: "Low", description: "Frames discarded for low confidence", field: "low_confidence_frame_rate", fmt: pctFmt, lowerIsBetter: true },
    { name: "Stage 1 Latency", value: avgStage1, target: "< 30s", description: "Record stop → Stage 1 delivery", field: "stage1_latency_ms", fmt: msFmt, lowerIsBetter: true },
    { name: "Stage 2 Latency", value: avgStage2, target: "< 5 min", description: "Stage 1 approval → full note", field: "stage2_latency_ms", fmt: msFmt, lowerIsBetter: true },
    { name: "Session Completeness", value: sessionCompletenessRate, target: "100%", description: "Sessions with all 8 metrics logged", field: "session_completeness", fmt: (v) => `${Math.round(v)}%` },
  ];

  // Specialty breakdown.
  const specialtyMap: Record<string, number> = {};
  sessionsData.forEach((s) => {
    specialtyMap[s.specialty] = (specialtyMap[s.specialty] || 0) + 1;
  });
  const specialties = Object.entries(specialtyMap)
    .sort(([, a], [, b]) => b - a)
    .slice(0, 5);
  const maxSpecialty = Math.max(...specialties.map(([, v]) => v), 1);

  const windowLabel = timeseries ? `${timeseries.from} → ${timeseries.to}` : "last 14 days";
  const buckets = timeseries?.buckets ?? [];

  return (
    <>
      <Header
        title="Dashboard"
        subtitle="Pilot performance overview"
        actions={
          <span className="hidden items-center gap-1.5 rounded-full bg-gray-50 px-2.5 py-1 text-[11px] font-medium text-gray-500 ring-1 ring-inset ring-gray-200 sm:inline-flex">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            {windowLabel}
          </span>
        }
      />

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
          {summaryCards.map((card, i) => {
            const empty = card.value === EMPTY;
            return (
              <div
                key={card.label}
                className="group relative overflow-hidden rounded-xl bg-navy p-5 shadow-card"
              >
                <div className="pointer-events-none absolute -right-3 -top-3 h-16 w-16 rounded-full bg-white/[0.04]" />
                <div className="flex items-start justify-between">
                  <div className="min-w-0">
                    <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
                      {card.label}
                    </p>
                    {loading ? (
                      <div className="mt-2 h-8 w-16 animate-shimmer rounded" />
                    ) : (
                      <p
                        className={`mt-1 text-3xl font-bold tabular-nums ${empty ? "text-white/30" : "text-gradient-gold"}`}
                      >
                        {card.value}
                      </p>
                    )}
                    <p className="mt-1 text-[11px] text-gray-500">{card.caption}</p>
                  </div>
                  <div className="rounded-lg bg-white/[0.06] p-2 text-gold-400">
                    {summaryIcons[i]}
                  </div>
                </div>
              </div>
            );
          })}
        </div>

        {/* Behaviour metrics — value + target + inline 14-day trend */}
        <div className="mb-4 flex items-baseline justify-between">
          <h2 className="text-sm font-semibold uppercase tracking-wider text-gray-400">
            Behaviour Metrics
          </h2>
          <span className="text-[11px] text-gray-400">14-day trend · {windowLabel}</span>
        </div>
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4 stagger-children">
          {metrics.map((m) => (
            <MetricCard key={m.name} metric={m} buckets={buckets} loading={loading} />
          ))}
        </div>

        {/* Volume + specialty */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <Card title={`Daily Volume (${buckets.length} ${buckets.length === 1 ? "day" : "days"})`}>
            {loading || buckets.length === 0 ? (
              <EmptyPanel loading={loading} label="No session volume yet." />
            ) : (
              <div className="flex h-48 items-end justify-around gap-1 pt-4">
                {buckets.map((b, i) => {
                  const maxV = Math.max(1, ...buckets.map((x) => x.session_count));
                  const height = (b.session_count / maxV) * 100;
                  const isToday = i === buckets.length - 1;
                  const showLabel =
                    buckets.length <= 14 ||
                    i % Math.ceil(buckets.length / 7) === 0;
                  return (
                    <div
                      key={b.date}
                      className="group flex flex-1 flex-col items-center gap-1.5"
                      title={`${b.date}: ${b.session_count} session${b.session_count === 1 ? "" : "s"}`}
                    >
                      <span className="text-[10px] font-semibold tabular-nums text-navy-600 opacity-0 transition-opacity group-hover:opacity-100">
                        {b.session_count}
                      </span>
                      <div
                        className="w-full overflow-hidden rounded-t-md transition-all duration-500 ease-out"
                        style={{ height: `${Math.max(height, 4)}%` }}
                      >
                        <div className="h-full w-full rounded-t-md bg-gradient-to-t from-gold-500 to-gold-300" />
                      </div>
                      <span
                        className={`text-[9px] font-medium tabular-nums ${isToday ? "text-navy-600" : "text-gray-400"}`}
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
              <EmptyPanel loading={loading} label="No specialty data yet." />
            ) : (
              <div className="space-y-3 py-2">
                {specialties.map(([key, count]) => {
                  const pct = (count / maxSpecialty) * 100;
                  return (
                    <div key={key} className="group">
                      <div className="mb-1 flex items-center justify-between">
                        <span className="text-xs font-medium text-gray-600">
                          {humanSpecialty(key)}
                        </span>
                        <span className="text-xs font-semibold tabular-nums text-navy-600">
                          {count}
                        </span>
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

// ── Metric card — headline value + target + inline 14-day sparkline ─────────

type SparklineField = keyof Pick<
  MetricTimeseriesBucket,
  | "template_section_completeness"
  | "citation_traceability_rate"
  | "conflict_rate"
  | "low_confidence_frame_rate"
  | "stage1_latency_ms"
  | "stage2_latency_ms"
  | "session_completeness"
>;

type MetricRow = {
  name: string;
  value: string;
  target: string;
  description: string;
  field: SparklineField | null;
  fmt?: (v: number) => string;
  lowerIsBetter?: boolean;
};

function MetricCard({
  metric,
  buckets,
  loading,
}: {
  metric: MetricRow;
  buckets: MetricTimeseriesBucket[];
  loading: boolean;
}) {
  const { name, value, target, description, field, fmt, lowerIsBetter } = metric;
  const empty = value === EMPTY;
  const tone = metricTone(value, target);

  return (
    <Card hoverable>
      <div className="flex items-start justify-between gap-2">
        <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
          {name}
        </p>
        <span
          className={`mt-1 h-2 w-2 shrink-0 rounded-full ${toneDot[tone]}`}
          aria-hidden
        />
      </div>

      {loading ? (
        <LoadingSkeleton lines={2} className="mt-3" />
      ) : (
        <>
          <div className="mt-1.5 flex items-baseline gap-1.5">
            <p
              className={`text-2xl font-bold tabular-nums ${empty ? "text-gray-300" : "text-navy-700"}`}
            >
              {value}
            </p>
            {target !== "N/A" && (
              <span className="text-[11px] font-medium text-gray-400">
                / {target}
              </span>
            )}
          </div>
          <p className="mt-1 text-[11px] leading-snug text-gray-400">
            {description}
          </p>
          <div className="mt-3 h-9">
            {field && fmt ? (
              <MiniSparkline
                buckets={buckets}
                field={field}
                lowerIsBetter={lowerIsBetter}
              />
            ) : (
              <div className="flex h-full items-center">
                <span className="text-[10px] text-gray-300">
                  No trend available
                </span>
              </div>
            )}
          </div>
        </>
      )}
    </Card>
  );
}

// CSS-only mini bar chart — one bar per day. Shares a single min/max so
// flat regions look flat (not all-zero / all-max). A real chart lib is a
// post-pilot follow-up; CSS keeps the dependency surface stable.
function MiniSparkline({
  buckets,
  field,
  lowerIsBetter,
}: {
  buckets: MetricTimeseriesBucket[];
  field: SparklineField;
  lowerIsBetter?: boolean;
}) {
  const values = buckets.map((b) => {
    const v = b[field];
    return v === null || v === undefined ? null : Number(v);
  });
  const nonNull = values.filter((v): v is number => v !== null);

  if (nonNull.length === 0) {
    return (
      <div className="flex h-full items-center">
        <span className="text-[10px] text-gray-300">Awaiting data</span>
      </div>
    );
  }

  const max = Math.max(...nonNull);
  const min = Math.min(...nonNull);
  const span = Math.max(max - min, 1e-6);
  const colorClass = lowerIsBetter
    ? "from-emerald-300 to-emerald-500"
    : "from-gold-300 to-gold-500";

  return (
    <div className="flex h-full items-end gap-0.5">
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
        const norm = (v - min) / span;
        const pct = Math.max(8, Math.round(norm * 100));
        return (
          <div
            key={i}
            className={`flex-1 rounded-sm bg-gradient-to-t ${colorClass}`}
            style={{ height: `${pct}%` }}
            title={`${buckets[i].date}`}
          />
        );
      })}
    </div>
  );
}

function EmptyPanel({ loading, label }: { loading: boolean; label: string }) {
  return (
    <div className="flex h-48 flex-col items-center justify-center gap-2 text-gray-300">
      {loading ? (
        <p className="text-sm text-gray-400">Loading…</p>
      ) : (
        <>
          <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
            <path strokeLinecap="round" strokeLinejoin="round" d="M3 13.5 9 9l4 3 5-6M3 20h18" />
          </svg>
          <p className="text-sm text-gray-400">{label}</p>
        </>
      )}
    </div>
  );
}
