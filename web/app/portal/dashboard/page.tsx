"use client";

import { AlertTriangle, ArrowRight, BadgeCheck, ClipboardList, Clock, FileText, History, Inbox, LayoutGrid, RefreshCw, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import ActivityFeed from "@/components/portal/ActivityFeed";
import EmptyPanelState from "@/components/portal/EmptyPanelState";
import PageHeader from "@/components/portal/PageHeader";
import QuickActions from "@/components/portal/QuickActions";
import { listMySessions, listMyCustomTemplates } from "@/lib/portal-api";
import {
  badgeVariantFor,
  formatRelative,
  humanSpecialty,
} from "@/lib/session-format";
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
  // Recent sessions strip — most recent 6 across all states except
  // PURGED (those rows exist for audit but the physician can't view
  // them anymore). Provides at-a-glance "what I've been working on"
  // without scrolling to the inbox.
  const recentSessions = useMemo(
    () => sessions
      .filter((s) => s.state !== "PURGED")
      .slice(0, 6),
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

      {/* ── Quick actions — task-oriented shortcuts above the KPI
            tiles. Patient-identifier lookup is the highest-value
            entry; bulk export + new template ride along. ── */}
      <QuickActions />

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
            <EmptyPanelState
              icon={<Inbox className="h-7 w-7" />}
              title={t("panels.noSessionsWaiting")}
              hint={t("panels.noSessionsWaitingHint")}
            />
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
            <EmptyPanelState
              icon={<Sparkles className="h-7 w-7" />}
              title={t("panels.nothingProcessing")}
              hint={t("panels.nothingProcessingHint")}
            />
          ) : (
            <ul className="divide-y divide-gray-100">
              {inProgress.map((s) => (
                <SessionRow key={s.id} session={s} processing />
              ))}
            </ul>
          )}
        </Card>
      </div>

      {/* Live activity feed — polling /me/audit every 30s for
          noteworthy events (Stage 1/2 delivery, approvals, EMR
          write-back results, etc.). Sits between the activity
          panels and the historical recent strip — "what just
          changed" complements "what's pending" and "what I
          touched lately". */}
      <section className="mt-4">
        <ActivityFeed />
      </section>

      {/* Recent sessions strip — physician's working memory. Shows
          the 6 most recent sessions across any state (except PURGED).
          Horizontal scroll on narrow viewports keeps the row dense
          on dashboards opened on smaller laptops. */}
      <RecentStrip
        sessions={recentSessions}
        loading={loading}
      />

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

/* ── Recent sessions strip ──────────────────────────────────────────────── */

/**
 * Horizontal row of the 6 most recent sessions across any state
 * (except PURGED — those don't open).
 *
 * Each card shows: relative time + specialty + identifier (if set) +
 * state badge. Click drops the user into the note review screen.
 *
 * Strip layout: snap-x on a horizontal overflow container so narrow
 * viewports get carousel-style swipe instead of cards squeezing.
 * Each card is min-w-[220px] which means on wide screens 5-6 sit
 * side-by-side; on a 14" laptop the row scrolls.
 *
 * Loading skeleton uses 4 placeholder cards (matches the typical
 * pilot count of recent sessions; over-budgeting the skeleton
 * count would make the row feel too busy on a quiet day).
 */
function RecentStrip({
  sessions,
  loading,
}: {
  sessions: Session[];
  loading: boolean;
}) {
  const t = useTranslations("Dashboard.recent");
  const tState = useTranslations("Dashboard.stateBadge");

  return (
    <section className="mt-6">
      <div className="mb-3 flex items-center gap-2">
        <History className="h-4 w-4 text-aurion-secondary" />
        <h2 className="text-sm font-semibold text-aurion-primary">
          {t("title")}
        </h2>
        <Link
          href="/portal/notes"
          className="ml-auto text-xs font-medium text-gold-600 hover:text-gold-700 transition-colors"
        >
          {t("viewAll")} →
        </Link>
      </div>

      {loading ? (
        <div className="flex gap-3 overflow-hidden">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="min-w-[220px] flex-1 rounded-aurion-md border border-aurion-hairline bg-aurion-card p-4"
            >
              <LoadingSkeleton lines={2} />
            </div>
          ))}
        </div>
      ) : sessions.length === 0 ? (
        <Card>
          <EmptyPanelState
            icon={<ClipboardList className="h-7 w-7" />}
            title={t("noneYet")}
            hint={t("noneYetHint")}
          />
        </Card>
      ) : (
        <div className="-mx-1 flex gap-3 overflow-x-auto snap-x snap-mandatory pb-2 px-1">
          {sessions.map((s) => (
            <RecentCard
              key={s.id}
              session={s}
              stateLabel={tState(s.state)}
            />
          ))}
        </div>
      )}
    </section>
  );
}

function RecentCard({
  session,
  stateLabel,
}: {
  session: Session;
  stateLabel: string;
}) {
  const variant = badgeVariantFor(session.state);
  return (
    <Link
      href={`/portal/notes/${session.id}`}
      className="snap-start min-w-[220px] flex-1 rounded-aurion-md border border-aurion-hairline bg-aurion-card p-3.5 transition-all duration-aurion ease-aurion hover:shadow-card hover:-translate-y-px hover:border-gold-300"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs text-aurion-tertiary">
          {formatRelative(session.created_at)}
        </p>
        <Badge variant={variant} dot>
          {stateLabel}
        </Badge>
      </div>
      <p className="mt-1.5 text-sm font-medium text-aurion-primary truncate">
        {humanSpecialty(session.specialty)}
      </p>
      {session.external_reference_id ? (
        <p className="mt-0.5 font-mono text-[11px] text-gold-700 truncate">
          {session.external_reference_id}
        </p>
      ) : (
        <p className="mt-0.5 font-mono text-[11px] text-aurion-tertiary truncate">
          {session.id.slice(0, 8)}
        </p>
      )}
    </Link>
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

