"use client";

/**
 * Provider usage & cost rollup (#73) — rendered below the runtime switch on
 * /portal/admin/providers, so the latency/success/fallback/cost picture sits
 * next to the knob it informs.
 *
 * Reads GET /api/v1/admin/providers/usage (ADMIN + COMPLIANCE_OFFICER).
 * Token/cost capture is partial today (vision live; note_generation /
 * transcription land with the provider-interface usage surfacing), so zero
 * cost renders as "—" with a footnote rather than a misleading "$0.00".
 */

import { BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getProviderUsage, humanizeError } from "@/lib/api";
import type { ProviderUsageResponse } from "@/types";

/** Lookback windows for the range picker. `null` = all recorded usage. */
const RANGES = [
  { key: "24h", hours: 24 },
  { key: "7d", hours: 24 * 7 },
  { key: "30d", hours: 24 * 30 },
  { key: "all", hours: null },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

// Brand display names — proper nouns, not localized. Mirrors the switch
// section above (page.tsx VALUE_LABEL).
const VALUE_LABEL: Record<string, string> = {
  whisper: "Whisper",
  assemblyai: "AssemblyAI",
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
};

function pct(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}

function latency(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

function tokens(input: number, output: number): string {
  const total = input + output;
  return total === 0 ? "—" : total.toLocaleString();
}

function cost(usd: number): string {
  return usd === 0 ? "—" : `$${usd.toFixed(usd < 1 ? 4 : 2)}`;
}

export default function ProviderUsagePanel() {
  const t = useTranslations("Providers.usage");

  const [range, setRange] = useState<RangeKey>("7d");
  const [data, setData] = useState<ProviderUsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const hours = RANGES.find((r) => r.key === range)?.hours ?? null;
        const since = hours
          ? new Date(Date.now() - hours * 3_600_000).toISOString()
          : undefined;
        const res = await getProviderUsage(since ? { since } : undefined);
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
  }, [range, t]);

  const totals = data?.totals;
  const empty = !loading && !error && (totals?.call_count ?? 0) === 0;

  return (
    <section className="mt-8" data-testid="provider-usage-panel">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-aurion-body font-semibold text-navy-800">
            <BarChart3 className="h-4 w-4 text-gold-600" aria-hidden="true" />
            {t("title")}
          </h2>
          <p className="mt-1 text-aurion-caption text-navy-500">{t("subtitle")}</p>
        </div>
        <div className="flex gap-1" role="group" aria-label={t("rangeLabel")}>
          {RANGES.map((r) => {
            const active = range === r.key;
            return (
              <button
                key={r.key}
                type="button"
                disabled={active}
                onClick={() => setRange(r.key)}
                aria-pressed={active}
                data-testid={`usage-range-${r.key}`}
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
      </div>

      {error && (
        <div
          className="mt-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          {error}
        </div>
      )}

      {loading ? (
        <div className="mt-4">
          <Card>
            <LoadingSkeleton lines={5} />
          </Card>
        </div>
      ) : empty ? (
        <div className="mt-4">
          <Card>
            <p className="py-4 text-center text-aurion-callout text-navy-500">
              {t("empty")}
            </p>
          </Card>
        </div>
      ) : totals && data ? (
        <>
          <dl className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {(
              [
                ["calls", totals.call_count.toLocaleString()],
                ["successRate", pct(totals.call_count ? totals.success_count / totals.call_count : 0)],
                ["avgLatency", latency(totals.avg_latency_ms)],
                ["estCost", cost(totals.total_cost_usd)],
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
                  data-testid={`usage-stat-${key}`}
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
                  {(["stage", "provider", "callsCol", "success", "fallback", "latencyCol", "tokensCol", "costCol"] as const).map(
                    (col) => (
                      <th
                        key={col}
                        className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400"
                      >
                        {t(`table.${col}`)}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {data.by_provider.map((row) => (
                  <tr
                    key={`${row.provider_type}:${row.provider_name}`}
                    data-testid={`usage-row-${row.provider_type}-${row.provider_name}`}
                  >
                    <td className="px-4 py-3 text-aurion-caption text-navy-500">
                      {t(`stages.${row.provider_type}`)}
                    </td>
                    <td className="px-4 py-3 text-aurion-callout font-medium text-navy-800">
                      {VALUE_LABEL[row.provider_name] ?? row.provider_name}
                    </td>
                    <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                      {row.call_count.toLocaleString()}
                    </td>
                    <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                      {pct(row.success_rate)}
                    </td>
                    <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                      {pct(row.fallback_rate)}
                    </td>
                    <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                      {latency(row.avg_latency_ms)}
                    </td>
                    <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                      {tokens(row.total_input_tokens, row.total_output_tokens)}
                    </td>
                    <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                      {cost(row.total_cost_usd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <p className="mt-2 text-aurion-caption text-navy-400">{t("costFootnote")}</p>
        </>
      ) : null}
    </section>
  );
}
