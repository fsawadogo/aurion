"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  ArrowRightIcon,
  ClockIcon,
  CheckBadgeIcon,
  ArrowPathIcon,
  ExclamationTriangleIcon,
  Squares2X2Icon,
  DocumentTextIcon,
} from "@heroicons/react/24/outline";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
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
    <div className="p-6 lg:p-8 max-w-6xl mx-auto">
      <div className="mb-6 flex items-end justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-navy-800">Dashboard</h1>
          <p className="mt-1 text-sm text-gray-500">
            Your overview at a glance.
          </p>
        </div>
        <Button variant="secondary" size="sm" onClick={() => void load()}>
          Refresh
        </Button>
      </div>

      {error && !loading && (
        <div className="mb-4 rounded-md bg-red-50 border border-red-200 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}

      {/* ── Headline tiles ── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <StatTile
          icon={<ClockIcon className="h-5 w-5 text-amber-600" />}
          label="Awaiting review"
          value={stats.awaitingReview}
          href="/portal/notes"
          loading={loading}
        />
        <StatTile
          icon={<ArrowPathIcon className="h-5 w-5 text-navy-500" />}
          label="In progress"
          value={stats.inProgress}
          href="/portal/notes"
          loading={loading}
        />
        <StatTile
          icon={<CheckBadgeIcon className="h-5 w-5 text-emerald-600" />}
          label="Approved this week"
          value={stats.approvedThisWeek}
          href="/portal/notes"
          loading={loading}
        />
        <StatTile
          icon={<Squares2X2Icon className="h-5 w-5 text-gold-600" />}
          label="Custom templates"
          value={templates.length}
          href="/portal/templates"
          loading={loading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Card>
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-navy-700">
            <DocumentTextIcon className="h-4 w-4 text-amber-500" />
            Awaiting your review
          </div>
          {loading ? (
            <LoadingSkeleton lines={4} />
          ) : awaitingReview.length === 0 ? (
            <p className="text-sm text-gray-500 italic">
              No sessions waiting on review. Nice.
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
            <ArrowPathIcon className="h-4 w-4 text-navy-500" />
            Visual enrichment running
          </div>
          {loading ? (
            <LoadingSkeleton lines={4} />
          ) : inProgress.length === 0 ? (
            <p className="text-sm text-gray-500 italic">
              Nothing currently processing.
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
          <ExclamationTriangleIcon className="h-5 w-5 shrink-0" />
          <span>
            {stats.failed} session{stats.failed === 1 ? "" : "s"} failed to
            process and need attention.
          </span>
          <Link
            href="/portal/notes"
            className="ml-auto inline-flex items-center text-xs font-medium underline"
          >
            See list
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
      className="block rounded-lg border border-gray-200 bg-white p-4 transition-colors hover:border-gold-300"
    >
      <div className="flex items-start justify-between">
        {icon}
        <span className="text-2xl font-semibold text-navy-800 tabular-nums">
          {loading ? "…" : value}
        </span>
      </div>
      <p className="mt-1 text-xs text-gray-500">{label}</p>
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
        <ArrowRightIcon className="h-4 w-4 text-gray-300 shrink-0" />
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
