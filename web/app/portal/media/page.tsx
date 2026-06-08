"use client";

/**
 * /portal/media — admin "Captured Media" page (#338).
 *
 * Windowed media-retention review surface. Lists every session whose raw
 * media (unmasked patient audio + masked clips) is still inside the
 * retention window, with a per-row download affordance.
 *
 * PHI posture:
 *   - The list carries NO patient identifier — only physician name, session
 *     timing, visit/context/encounter metadata, state, media availability,
 *     and a retention countdown. The backend enforces this; the page never
 *     asks for more.
 *   - Raw audio is unmasked patient speech, so the whole surface is double-
 *     gated: a role check AND the media_review_retention_enabled flag. When
 *     the flag is off the backend 403s the list and the page shows a clear
 *     "not enabled" state rather than a broken table.
 *
 * Role split (mirrors the backend require_role gates):
 *   - ADMIN / EVAL_TEAM      — view the list AND download media.
 *   - COMPLIANCE_OFFICER     — view the list only (download actions hidden;
 *                               the backend also 403s their download call).
 *   - CLINICIAN              — no nav entry, no access.
 */

import {
  AudioLines,
  Download,
  Film,
  Lock,
  RefreshCw,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import EmptyPanelState from "@/components/portal/EmptyPanelState";
import PageHeader from "@/components/portal/PageHeader";
import { getCapturedMedia, getMe, getMediaDownloadUrls, humanizeError} from "@/lib/api";
import type { CapturedMediaItem, UserRole } from "@/types";

/** States the backend stateBadge map knows about — anything else renders raw. */
const KNOWN_STATES = new Set([
  "AWAITING_REVIEW",
  "PROCESSING_STAGE2",
  "REVIEW_COMPLETE",
  "EXPORTED",
]);

const KNOWN_ENCOUNTER_TYPES = new Set([
  "doctor_patient",
  "doctor_patient_allied",
  "doctor_patient_transitory",
]);

/** Open a presigned URL so the browser downloads it. Presigned S3 GETs
 *  expire after the backend TTL; we never persist them. */
function triggerDownload(url: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.target = "_blank";
  a.rel = "noopener noreferrer";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

export default function CapturedMediaPage() {
  const t = useTranslations("CapturedMedia");

  const [items, setItems] = useState<CapturedMediaItem[]>([]);
  const [retentionDays, setRetentionDays] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notEnabled, setNotEnabled] = useState(false);
  const [role, setRole] = useState<UserRole | null>(null);

  // Per-row download state: the session id currently downloading and the
  // kind, plus a per-row error keyed by session id.
  const [busy, setBusy] = useState<{ id: string; kind: "audio" | "clips" } | null>(
    null,
  );
  const [rowError, setRowError] = useState<Record<string, string>>({});

  const canDownload = role === "ADMIN" || role === "EVAL_TEAM";

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotEnabled(false);
    try {
      const data = await getCapturedMedia();
      setItems(data.items);
      setRetentionDays(data.retention_days);
    } catch (e) {
      // A 403 on a role that CAN see this page means the feature flag is
      // off (the nav only shows it to allowed roles). Surface the clear
      // "not enabled" state instead of a raw error.
      if (e instanceof Error && e.message.startsWith("API 403")) {
        setNotEnabled(true);
      } else {
        setError(humanizeError(e, t("loadError")));
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((u) => {
        if (!cancelled) setRole(u.role);
      })
      .catch(() => {
        // Role stays null → download actions hidden (safe default).
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleDownload(item: CapturedMediaItem, kind: "audio" | "clips") {
    setBusy({ id: item.session_id, kind });
    setRowError((prev) => {
      const next = { ...prev };
      delete next[item.session_id];
      return next;
    });
    try {
      const urls = await getMediaDownloadUrls(item.session_id);
      if (kind === "audio") {
        if (urls.audio_url) {
          triggerDownload(urls.audio_url);
        } else {
          setRowError((p) => ({ ...p, [item.session_id]: t("download.noAudio") }));
        }
      } else {
        if (urls.clips.length > 0) {
          urls.clips.forEach((c) => triggerDownload(c.url));
        } else {
          setRowError((p) => ({ ...p, [item.session_id]: t("download.noClips") }));
        }
      }
    } catch {
      setRowError((p) => ({ ...p, [item.session_id]: t("download.error") }));
    } finally {
      setBusy(null);
    }
  }

  const stateLabel = useCallback(
    (state: string) => (KNOWN_STATES.has(state) ? t(`stateBadge.${state}`) : state),
    [t],
  );

  const encounterLabel = useCallback(
    (etype: string) =>
      KNOWN_ENCOUNTER_TYPES.has(etype) ? t(`encounterType.${etype}`) : etype,
    [t],
  );

  const formatDate = useCallback((iso: string) => {
    if (!iso) return "—";
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "—";
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  }, []);

  const formatCountdown = useCallback(
    (iso: string) => {
      if (!iso) return "—";
      const expires = new Date(iso).getTime();
      if (Number.isNaN(expires)) return "—";
      const ms = expires - Date.now();
      if (ms <= 0) return t("expires.expired");
      const days = Math.floor(ms / 86_400_000);
      if (days >= 1) return t("expires.inDays", { count: days });
      const hours = Math.max(1, Math.ceil(ms / 3_600_000));
      return t("expires.inHours", { count: hours });
    },
    [t],
  );

  const colSpan = canDownload ? 8 : 7;

  const headerNote = useMemo(() => {
    if (retentionDays === null) return undefined;
    return t("retentionNote", { days: retentionDays });
  }, [retentionDays, t]);

  return (
    <div className="aurion-page-padded aurion-container" data-testid="captured-media-page">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={headerNote ?? t("subtitle")}
        actions={
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void load()}
            disabled={loading}
          >
            <span className="inline-flex items-center gap-1.5">
              <RefreshCw className={"h-4 w-4 " + (loading ? "animate-spin" : "")} />
              {t("refresh")}
            </span>
          </Button>
        }
      />

      {!canDownload && role === "COMPLIANCE_OFFICER" && (
        <div
          className="mb-4 flex items-start gap-2 rounded-aurion-md border border-navy-100 bg-canvas px-4 py-3 text-aurion-caption text-navy-500"
          role="note"
        >
          <Lock className="h-4 w-4 shrink-0 mt-0.5 text-navy-400" />
          <span>{t("viewOnly")}</span>
        </div>
      )}

      {error && (
        <div
          className="mb-4 flex items-start gap-2 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
        >
          <span className="flex-1">{error}</span>
          <button
            onClick={() => setError(null)}
            className="text-red-400 hover:text-red-600 text-xs font-medium"
          >
            {t("dismiss")}
          </button>
        </div>
      )}

      {notEnabled ? (
        <Card>
          <EmptyPanelState
            icon={<Film className="h-5 w-5" />}
            title={t("notEnabledTitle")}
            hint={t("notEnabledHint")}
          />
        </Card>
      ) : (
        <div className="overflow-hidden rounded-aurion-lg border border-hairline bg-white shadow-card">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-hairline bg-canvas">
                  <th className="px-4 py-3 text-left aurion-micro text-navy-400">{t("columns.physician")}</th>
                  <th className="px-4 py-3 text-left aurion-micro text-navy-400">{t("columns.date")}</th>
                  <th className="px-4 py-3 text-left aurion-micro text-navy-400">{t("columns.visit")}</th>
                  <th className="px-4 py-3 text-left aurion-micro text-navy-400">{t("columns.encounter")}</th>
                  <th className="px-4 py-3 text-left aurion-micro text-navy-400">{t("columns.state")}</th>
                  <th className="px-4 py-3 text-left aurion-micro text-navy-400">{t("columns.media")}</th>
                  <th className="px-4 py-3 text-left aurion-micro text-navy-400">{t("columns.expires")}</th>
                  {canDownload && (
                    <th className="px-4 py-3 text-right aurion-micro text-navy-400">{t("columns.actions")}</th>
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {loading ? (
                  <tr>
                    <td colSpan={colSpan} className="px-4 py-6">
                      <LoadingSkeleton lines={4} />
                    </td>
                  </tr>
                ) : items.length === 0 ? (
                  <tr>
                    <td colSpan={colSpan} className="px-4 py-12 text-center">
                      <p className="text-aurion-callout text-navy-400">{t("empty")}</p>
                    </td>
                  </tr>
                ) : (
                  items.map((item) => (
                    <tr key={item.session_id} className="transition-colors hover:bg-canvas/60">
                      <td className="whitespace-nowrap px-4 py-3 text-aurion-body font-medium text-navy-800">
                        {item.physician_name}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-aurion-callout text-navy-500">
                        {formatDate(item.started_at)}
                      </td>
                      <td className="px-4 py-3 text-aurion-callout text-navy-600">
                        <div className="flex flex-col">
                          <span>{item.visit_type ?? "—"}</span>
                          {item.context_label && (
                            <span className="text-aurion-caption text-navy-400">
                              {item.context_label}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-aurion-callout text-navy-600">
                        {encounterLabel(item.encounter_type)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3">
                        <Badge variant="neutral" dot>
                          {stateLabel(item.state)}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-aurion-callout">
                        <div className="flex items-center gap-3">
                          {item.has_audio ? (
                            <span className="inline-flex items-center gap-1 text-emerald-600">
                              <AudioLines className="h-3.5 w-3.5" />
                              {t("media.audio")}
                            </span>
                          ) : null}
                          {item.clip_count > 0 ? (
                            <span className="inline-flex items-center gap-1 text-navy-600">
                              <Film className="h-3.5 w-3.5" />
                              {t("media.clips", { count: item.clip_count })}
                            </span>
                          ) : null}
                          {!item.has_audio && item.clip_count === 0 ? (
                            <span className="text-navy-300">{t("media.none")}</span>
                          ) : null}
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-aurion-callout text-navy-500 tabular-nums">
                        {formatCountdown(item.retention_expires_at)}
                      </td>
                      {canDownload && (
                        <td className="whitespace-nowrap px-4 py-3 text-right">
                          <div className="inline-flex flex-col items-end gap-1">
                            <div className="inline-flex items-center gap-2">
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={
                                  !item.has_audio ||
                                  (busy?.id === item.session_id && busy.kind === "audio")
                                }
                                loading={busy?.id === item.session_id && busy.kind === "audio"}
                                onClick={() => void handleDownload(item, "audio")}
                              >
                                <span className="inline-flex items-center gap-1.5">
                                  <Download className="h-3.5 w-3.5" />
                                  {t("download.audio")}
                                </span>
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                disabled={
                                  item.clip_count === 0 ||
                                  (busy?.id === item.session_id && busy.kind === "clips")
                                }
                                loading={busy?.id === item.session_id && busy.kind === "clips"}
                                onClick={() => void handleDownload(item, "clips")}
                              >
                                <span className="inline-flex items-center gap-1.5">
                                  <Download className="h-3.5 w-3.5" />
                                  {t("download.clips")}
                                </span>
                              </Button>
                            </div>
                            {rowError[item.session_id] && (
                              <span className="text-aurion-caption text-red-600">
                                {rowError[item.session_id]}
                              </span>
                            )}
                          </div>
                        </td>
                      )}
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
