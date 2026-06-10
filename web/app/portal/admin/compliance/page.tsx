"use client";

/**
 * /portal/admin/compliance — signed compliance reports (#77). ADMIN +
 * COMPLIANCE_OFFICER (mirrors the backend gate).
 *
 * Generate / list / download the persisted, sha256-signed CSV snapshots:
 * audit (the full trail), masking (the Law-25 "every frame was masked"
 * proof), retention (purge + retained-media-access lifecycle). The
 * download carries the hash in X-Aurion-Sha256 and the row shows its
 * prefix, so an institution can verify the file it received.
 */

import { Download, FileCheck2, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import {
  downloadComplianceReport,
  generateComplianceReport,
  humanizeError,
  listComplianceReports,
} from "@/lib/api";
import { formatRelative } from "@/lib/session-format";
import type { ComplianceReportMetadata, ComplianceReportType } from "@/types";

const TYPES: ComplianceReportType[] = ["audit", "masking", "retention"];

function bytes(n: number): string {
  if (n >= 1_048_576) return `${(n / 1_048_576).toFixed(1)} MB`;
  if (n >= 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${n} B`;
}

export default function AdminCompliancePage() {
  const t = useTranslations("AdminCompliance");
  const format = useFormatter();

  const [reports, setReports] = useState<ComplianceReportMetadata[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState<ComplianceReportType | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listComplianceReports({ limit: 50 });
      setReports(res.items);
    } catch (e) {
      setError(humanizeError(e, t("loadError")));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onGenerate(type: ComplianceReportType) {
    setGenerating(type);
    setError(null);
    setSuccess(null);
    try {
      const meta = await generateComplianceReport(type);
      setSuccess(
        t("generateSuccess", {
          type: t(`types.${type}`),
          sha: meta.sha256.slice(0, 12),
        }),
      );
      await load();
    } catch (e) {
      setError(humanizeError(e, t("generateError")));
    } finally {
      setGenerating(null);
    }
  }

  async function onDownload(report: ComplianceReportMetadata) {
    setDownloadingId(report.id);
    setError(null);
    try {
      const blob = await downloadComplianceReport(report.id);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aurion_${report.report_type}_${report.id}.csv`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(humanizeError(e, t("downloadError")));
    } finally {
      setDownloadingId(null);
    }
  }

  return (
    <div className="aurion-page-padded aurion-container-narrow" data-testid="compliance-page">
      <PageHeader eyebrow={t("eyebrow")} title={t("title")} description={t("description")} />

      <div className="mb-4 flex flex-wrap gap-2">
        {TYPES.map((type) => (
          <Button
            key={type}
            variant="secondary"
            size="sm"
            loading={generating === type}
            disabled={generating !== null}
            onClick={() => void onGenerate(type)}
            data-testid={`generate-${type}`}
          >
            {generating === type ? (
              <Loader2 className="h-4 w-4 mr-1 animate-spin" />
            ) : (
              <FileCheck2 className="h-4 w-4 mr-1" />
            )}
            {t("generate", { type: t(`types.${type}`) })}
          </Button>
        ))}
      </div>

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          {error}
        </div>
      )}
      {success && (
        <div
          className="mb-4 rounded-aurion-md border border-green-200 bg-green-50 px-4 py-3 text-aurion-callout text-green-800"
          role="status"
        >
          {success}
        </div>
      )}

      <Card>
        {loading || !reports ? (
          <LoadingSkeleton lines={6} />
        ) : reports.length === 0 ? (
          <p className="py-8 text-center text-aurion-callout text-navy-500">
            {t("empty")}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80">
                  {(["type", "generated", "window", "size", "sha", "actions"] as const).map(
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
                {reports.map((r) => (
                  <tr key={r.id} data-testid={`report-row-${r.id}`}>
                    <td className="px-4 py-3">
                      <Badge variant="info">{t(`types.${r.report_type}`)}</Badge>
                    </td>
                    <td className="px-4 py-3 text-aurion-callout text-navy-700">
                      {formatRelative(r.generated_at)}
                    </td>
                    <td className="px-4 py-3 text-aurion-caption text-navy-500">
                      {r.since || r.until
                        ? `${r.since ? format.dateTime(new Date(r.since), { dateStyle: "medium" }) : "…"} → ${r.until ? format.dateTime(new Date(r.until), { dateStyle: "medium" }) : "…"}`
                        : t("fullHistory")}
                    </td>
                    <td className="px-4 py-3 text-aurion-callout tabular-nums text-navy-700">
                      {bytes(r.byte_size)}
                    </td>
                    <td className="px-4 py-3">
                      <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] tracking-tight text-gray-500">
                        {r.sha256.slice(0, 12)}…
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <Button
                        variant="ghost"
                        size="sm"
                        loading={downloadingId === r.id}
                        disabled={downloadingId !== null}
                        onClick={() => void onDownload(r)}
                        data-testid={`download-${r.id}`}
                      >
                        <Download className="h-3.5 w-3.5 mr-1" />
                        {t("download")}
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <p className="mt-2 text-aurion-caption text-navy-400">{t("footnote")}</p>
    </div>
  );
}
