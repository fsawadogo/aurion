"use client";

/**
 * /portal/admin/analytics — adoption & ROI rollup (#71, slice 2).
 * EVAL_TEAM or ADMIN (enforced server-side on the endpoint; the Sidebar
 * link mirrors the gate).
 *
 * Reads GET /api/v1/admin/analytics/adoption: adoption stat cards, quality
 * averages, a per-clinician table, and CSV export. Time-saved appears ONLY
 * after the admin supplies a baseline (minutes of manual documentation per
 * note) — the figure is an opt-in estimate traceable to that assumption,
 * never a server-invented claim.
 */

import { Clock3, Download, TrendingUp, Users } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import { exportAdoptionCsv, getAdoptionAnalytics, humanizeError } from "@/lib/api";
import { formatRelative } from "@/lib/session-format";
import type { AdoptionResponse } from "@/types";

const RANGES = [
  { key: "7d", days: 7 },
  { key: "30d", days: 30 },
  { key: "90d", days: 90 },
  { key: "all", days: null },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

function pct(fraction: number | null): string {
  return fraction === null ? "—" : `${(fraction * 100).toFixed(1)}%`;
}

function latency(ms: number | null): string {
  if (ms === null) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

/** Minutes → "Xh Ym" (or "Ym" under an hour). */
function hours(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return h > 0 ? `${h} h ${m} min` : `${m} min`;
}

export default function AdminAnalyticsPage() {
  const t = useTranslations("AdminAnalytics");
  const format = useFormatter();

  const [range, setRange] = useState<RangeKey>("30d");
  // The raw input string (so the field can be cleared); parsed on change.
  const [baselineInput, setBaselineInput] = useState("");
  const [data, setData] = useState<AdoptionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const baseline = (() => {
    const v = Number(baselineInput);
    return baselineInput.trim() !== "" && Number.isFinite(v) && v > 0 && v <= 120
      ? v
      : undefined;
  })();

  const buildOpts = useCallback(() => {
    const days = RANGES.find((r) => r.key === range)?.days ?? null;
    const since = days
      ? new Date(Date.now() - days * 86_400_000).toISOString()
      : undefined;
    return {
      ...(since ? { since } : {}),
      ...(baseline !== undefined ? { baselineMinutesPerNote: baseline } : {}),
    };
  }, [range, baseline]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await getAdoptionAnalytics(buildOpts());
        if (!cancelled) setData(res);
      } catch (e) {
        if (!cancelled) setError(humanizeError(e, t("loadError")));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [buildOpts, t]);

  async function onExport() {
    setExporting(true);
    setError(null);
    try {
      const blob = await exportAdoptionCsv(buildOpts());
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "aurion_adoption.csv";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(humanizeError(e, t("exportError")));
    } finally {
      setExporting(false);
    }
  }

  const totals = data?.totals;

  return (
    <div className="aurion-page-padded aurion-container-narrow" data-testid="analytics-page">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={
          <Button
            variant="secondary"
            size="sm"
            loading={exporting}
            disabled={exporting || loading}
            onClick={() => void onExport()}
          >
            <Download className="h-4 w-4 mr-1" />
            {t("exportCsv")}
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex gap-1" role="group" aria-label={t("rangeLabel")}>
          {RANGES.map((r) => {
            const active = range === r.key;
            return (
              <button
                key={r.key}
                type="button"
                disabled={active || loading}
                onClick={() => setRange(r.key)}
                aria-pressed={active}
                data-testid={`analytics-range-${r.key}`}
                className={
                  "rounded-aurion-md border px-2.5 py-1 text-xs font-medium transition-colors duration-short ease-aurion " +
                  "focus:outline-none focus:ring-2 focus:ring-gold-300/40 disabled:cursor-default " +
                  (active
                    ? "border-navy-700 bg-navy-700 text-white"
                    : "border-navy-200 text-navy-600 hover:bg-navy-50")
                }
              >
                {t(`ranges.${r.key}`)}
              </button>
            );
          })}
        </div>

        <label className="flex items-center gap-2 text-aurion-caption text-navy-600">
          <Clock3 className="h-4 w-4 text-gold-600" aria-hidden="true" />
          {t("baselineLabel")}
          <input
            type="number"
            min={1}
            max={120}
            step={1}
            value={baselineInput}
            onChange={(e) => setBaselineInput(e.target.value)}
            placeholder={t("baselinePlaceholder")}
            data-testid="baseline-input"
            className="w-20 rounded-aurion-md border border-navy-200 px-2 py-1 text-aurion-caption text-navy-800 focus:outline-none focus:ring-2 focus:ring-gold-300/40"
          />
          {t("baselineUnit")}
        </label>
      </div>

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          {error}
        </div>
      )}

      {loading || !totals || !data ? (
        <Card>
          <LoadingSkeleton lines={8} />
        </Card>
      ) : (
        <>
          <h2 className="mb-3 text-aurion-body font-semibold text-navy-800">
            {t("adoptionRoi")}
          </h2>
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {(
              [
                ["activeClinicians", format.number(totals.active_clinicians), Users],
                ["notesExported", format.number(totals.sessions_exported), TrendingUp],
                ["notesPerDay", format.number(totals.notes_per_active_day), TrendingUp],
                [
                  "timeSaved",
                  totals.time_saved_minutes === null
                    ? "—"
                    : hours(totals.time_saved_minutes),
                  Clock3,
                ],
              ] as const
            ).map(([key, value]) => (
              <div
                key={key}
                className="rounded-aurion-md border border-hairline bg-white px-4 py-3"
              >
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {t(`stats.${key}`)}
                </dt>
                <dd
                  className="mt-1 text-xl font-semibold tabular-nums text-navy-800"
                  data-testid={`analytics-stat-${key}`}
                >
                  {value}
                </dd>
                {key === "timeSaved" && (
                  <p className="mt-1 text-[11px] leading-snug text-navy-400">
                    {totals.time_saved_minutes === null
                      ? t("timeSavedNeedsBaseline")
                      : t("timeSavedAssumption", {
                          baseline: data.baseline_minutes_per_note ?? 0,
                        })}
                  </p>
                )}
              </div>
            ))}
          </dl>

          <h2 className="mb-3 mt-6 text-aurion-body font-semibold text-navy-800">
            {t("qualityPerformance")}
          </h2>
          <dl className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {(
              [
                ["completeness", pct(totals.avg_completeness)],
                ["citation", pct(totals.avg_citation_traceability)],
                ["editRate", pct(totals.avg_edit_rate)],
                ["stage1", latency(totals.avg_stage1_latency_ms)],
              ] as const
            ).map(([key, value]) => (
              <div
                key={key}
                className="rounded-aurion-md border border-hairline bg-white px-4 py-3"
              >
                <dt className="text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {t(`quality.${key}`)}
                </dt>
                <dd
                  className="mt-1 text-xl font-semibold tabular-nums text-navy-800"
                  data-testid={`analytics-quality-${key}`}
                >
                  {value}
                </dd>
              </div>
            ))}
          </dl>

          <div className="mt-4 overflow-x-auto rounded-aurion-md border border-hairline bg-white">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80">
                  {(
                    ["clinician", "sessions", "exported", "perDay", "completeness", "editRate", "timeSaved", "lastActive"] as const
                  ).map((col) => (
                    <th
                      key={col}
                      className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400"
                    >
                      {t(`table.${col}`)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.by_clinician.length === 0 ? (
                  <tr>
                    <td
                      colSpan={8}
                      className="px-4 py-6 text-center text-aurion-callout text-navy-500"
                    >
                      {t("empty")}
                    </td>
                  </tr>
                ) : (
                  data.by_clinician.map((row) => (
                    <tr key={row.clinician_id} data-testid={`analytics-row-${row.clinician_id}`}>
                      <td className="px-4 py-3 text-aurion-callout font-medium text-navy-800">
                        {row.email ?? row.clinician_id.slice(0, 8)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {format.number(row.sessions_total)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {format.number(row.sessions_exported)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {format.number(row.notes_per_active_day)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {pct(row.avg_completeness)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {pct(row.avg_edit_rate)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {row.time_saved_minutes === null ? "—" : hours(row.time_saved_minutes)}
                      </td>
                      <td className="px-4 py-3 text-aurion-caption text-navy-500">
                        {row.last_active_at ? formatRelative(row.last_active_at) : "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          <p className="mt-2 text-aurion-caption text-navy-400">{t("footnote")}</p>
        </>
      )}
    </div>
  );
}
