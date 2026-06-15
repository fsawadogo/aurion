"use client";

/**
 * Compact "Usage Metrics" snapshot for the AI-providers bento (Stitch).
 *
 * Sits in the right column beside Pipeline Stage Routing, mirroring the
 * export's narrow usage panel: four headline totals (calls, avg latency,
 * success rate, est. cost) at a glance over all recorded usage. The
 * detailed range-selectable per-provider breakdown lives in
 * ProviderUsagePanel below (rendered with hideTotals so these numbers
 * aren't duplicated).
 *
 * Reuses the Providers.usage i18n namespace (title/subtitle/stats/loadError)
 * — no new strings, EN+FR already at parity.
 */

import { BarChart3 } from "lucide-react";
import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getProviderUsage, humanizeError } from "@/lib/api";
import type { ProviderUsageResponse } from "@/types";

function pct(fraction: number): string {
  return `${(fraction * 100).toFixed(1)}%`;
}
function latency(ms: number): string {
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} s` : `${Math.round(ms)} ms`;
}
function cost(usd: number): string {
  return usd === 0 ? "—" : `$${usd.toFixed(usd < 1 ? 4 : 2)}`;
}

export default function ProviderUsageSnapshot() {
  const t = useTranslations("Providers.usage");
  const format = useFormatter();

  const [data, setData] = useState<ProviderUsageResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const res = await getProviderUsage();
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
  }, [t]);

  const totals = data?.totals;

  return (
    <Card data-testid="provider-usage-snapshot">
      <h2 className="flex items-center gap-2 text-aurion-body font-semibold text-navy-800">
        <BarChart3 className="h-4 w-4 text-gold-600" aria-hidden="true" />
        {t("title")}
      </h2>
      <p className="mt-1 text-aurion-caption text-navy-500">{t("subtitle")}</p>

      {loading ? (
        <div className="mt-4">
          <LoadingSkeleton lines={4} />
        </div>
      ) : error ? (
        <p className="mt-4 text-aurion-callout text-red-600" role="alert">
          {error}
        </p>
      ) : totals ? (
        <dl className="mt-4 space-y-2.5">
          {(
            [
              ["calls", format.number(totals.call_count)],
              ["avgLatency", latency(totals.avg_latency_ms)],
              [
                "successRate",
                pct(totals.call_count ? totals.success_count / totals.call_count : 0),
              ],
              ["estCost", cost(totals.total_cost_usd)],
            ] as const
          ).map(([key, value]) => (
            <div
              key={key}
              className="flex items-center justify-between gap-2 border-b border-hairline pb-2.5 last:border-0 last:pb-0"
            >
              <dt className="text-aurion-caption text-navy-500">{t(`stats.${key}`)}</dt>
              <dd
                className="text-aurion-body font-semibold tabular-nums text-navy-800"
                data-testid={`snapshot-stat-${key}`}
              >
                {value}
              </dd>
            </div>
          ))}
        </dl>
      ) : null}
    </Card>
  );
}
