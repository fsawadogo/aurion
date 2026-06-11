"use client";

/**
 * /portal/admin/providers — runtime AI-provider switch. ADMIN or
 * COMPLIANCE_OFFICER.
 *
 * Pins which model provider serves each pipeline stage (note generation,
 * vision, transcription) WITHOUT a redeploy. Backed by
 * GET/PUT/DELETE /api/v1/admin/providers: a PUT writes a runtime override
 * (immediate on the serving task, ~10s fleet convergence via the override
 * poller) and is audited; "Reset to default" clears the override so the
 * stage falls back to its AppConfig baseline.
 *
 * Role gate: the Sidebar link shows for ADMIN + COMPLIANCE_OFFICER, AND the
 * backend endpoints are require_role(ADMIN, COMPLIANCE_OFFICER) — a
 * non-authorized direct visit just sees the GET's load error.
 */

import { AlertTriangle, CheckCircle2, Cpu, RotateCcw } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import ProviderComparePanel from "@/components/portal/ProviderComparePanel";
import ProviderUsagePanel from "@/components/portal/ProviderUsagePanel";
import {
  clearProviderOverride,
  getProviders,
  humanizeError,
  setProviderOverride,
} from "@/lib/api";
import type { ProviderEffective, ProviderType } from "@/types";

// Valid options per provider type — mirrors backend _PROVIDER_ENUMS
// (app/api/v1/admin/config.py) and the config schema enums. Keep in sync;
// an invalid value is rejected by the backend with a 400 anyway.
const PROVIDER_OPTIONS: Record<ProviderType, string[]> = {
  note_generation: ["openai", "anthropic", "gemini"],
  vision: ["openai", "anthropic", "gemini"],
  transcription: ["whisper", "assemblyai"],
};

// Display order: the two LLM stages first, transcription last.
const ORDER: ProviderType[] = ["note_generation", "vision", "transcription"];

// Brand display names — proper nouns, not localized.
const VALUE_LABEL: Record<string, string> = {
  whisper: "Whisper",
  assemblyai: "AssemblyAI",
  openai: "OpenAI",
  anthropic: "Anthropic",
  gemini: "Gemini",
};
function valueLabel(v: string): string {
  return VALUE_LABEL[v] ?? v;
}

export default function ProvidersPage() {
  const t = useTranslations("Providers");

  const [providers, setProviders] = useState<ProviderEffective[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyType, setBusyType] = useState<ProviderType | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);
      try {
        const data = await getProviders();
        if (!cancelled) setProviders(data.providers);
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

  async function applySet(type: ProviderType, value: string) {
    setBusyType(type);
    setError(null);
    setSuccess(null);
    try {
      const data = await setProviderOverride(type, value, "Set via admin portal");
      setProviders(data.providers);
      setSuccess(
        t("setSuccess", { type: t(`types.${type}.name`), value: valueLabel(value) }),
      );
    } catch (e) {
      setError(humanizeError(e, t("setError")));
    } finally {
      setBusyType(null);
    }
  }

  async function applyClear(type: ProviderType) {
    setBusyType(type);
    setError(null);
    setSuccess(null);
    try {
      const data = await clearProviderOverride(type);
      setProviders(data.providers);
      setSuccess(t("clearSuccess", { type: t(`types.${type}.name`) }));
    } catch (e) {
      setError(humanizeError(e, t("clearError")));
    } finally {
      setBusyType(null);
    }
  }

  return (
    <div
      className="aurion-page-padded aurion-container-narrow"
      data-testid="providers-page"
    >
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} description={t("subtitle")} />

      {error && (
        <div
          className="mb-4 flex items-start gap-2 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          <AlertTriangle className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{error}</span>
        </div>
      )}

      {success && (
        <div
          className="mb-4 flex items-start gap-2 rounded-aurion-md border border-green-200 bg-green-50 px-4 py-3 text-aurion-callout text-green-800"
          role="status"
        >
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
          <span>{success}</span>
        </div>
      )}

      {loading || !providers ? (
        <Card>
          <LoadingSkeleton lines={6} />
        </Card>
      ) : (
        <div className="space-y-4">
          {ORDER.map((type) => {
            const row = providers.find((p) => p.provider_type === type);
            if (!row) return null;
            const overridden = row.override_value !== null;
            const busy = busyType === type;
            return (
              <div key={type} data-testid={`provider-row-${type}`}>
                <Card>
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <h2 className="text-aurion-body font-semibold text-navy-800">
                      {t(`types.${type}.name`)}
                    </h2>
                    <p className="mt-1 text-aurion-caption text-navy-500">
                      {t(`types.${type}.description`)}
                    </p>
                  </div>
                  <Cpu className="h-5 w-5 shrink-0 text-gold-600" aria-hidden="true" />
                </div>

                <div className="mt-4 flex flex-wrap gap-2" role="group" aria-label={t(`types.${type}.name`)}>
                  {PROVIDER_OPTIONS[type].map((opt) => {
                    const active = row.effective_value === opt;
                    return (
                      <button
                        key={opt}
                        type="button"
                        disabled={busy || active}
                        onClick={() => void applySet(type, opt)}
                        aria-pressed={active}
                        data-testid={`provider-${type}-option-${opt}`}
                        className={
                          "rounded-aurion-md border px-3 py-1.5 text-sm font-medium transition-colors duration-short ease-aurion " +
                          "focus:outline-none focus:ring-2 focus:ring-gold-300/40 disabled:cursor-default " +
                          (active
                            ? "border-gold-500 bg-gold-500 text-white"
                            : "border-navy-200 text-navy-700 hover:bg-navy-50 disabled:opacity-50")
                        }
                      >
                        {valueLabel(opt)}
                      </button>
                    );
                  })}
                </div>

                <div className="mt-3 flex items-center justify-between gap-3">
                  <p className="text-aurion-caption text-navy-500">
                    {overridden
                      ? t("overrideActive", { baseline: valueLabel(row.appconfig_value) })
                      : t("usingDefault", { baseline: valueLabel(row.appconfig_value) })}
                  </p>
                  {overridden && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={busy}
                      onClick={() => void applyClear(type)}
                    >
                      <RotateCcw className="h-3.5 w-3.5 mr-1" />
                      {t("resetToDefault")}
                    </Button>
                  )}
                </div>
                </Card>
              </div>
            );
          })}
        </div>
      )}

      {/* Usage & cost rollup (#73) — same role gate as the switch above;
          fetches independently so a usage hiccup never blocks switching. */}
      <ProviderUsagePanel />

      {/* A-B compare (#73/#74) — operational + eval-quality side-by-side. */}
      <ProviderComparePanel />
    </div>
  );
}
