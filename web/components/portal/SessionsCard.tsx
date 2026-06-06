"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  listSessions,
  revokeAllSessions,
  revokeSession,
  type ActiveSession,
} from "@/lib/portal-api";

/**
 * Active sessions card on /portal/profile/account (#163).
 *
 * Lists every still-active refresh-token row for the calling clinician.
 * Each row shows:
 *   * device hint (e.g. "Safari · macOS")
 *   * ip class    ("local" / "private" / "internet")
 *   * created     (raw ISO trimmed)
 *   * last used   (raw ISO trimmed)
 *   * a "Revoke" button per row
 *   * the current-session row carries an extra badge AND is non-
 *     revokable from the per-row button (clinician would otherwise
 *     sign themselves out mid-action)
 *
 * The "Sign out everywhere else" CTA at the bottom revokes every row
 * except the current one in one shot.
 */
export default function SessionsCard() {
  const t = useTranslations("Account.sessions");
  const [sessions, setSessions] = useState<ActiveSession[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const list = await listSessions();
      setSessions(list);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("loadError"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleRevoke(id: string) {
    setBusy(id);
    setError(null);
    try {
      await revokeSession(id);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("revokeError"));
    } finally {
      setBusy(null);
    }
  }

  async function handleRevokeAll() {
    setBusy("__all__");
    setError(null);
    try {
      await revokeAllSessions();
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("revokeAllError"));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title={t("title")}>
      <p className="text-sm text-gray-600 mb-3">{t("description")}</p>

      {loading ? (
        <LoadingSkeleton lines={3} />
      ) : error && !sessions ? (
        <div className="space-y-2">
          <p className="text-sm text-red-600">{error}</p>
          <Button variant="secondary" onClick={() => void refresh()}>
            {t("retry")}
          </Button>
        </div>
      ) : sessions && sessions.length > 0 ? (
        <div className="space-y-3">
          {error && (
            <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-xs text-red-700">
              {error}
            </div>
          )}
          <ul className="divide-y divide-gray-100">
            {sessions.map((s) => (
              <SessionRow
                key={s.id}
                session={s}
                busy={busy === s.id}
                onRevoke={() => void handleRevoke(s.id)}
              />
            ))}
          </ul>
          <div className="pt-1">
            <Button
              variant="secondary"
              onClick={() => void handleRevokeAll()}
              disabled={busy !== null || sessions.length <= 1}
            >
              {busy === "__all__" ? t("revokingAll") : t("revokeAllCta")}
            </Button>
          </div>
        </div>
      ) : (
        <p className="text-sm text-gray-500">{t("empty")}</p>
      )}
    </Card>
  );
}

function SessionRow({
  session,
  busy,
  onRevoke,
}: {
  session: ActiveSession;
  busy: boolean;
  onRevoke: () => void;
}) {
  const t = useTranslations("Account.sessions");
  return (
    <li className="flex items-center justify-between gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium text-navy-800">
            {session.device_hint}
          </span>
          {session.is_current && (
            <span className="inline-flex items-center rounded-full bg-gold-50 border border-gold-200 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-navy-900">
              {t("currentBadge")}
            </span>
          )}
        </div>
        <div className="mt-0.5 text-xs text-gray-500">
          {t("rowMeta", {
            ip: t(`ipClass.${session.ip_class}` as
              | "ipClass.local"
              | "ipClass.private"
              | "ipClass.internet"
              | "ipClass.unknown"),
            lastUsed: session.last_used_at
              ? formatStamp(session.last_used_at)
              : t("neverUsed"),
          })}
        </div>
      </div>
      <Button
        variant="secondary"
        onClick={onRevoke}
        disabled={busy || session.is_current}
        aria-label={t("revokeRowAria", { device: session.device_hint })}
      >
        {busy ? t("revoking") : t("revokeCta")}
      </Button>
    </li>
  );
}

/** ISO timestamp → short local date+time. Falls back to the raw
 * string on parse failure so we never throw. */
function formatStamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}
