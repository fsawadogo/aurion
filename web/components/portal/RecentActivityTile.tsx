"use client";

import { Activity } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";
import Link from "next/link";

import { getMyAuditLog } from "@/lib/portal-api";
import type { AuditEvent, PaginatedResponse } from "@/types";

/**
 * Dashboard "Recent activity" tile (#162, AC-7).
 *
 * Compact link card that fetches the caller's audit log, counts events
 * in the trailing 7 days, and links to `/portal/audit` for the full
 * surface.
 *
 * Why a tile and not a server-rendered count: the dashboard already
 * runs as a client component (per its `"use client"` directive at the
 * top of `app/portal/dashboard/page.tsx`), so a separate server fetch
 * would just complicate hydration. We trade one extra round-trip on
 * dashboard load for a clean isolation boundary.
 *
 * We deliberately fetch `page_size=200` and count client-side rather
 * than asking the backend to bucket events for us — pilot clinicians
 * rarely have more than a few dozen events per week, and the existing
 * /me/audit endpoint already does the actor_id scope. A dedicated
 * `/me/audit/counts` endpoint is a follow-up if the page size ever
 * stops covering the window.
 */
export default function RecentActivityTile() {
  const t = useTranslations("MyActivity");
  const [recentCount, setRecentCount] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = (await getMyAuditLog({
          page_size: 200,
        })) as PaginatedResponse<AuditEvent>;
        const cutoff = Date.now() - 7 * 24 * 60 * 60 * 1000;
        let count = 0;
        for (const ev of data.items ?? []) {
          const ts = new Date(ev.event_timestamp).getTime();
          if (!Number.isNaN(ts) && ts >= cutoff) count += 1;
        }
        if (!cancelled) setRecentCount(count);
      } catch {
        // Treat fetch failures as "nothing to show" rather than alarming
        // the physician — the tile is a derived dashboard surface, not
        // a transactional control.
        if (!cancelled) setRecentCount(0);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const display = loading
    ? "…"
    : recentCount !== null
      ? String(recentCount)
      : "0";

  const hint = loading
    ? ""
    : recentCount && recentCount > 0
      ? t("tileHint", { count: recentCount })
      : t("tileEmpty");

  return (
    <Link
      href="/portal/audit"
      className="block rounded-aurion-lg border border-hairline bg-surface px-4 py-3.5 shadow-card transition-all duration-aurion ease-aurion hover:shadow-card-hover hover:border-gold-300 hover:-translate-y-px"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-navy-300 transition-colors duration-short group-hover:text-gold-500">
          <Activity className="h-5 w-5 text-navy-500" />
        </span>
        <span className="aurion-display text-navy-800 tabular-nums">
          {display}
        </span>
      </div>
      <p className="mt-2 aurion-micro">{t("tileLabel")}</p>
      {hint && (
        <p className="mt-0.5 truncate text-[11px] text-aurion-tertiary">
          {hint}
        </p>
      )}
    </Link>
  );
}
