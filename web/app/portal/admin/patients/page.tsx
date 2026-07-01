"use client";

/**
 * `/portal/admin/patients` — landing / search for the cross-clinician
 * Patient Chart (#604). An elevated reviewer (CLINICAL_ADMIN/ADMIN) types a
 * patient identifier and opens the aggregated chart at
 * `/portal/admin/patients/[identifier]`.
 *
 * The chart itself is role + flag gated on the backend; this page mirrors the
 * flag with `getPortalFeatureFlags().cross_clinician_chart_enabled` so the
 * search box only appears when the feature is live, and shows a "not enabled"
 * state otherwise. The identifier is never logged; navigation URL-encodes it.
 */

import { Search, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import EmptyPanelState from "@/components/portal/EmptyPanelState";
import PageHeader from "@/components/portal/PageHeader";
import { getPortalFeatureFlags } from "@/lib/portal-api";

const INPUT_CLS =
  "w-full rounded-aurion-md border border-hairline bg-white px-3 py-2 text-aurion-callout text-navy-800 placeholder:text-navy-300 focus:outline-none focus:ring-2 focus:ring-gold-300/40";

export default function AdminPatientsSearchPage() {
  const t = useTranslations("AdminPatientChart");
  const [enabled, setEnabled] = useState<boolean | null>(null);
  const [value, setValue] = useState("");

  useEffect(() => {
    let cancelled = false;
    getPortalFeatureFlags()
      .then((f) => {
        if (!cancelled) setEnabled(f.cross_clinician_chart_enabled);
      })
      .catch(() => {
        if (!cancelled) setEnabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const submit = useCallback(() => {
    const id = value.trim();
    if (!id) return;
    // Plain assignment (not next/router) so the dynamic identifier segment
    // resolves under static export — same pattern as the note deep links.
    window.location.href = `/portal/admin/patients/${encodeURIComponent(id)}`;
  }, [value]);

  return (
    <div className="aurion-page-padded aurion-container">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("searchTitle")}
        description={t("searchSubtitle")}
      />

      {enabled === null ? (
        <Card>
          <LoadingSkeleton lines={3} />
        </Card>
      ) : !enabled ? (
        <Card>
          <div data-testid="patient-chart-search-disabled">
            <EmptyPanelState
              icon={<ShieldCheck className="h-5 w-5" aria-hidden="true" />}
              title={t("notEnabledTitle")}
              hint={t("notEnabledBody")}
            />
          </div>
        </Card>
      ) : (
        <Card>
          <form
            className="flex flex-col gap-3 sm:flex-row sm:items-end"
            onSubmit={(ev) => {
              ev.preventDefault();
              submit();
            }}
          >
            <label className="flex-1">
              <span className="mb-1 block text-xs font-semibold text-navy-600">
                {t("searchLabel")}
              </span>
              <input
                className={INPUT_CLS}
                value={value}
                onChange={(ev) => setValue(ev.target.value)}
                placeholder={t("searchPlaceholder")}
                data-testid="patient-chart-search-input"
                autoComplete="off"
                spellCheck={false}
              />
            </label>
            <Button
              type="submit"
              variant="primary"
              disabled={!value.trim()}
              data-testid="patient-chart-search-submit"
            >
              <span className="inline-flex items-center gap-1.5">
                <Search className="h-4 w-4" />
                {t("searchAction")}
              </span>
            </Button>
          </form>
          <p className="mt-3 text-xs text-gray-500">{t("searchHint")}</p>
        </Card>
      )}
    </div>
  );
}
