"use client";

import {
  AlertTriangle,
  ArrowRight,
  CalendarDays,
  ClipboardList,
  Clock,
  History,
  IdCard,
  Stethoscope,
} from "lucide-react";
import { humanizeError } from "@/lib/api";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouteSegment } from "@/lib/use-route-segment";

import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import EmptyPanelState from "@/components/portal/EmptyPanelState";
import PageHeader from "@/components/portal/PageHeader";
import { listMySessionsByPatientIdentifier } from "@/lib/portal-api";
import {
  badgeVariantFor,
  formatRelative,
  humanSpecialty,
  shortSessionId,
} from "@/lib/session-format";
import type { PatientSessionMatch } from "@/types";

/**
 * `/portal/patients/[identifier]` — every session the calling
 * clinician has recorded against one patient identifier, on a single
 * page.
 *
 * The page is the landing surface for any "longitudinal context"
 * shortcut in the portal: B2 Quick Actions identifier search modal,
 * inbox row identifier chip → patient page (future), and the iOS
 * prior-encounters rail's web mirror.
 *
 * Owner-scoping happens server-side: the backend filters by
 * `clinician_id == user.user_id` before decrypting any identifier,
 * so two clinicians who happen to use the same chart number get
 * disjoint result sets. See the parent server shell for the full
 * PHI rationale.
 *
 * Layout mirrors the dashboard:
 *   - PageHeader (title = formatted identifier, eyebrow + ICU
 *     pluralized count + first/last visit)
 *   - 3 stat tiles (total / last visit / most-recent specialty)
 *   - Session list — chronological newest-first cards
 *   - Loading: PageHeader skeleton + LoadingSkeleton list
 *   - Empty: EmptyPanelState
 *   - Failure: red retry banner mirroring the dashboard pattern
 */
export default function PatientDetailClient() {
  const t = useTranslations("PatientDetail");
  // Static-export gotcha — see web/lib/use-route-segment.ts. The hook
  // also handles URI decoding and the array-vs-string `useParams()`
  // typing, so the call site stays a single line.
  const identifier = useRouteSegment("identifier");

  const [sessions, setSessions] = useState<PatientSessionMatch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!identifier) return;
    setLoading(true);
    setError(null);
    try {
      const matches = await listMySessionsByPatientIdentifier(identifier);
      // Newest-first ordering is the contract the page renders against.
      // The backend doesn't guarantee a sort order, so we sort here.
      matches.sort((a, b) => b.created_at.localeCompare(a.created_at));
      setSessions(matches);
    } catch (e) {
      // No identifier in the error message we surface — message is the
      // generic "couldn't load" string from the catalog, so a 422 or
      // 500 doesn't echo PHI into the UI.
      setError(humanizeError(e, t("loadFailed")));
    } finally {
      setLoading(false);
    }
  }, [identifier, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const summary = useMemo(() => derivePatientSummary(sessions), [sessions]);

  return (
    <div className="aurion-page-padded aurion-container">
      <PageHeader
        breadcrumb={[
          { label: t("backToInbox"), href: "/portal/notes" },
          // Identifier appears once here in the breadcrumb trail
          // because the user just typed/clicked it to get here — the
          // PHI is already in the URL bar; this just mirrors it.
          { label: identifier || t("title") },
        ]}
        eyebrow={t("eyebrow")}
        title={identifier || t("title")}
        description={
          loading
            ? undefined
            : sessions.length === 0
              ? t("subtitle.none")
              : t("subtitle.summary", {
                  count: sessions.length,
                  first: summary.firstVisitDisplay,
                  last: summary.lastVisitDisplay,
                })
        }
        actions={
          <Button variant="secondary" size="sm" onClick={() => void load()}>
            {t("refresh")}
          </Button>
        }
      />

      {error && !loading && (
        <div className="mb-4 flex items-center gap-3 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700">
          <AlertTriangle className="h-5 w-5 shrink-0" />
          <span className="flex-1">{t("loadFailed")}</span>
          <button
            type="button"
            onClick={() => void load()}
            className="text-xs font-semibold underline"
            data-testid="patient-detail-retry"
          >
            {t("retry")}
          </button>
        </div>
      )}

      {/* ── Stat tiles ── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 mb-6">
        <StatTile
          icon={<History className="h-5 w-5 text-gold-600" />}
          label={t("stats.totalSessions")}
          value={loading ? "…" : String(summary.totalSessions)}
        />
        <StatTile
          icon={<Clock className="h-5 w-5 text-amber-600" />}
          label={t("stats.lastVisit")}
          value={
            loading
              ? "…"
              : summary.lastVisitRelative
                ? summary.lastVisitRelative
                : t("stats.never")
          }
        />
        <StatTile
          icon={<Stethoscope className="h-5 w-5 text-navy-500" />}
          label={t("stats.recentSpecialty")}
          value={
            loading
              ? "…"
              : summary.recentSpecialty
                ? humanSpecialty(summary.recentSpecialty)
                : t("stats.notAvailable")
          }
        />
      </div>

      {/* ── Session list ── */}
      <Card>
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-navy-700">
          <ClipboardList className="h-4 w-4 text-gold-500" />
          {t("sessions.title")}
        </div>
        {loading ? (
          <LoadingSkeleton lines={5} />
        ) : sessions.length === 0 ? (
          <EmptyPanelState
            icon={<IdCard className="h-7 w-7" />}
            title={t("sessions.empty")}
            hint={t("sessions.emptyHint")}
          />
        ) : (
          <ul
            className="divide-y divide-gray-100"
            data-testid="patient-detail-session-list"
          >
            {sessions.map((s) => (
              <SessionRow key={s.session_id} session={s} />
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}

/* ── Subcomponents ──────────────────────────────────────────────────────── */

function StatTile({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="rounded-aurion-lg border border-hairline bg-surface px-4 py-3.5 shadow-card">
      <div className="flex items-start justify-between gap-2">
        <span className="text-navy-300">{icon}</span>
        <span className="aurion-display text-navy-800 tabular-nums truncate max-w-[60%] text-right">
          {value}
        </span>
      </div>
      <p className="mt-2 aurion-micro">{label}</p>
    </div>
  );
}

function SessionRow({ session }: { session: PatientSessionMatch }) {
  // Cast the bare string state through SessionState in badgeVariantFor;
  // PatientSessionMatch types state as `string` (backend gives us the
  // enum value string), but the helper expects the strict union. The
  // helper's default branch covers any unknown state safely.
  const variant = badgeVariantFor(session.state as never);
  return (
    <li className="py-2.5">
      {/* Plain anchor for dynamic `/portal/notes/[id]` — Next `<Link>`
          collapses the URL under static export.
          See web/lib/use-route-segment.ts. */}
      <a
        href={`/portal/notes/${session.session_id}`}
        className="flex items-center gap-3 hover:bg-gray-50 -mx-2 px-2 py-1 rounded-md transition-colors"
        data-testid={`patient-detail-row-${session.session_id}`}
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-navy-50 text-navy-400 ring-1 ring-inset ring-navy-100">
          <Stethoscope className="h-4 w-4" />
        </span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-navy-800 truncate">
            {humanSpecialty(session.specialty)}
          </p>
          <p className="text-xs text-gray-500 mt-0.5 flex items-center gap-1.5">
            <CalendarDays className="h-3 w-3 shrink-0 text-navy-300" />
            <span className="truncate">
              {formatRelative(session.created_at, { withYear: true })}
            </span>
            <code
              className="shrink-0 rounded-md bg-gray-100 px-1.5 py-0.5 font-mono text-[10px] tracking-tight text-gray-500"
              title={session.session_id}
            >
              {shortSessionId(session.session_id)}
            </code>
          </p>
        </div>
        <span className="shrink-0" title={session.state}>
          <Badge variant={variant} dot>
            {session.state.replace(/_/g, " ")}
          </Badge>
        </span>
        <ArrowRight className="h-4 w-4 text-gray-300 shrink-0" />
      </a>
    </li>
  );
}

/* ── Stats derivation ───────────────────────────────────────────────────── */

interface PatientSummary {
  totalSessions: number;
  firstVisitDisplay: string;
  lastVisitDisplay: string;
  lastVisitRelative: string | null;
  recentSpecialty: string | null;
}

/**
 * Pure derivation from the sorted (newest-first) sessions array.
 *
 * Assumes the caller has already sorted by `created_at` descending —
 * we don't re-sort here because the page sorts once on load and uses
 * the same array for both display and stats. Returns sentinel values
 * for the empty list so the page can render the same layout with
 * skeleton text rather than branching the whole tree on emptiness.
 */
function derivePatientSummary(
  sessions: readonly PatientSessionMatch[],
): PatientSummary {
  if (sessions.length === 0) {
    return {
      totalSessions: 0,
      firstVisitDisplay: "",
      lastVisitDisplay: "",
      lastVisitRelative: null,
      recentSpecialty: null,
    };
  }
  const newest = sessions[0];
  const oldest = sessions[sessions.length - 1];
  return {
    totalSessions: sessions.length,
    firstVisitDisplay: formatDateOnly(oldest.created_at),
    lastVisitDisplay: formatDateOnly(newest.created_at),
    lastVisitRelative: formatRelative(newest.created_at),
    recentSpecialty: newest.specialty,
  };
}

/** Short, locale-aware "Mar 14, 2025" display for the header
 * description. Falls back to the raw ISO if the timestamp is
 * unparseable (same defensive contract as `formatRelative`). */
function formatDateOnly(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}
