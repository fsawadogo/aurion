"use client";

/**
 * Provider A-B compare (#73/#74) — rendered below the usage panel on
 * /portal/admin/providers so the comparison sits next to the switch it
 * informs.
 *
 * Two layers:
 * - Operational (GET /admin/providers/compare): calls, success/fallback,
 *   latency, cost for a chosen A vs B within one provider type.
 * - Quality (GET /admin/providers/compare-quality): eval-team score
 *   averages per provider. EVAL_TEAM + ADMIN server-side — a
 *   COMPLIANCE_OFFICER viewing this ADMIN+COMPLIANCE page gets a 403 on
 *   this call only, so the quality section hides instead of failing the
 *   page. Sample sizes ride with every row: at pilot N the differences
 *   are directional, not significant, and the caption says so.
 */

import { Scale } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  compareProviderQuality,
  compareProviders,
  humanizeError,
} from "@/lib/api";
import type {
  ProviderCompareResponse,
  ProviderQualityCompareResponse,
  ProviderType,
  ProviderUsageRollup,
} from "@/types";

const TYPE_OPTIONS: Record<ProviderType, string[]> = {
  note_generation: ["openai", "anthropic", "gemini"],
  vision: ["openai", "anthropic", "gemini"],
  transcription: ["whisper", "assemblyai"],
};

const VALUE_LABEL: Record<string, string> = {
  whisper: "Whisper",
  assemblyai: "AssemblyAI",
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
};

const RANGES = [
  { key: "7d", days: 7 },
  { key: "30d", days: 30 },
  { key: "all", days: null },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

function pct(fraction: number | null | undefined): string {
  return fraction === null || fraction === undefined
    ? "—"
    : `${(fraction * 100).toFixed(1)}%`;
}

function latency(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}

function cost(usd: number | null | undefined): string {
  if (!usd) return "—";
  return `$${usd.toFixed(usd < 1 ? 4 : 2)}`;
}

function score(v: number | null): string {
  return v === null ? "—" : v.toFixed(2);
}

export default function ProviderComparePanel() {
  const t = useTranslations("ProviderCompare");
  const format = useFormatter();

  const [providerType, setProviderType] = useState<ProviderType>("note_generation");
  const [a, setA] = useState("anthropic");
  const [b, setB] = useState("gemini");
  const [range, setRange] = useState<RangeKey>("30d");
  const [operational, setOperational] = useState<ProviderCompareResponse | null>(null);
  const [quality, setQuality] = useState<ProviderQualityCompareResponse | null>(null);
  const [qualityHidden, setQualityHidden] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const sinceIso = useCallback(() => {
    const days = RANGES.find((r) => r.key === range)?.days ?? null;
    return days ? new Date(Date.now() - days * 86_400_000).toISOString() : undefined;
  }, [range]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const since = sinceIso();
        const op = await compareProviders({
          a,
          b,
          providerType,
          ...(since ? { since } : {}),
        });
        if (!cancelled) setOperational(op);
      } catch (e) {
        if (!cancelled) setError(humanizeError(e, t("loadError")));
      }
      try {
        const since = sinceIso();
        const q = await compareProviderQuality(since ? { since } : undefined);
        if (!cancelled) {
          setQuality(q);
          setQualityHidden(false);
        }
      } catch {
        // EVAL_TEAM-gated — a COMPLIANCE_OFFICER 403s here; hide the
        // section rather than failing the whole panel.
        if (!cancelled) setQualityHidden(true);
      }
      if (!cancelled) setLoading(false);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [a, b, providerType, sinceIso, t]);

  // Keep A/B valid when the type changes.
  useEffect(() => {
    const opts = TYPE_OPTIONS[providerType];
    if (!opts.includes(a)) setA(opts[0]);
    if (!opts.includes(b)) setB(opts[1] ?? opts[0]);
  }, [providerType, a, b]);

  const rows: Array<{
    key: string;
    label: string;
    value: (r: ProviderUsageRollup | null) => string;
  }> = [
    { key: "calls", label: t("rows.calls"), value: (r) => (r ? format.number(r.call_count) : "—") },
    { key: "success", label: t("rows.success"), value: (r) => pct(r?.success_rate ?? null) },
    { key: "fallback", label: t("rows.fallback"), value: (r) => pct(r?.fallback_rate ?? null) },
    { key: "latency", label: t("rows.latency"), value: (r) => latency(r?.avg_latency_ms ?? null) },
    { key: "cost", label: t("rows.cost"), value: (r) => cost(r?.total_cost_usd ?? null) },
  ];

  return (
    <section className="mt-8" data-testid="provider-compare-panel">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 text-aurion-body font-semibold text-navy-800">
            <Scale className="h-4 w-4 text-gold-600" aria-hidden="true" />
            {t("title")}
          </h2>
          <p className="mt-1 text-aurion-caption text-navy-500">{t("subtitle")}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={providerType}
            onChange={(e) => setProviderType(e.target.value as ProviderType)}
            aria-label={t("typeLabel")}
            data-testid="compare-type"
            className="rounded-aurion-md border border-navy-200 px-2 py-1 text-xs font-medium text-navy-700 focus:outline-none focus:ring-2 focus:ring-gold-300/40"
          >
            {(Object.keys(TYPE_OPTIONS) as ProviderType[]).map((tp) => (
              <option key={tp} value={tp}>
                {t(`types.${tp}`)}
              </option>
            ))}
          </select>
          {(["a", "b"] as const).map((side) => (
            <select
              key={side}
              value={side === "a" ? a : b}
              onChange={(e) => (side === "a" ? setA : setB)(e.target.value)}
              aria-label={t(side === "a" ? "providerA" : "providerB")}
              data-testid={`compare-${side}`}
              className="rounded-aurion-md border border-navy-200 px-2 py-1 text-xs font-medium text-navy-700 focus:outline-none focus:ring-2 focus:ring-gold-300/40"
            >
              {TYPE_OPTIONS[providerType].map((opt) => (
                <option key={opt} value={opt}>
                  {VALUE_LABEL[opt] ?? opt}
                </option>
              ))}
            </select>
          ))}
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
                  data-testid={`compare-range-${r.key}`}
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
      ) : operational ? (
        <div className="mt-4 overflow-x-auto rounded-aurion-md border border-hairline bg-white">
          <table className="min-w-full" data-testid="operational-table">
            <thead>
              <tr className="border-b border-gray-100 bg-gray-50/80">
                <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">
                  {t("rows.metric")}
                </th>
                {[operational.a, operational.b].map((name, i) => (
                  <th
                    key={`${name}-${i}`}
                    className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400"
                  >
                    {VALUE_LABEL[name] ?? name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {rows.map((row) => (
                <tr key={row.key} data-testid={`compare-row-${row.key}`}>
                  <td className="px-4 py-3 text-aurion-caption text-navy-500">{row.label}</td>
                  <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-800">
                    {row.value(operational.a_rollup)}
                  </td>
                  <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-800">
                    {row.value(operational.b_rollup)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {!loading && !qualityHidden && quality && (
        <>
          <div className="mt-4 overflow-x-auto rounded-aurion-md border border-hairline bg-white">
            <table className="min-w-full" data-testid="quality-table">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80">
                  {(["provider", "scored", "overall", "accuracy", "citation", "compliance", "hallucinations"] as const).map(
                    (col) => (
                      <th
                        key={col}
                        className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400"
                      >
                        {t(`quality.${col}`)}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {quality.providers.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-5 text-center text-aurion-callout text-navy-500">
                      {t("quality.empty")}
                    </td>
                  </tr>
                ) : (
                  quality.providers.map((q) => (
                    <tr key={q.provider_name} data-testid={`quality-row-${q.provider_name}`}>
                      <td className="px-4 py-3 text-aurion-callout font-medium text-navy-800">
                        {VALUE_LABEL[q.provider_name] ?? q.provider_name}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {format.number(q.scored_sessions)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {score(q.avg_overall)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {score(q.avg_transcript_accuracy)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {score(q.avg_citation_correctness)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {score(q.avg_descriptive_mode_compliance)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                        {score(q.avg_hallucination_count)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-aurion-caption text-navy-400">{t("quality.caption")}</p>
        </>
      )}
    </section>
  );
}
