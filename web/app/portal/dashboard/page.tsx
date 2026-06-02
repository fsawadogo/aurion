"use client";

import { AlertTriangle, ArrowRight, BadgeCheck, Clock, FileText, LayoutGrid, RefreshCw } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import PageHeader from "@/components/portal/PageHeader";
import { listMySessions, listMyCustomTemplates } from "@/lib/portal-api";
import type { CustomTemplate, Session, SessionState } from "@/types";

/**
 * /portal/dashboard — overview tile for the clinician portal.
 *
 * Four headline tiles + a short list of sessions awaiting review and
 * sessions whose Stage 2 visual enrichment is currently running.
 * Clicking any of those drops the physician directly into the
 * review pane.
 *
 * Counts are derived client-side from the full sessions list since
 * the pilot scale (<100 sessions per clinician) makes per-stat
 * endpoints overkill. PR-F+ can swap in a /me/dashboard rollup
 * endpoint if the list ever gets uncomfortable.
 */

const REVIEW_STATES: ReadonlySet<SessionState> = new Set<SessionState>([
  "AWAITING_REVIEW",
]);

const STAGE2_STATES: ReadonlySet<SessionState> = new Set<SessionState>([
  "PROCESSING_STAGE2",
]);

const ANY_PROCESSING: ReadonlySet<SessionState> = new Set<SessionState>([
  "PROCESSING_STAGE1",
  "PROCESSING_STAGE2",
]);

export default function PortalDashboardPage() {
  const t = useTranslations("Dashboard");
  const [sessions, setSessions] = useState<Session[]>([]);
  const [templates, setTemplates] = useState<CustomTemplate[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [ss, ts] = await Promise.all([
        listMySessions(),
        listMyCustomTemplates(),
      ]);
      ss.sort((a, b) => b.created_at.localeCompare(a.created_at));
      setSessions(ss);
      setTemplates(ts);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load dashboard.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const stats = useMemo(() => deriveStats(sessions), [sessions]);
  const awaitingReview = useMemo(
    () => sessions.filter((s) => REVIEW_STATES.has(s.state)).slice(0, 5),
    [sessions],
  );
  const inProgress = useMemo(
    () => sessions.filter((s) => ANY_PROCESSING.has(s.state)).slice(0, 5),
    [sessions],
  );

  return (
    <div className="aurion-page-padded aurion-container">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("subtitle")}
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            {t("refresh")}
          </Button>
        }
      />

      {error && !loading && (
        <div className="mb-4 rounded-aurion-md bg-red-50 border border-red-200 px-4 py-3 text-aurion-callout text-red-700">
          {error}
        </div>
      )}

      {/* ── Headline tiles — staggered slide-up on first paint. ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6 aurion-stagger">
        <StatTile
          icon={<Clock className="h-5 w-5 text-amber-600" />}
          label={t("stats.awaitingReview")}
          value={stats.awaitingReview}
          href="/portal/notes"
          loading={loading}
        />
        <StatTile
          icon={<RefreshCw className="h-5 w-5 text-navy-500" />}
          label={t("stats.inProgress")}
          value={stats.inProgress}
          href="/portal/notes"
          loading={loading}
        />
        <StatTile
          icon={<BadgeCheck className="h-5 w-5 text-emerald-600" />}
          label={t("stats.approvedThisWeek")}
          value={stats.approvedThisWeek}
          href="/portal/notes"
          loading={loading}
        />
        <StatTile
          icon={<LayoutGrid className="h-5 w-5 text-gold-600" />}
          label={t("stats.customTemplates")}
          value={templates.length}
          href="/portal/templates"
          loading={loading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-navy-700">
            <FileText className="h-4 w-4 text-amber-500" />
            {t("panels.awaitingYourReview")}
          </div>
          {loading ? (
            <LoadingSkeleton lines={4} />
          ) : awaitingReview.length === 0 ? (
            <p className="text-sm text-gray-500 italic">
              {t("panels.noSessionsWaiting")}
            </p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {awaitingReview.map((s) => (
                <SessionRow key={s.id} session={s} />
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-navy-700">
            <RefreshCw className="h-4 w-4 text-navy-500" />
            {t("panels.visualEnrichmentRunning")}
          </div>
          {loading ? (
            <LoadingSkeleton lines={4} />
          ) : inProgress.length === 0 ? (
            <p className="text-sm text-gray-500 italic">
              {t("panels.nothingProcessing")}
            </p>
          ) : (
            <ul className="divide-y divide-gray-100">
              {inProgress.map((s) => (
                <SessionRow key={s.id} session={s} processing />
              ))}
            </ul>
          )}
        </Card>
      </div>

      {sessions.length > 0 && stats.failed > 0 && (
        <div className="mt-4 flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span>
            {/* `failedBanner` uses ICU pluralization (one / other),
                so the translator picks the right form automatically
                for both EN and FR. */}
            {t("failedBanner", { count: stats.failed })}
          </span>
          <Link
            href="/portal/notes"
            className="ml-auto inline-flex items-center text-xs font-medium underline"
          >
            {t("seeList")}
          </Link>
        </div>
      )}
    </div>
  );
}

function StatTile({
  icon,
  label,
  value,
  href,
  loading,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  href: string;
  loading: boolean;
}) {
  return (
    <Link
      href={href}
      className="block rounded-aurion-lg border border-hairline bg-surface px-4 py-3.5 shadow-card transition-all duration-aurion ease-aurion hover:shadow-card-hover hover:border-gold-300 hover:-translate-y-px"
    >
      <div className="flex items-start justify-between gap-2">
        <span className="text-navy-300 transition-colors duration-short group-hover:text-gold-500">
          {icon}
        </span>
        <span className="aurion-display text-navy-800 tabular-nums">
          {loading ? "…" : value}
        </span>
      </div>
      <p className="mt-2 aurion-micro">{label}</p>
    </Link>
  );
}

function SessionRow({
  session,
  processing = false,
}: {
  session: Session;
  processing?: boolean;
}) {
  return (
    <li className="py-2.5">
      <Link
        href={`/portal/notes/${session.id}`}
        className="flex items-center gap-3 hover:bg-gray-50 -mx-2 px-2 py-1 rounded-md transition-colors"
      >
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-navy-800 truncate">
            {humanSpecialty(session.specialty)}
          </p>
          <p className="text-xs text-gray-500 mt-0.5">
            {formatRelative(session.created_at)} ·{" "}
            <span className="font-mono text-[10px]">
              {session.id.slice(0, 8)}
            </span>
          </p>
        </div>
        {processing ? (
          <Badge variant="info" dot>
            {session.state === "PROCESSING_STAGE2" ? "Stage 2" : "Stage 1"}
          </Badge>
        ) : (
          <Badge variant="warning" dot>Review</Badge>
        )}
        <ArrowRight className="h-4 w-4 text-gray-300 shrink-0" />
      </Link>
    </li>
  );
}

/* ── Stats derivation ───────────────────────────────────────────────────── */

interface Stats {
  awaitingReview: number;
  inProgress: number;
  approvedThisWeek: number;
  failed: number;
}

function deriveStats(list: Session[]): Stats {
  const weekAgo = Date.now() - 7 * 24 * 60 * 60 * 1000;
  let awaitingReview = 0;
  let inProgress = 0;
  let approvedThisWeek = 0;
  let failed = 0;
  for (const s of list) {
    if (REVIEW_STATES.has(s.state)) awaitingReview += 1;
    if (STAGE2_STATES.has(s.state) || s.state === "PROCESSING_STAGE1")
      inProgress += 1;
    if (
      (s.state === "REVIEW_COMPLETE" || s.state === "EXPORTED") &&
      new Date(s.updated_at).getTime() >= weekAgo
    )
      approvedThisWeek += 1;
    if (s.state === "FAILED") failed += 1;
  }
  return { awaitingReview, inProgress, approvedThisWeek, failed };
}

function humanSpecialty(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function formatRelative(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const m = Math.round((Date.now() - d.getTime()) / 60_000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hr ago`;
  const days = Math.round(h / 24);
  if (days < 7) return `${days}d ago`;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
}
