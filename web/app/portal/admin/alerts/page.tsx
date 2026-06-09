"use client";

/**
 * /portal/admin/alerts — operational alerts (#76). ADMIN +
 * COMPLIANCE_OFFICER (mirrors the backend gate).
 *
 * Lists alerts published by the pipeline trigger sites (Stage failures,
 * masking issues, SLA breaches) with severity chips and an open /
 * acknowledged filter; acknowledging an open alert records who took
 * ownership (idempotent server-side — the first acknowledger is
 * preserved). Delivery sinks (Slack/email) are follow-ups; email is
 * blocked on SES production access (#399).
 */

import { Bell, Check } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import { acknowledgeAlert, humanizeError, listAlerts } from "@/lib/api";
import { formatRelative } from "@/lib/session-format";
import type { AlertSeverity, OperationalAlert } from "@/types";

const FILTERS = ["open", "acknowledged", "all"] as const;
type FilterKey = (typeof FILTERS)[number];

const SEVERITY_BADGE: Record<AlertSeverity, "error" | "warning" | "info"> = {
  critical: "error",
  warning: "warning",
  info: "info",
};

export default function AdminAlertsPage() {
  const t = useTranslations("AdminAlerts");

  const [filter, setFilter] = useState<FilterKey>("open");
  const [alerts, setAlerts] = useState<OperationalAlert[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [ackingId, setAckingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAlerts(
        filter === "all" ? { limit: 100 } : { status: filter, limit: 100 },
      );
      setAlerts(res.items);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [filter, t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onAcknowledge(id: string) {
    setAckingId(id);
    setError(null);
    try {
      const updated = await acknowledgeAlert(id);
      // In the "open" filter the row leaves the list; elsewhere it updates
      // in place.
      setAlerts((xs) =>
        filter === "open"
          ? (xs ?? []).filter((a) => a.id !== id)
          : (xs ?? []).map((a) => (a.id === id ? updated : a)),
      );
    } catch (e) {
      setError(humanizeError(e, t("ackError")));
    } finally {
      setAckingId(null);
    }
  }

  return (
    <div className="aurion-page-padded aurion-container-narrow" data-testid="admin-alerts-page">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} description={t("description")} />

      <div className="mb-4 flex gap-1" role="group" aria-label={t("filterLabel")}>
        {FILTERS.map((f) => {
          const active = filter === f;
          return (
            <button
              key={f}
              type="button"
              disabled={active || loading}
              onClick={() => setFilter(f)}
              aria-pressed={active}
              data-testid={`alerts-filter-${f}`}
              className={
                "rounded-aurion-md border px-2.5 py-1 text-xs font-medium transition-colors duration-short ease-aurion " +
                "focus:outline-none focus:ring-2 focus:ring-gold-300/40 disabled:cursor-default " +
                (active
                  ? "border-navy-700 bg-navy-700 text-white"
                  : "border-navy-200 text-navy-600 hover:bg-navy-50")
              }
            >
              {t(`filters.${f}`)}
            </button>
          );
        })}
      </div>

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          {error}
        </div>
      )}

      <Card>
        {loading || !alerts ? (
          <LoadingSkeleton lines={6} />
        ) : alerts.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-10 text-center">
            <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-green-50 text-green-600">
              <Bell className="h-6 w-6" />
            </div>
            <p className="aurion-callout font-medium text-navy-700">{t("empty")}</p>
          </div>
        ) : (
          <ul className="divide-y divide-hairline">
            {alerts.map((a) => (
              <li
                key={a.id}
                className="flex items-start gap-3 py-3"
                data-testid={`alert-row-${a.id}`}
              >
                <Badge variant={SEVERITY_BADGE[a.severity]} className="mt-0.5 shrink-0">
                  {t(`severity.${a.severity}`)}
                </Badge>
                <div className="flex-1 min-w-0">
                  <p className="text-aurion-callout font-medium text-navy-800">
                    {a.message}
                  </p>
                  <p className="mt-0.5 text-aurion-caption text-navy-500">
                    <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] tracking-tight text-gray-500">
                      {a.alert_type}
                    </code>{" "}
                    · {a.source} · {formatRelative(a.created_at)}
                    {a.acknowledged_at && (
                      <> · {t("acknowledgedAt", { when: formatRelative(a.acknowledged_at) })}</>
                    )}
                  </p>
                </div>
                {a.acknowledged_at === null && (
                  <Button
                    variant="secondary"
                    size="sm"
                    loading={ackingId === a.id}
                    disabled={ackingId !== null}
                    onClick={() => void onAcknowledge(a.id)}
                    data-testid={`ack-${a.id}`}
                  >
                    <Check className="h-3.5 w-3.5 mr-1" />
                    {t("acknowledge")}
                  </Button>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
