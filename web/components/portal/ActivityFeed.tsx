"use client";

import {
  Activity,
  AlertTriangle,
  BadgeCheck,
  Download,
  Eye,
  FileCheck,
  FileText,
  Send,
  Sparkles,
  Trash2,
  XCircle,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getMyAuditLog } from "@/lib/portal-api";
import { formatRelative } from "@/lib/session-format";
import type { AuditEvent, PaginatedResponse } from "@/types";

/**
 * /portal/dashboard — live activity feed.
 *
 * Compact stream of the most recent noteworthy events for this
 * clinician, polled from /api/v1/me/audit. Sits between "I have
 * sessions to review" (the awaiting-review panel) and "what's
 * happened lately" (the recent strip) — focused specifically on
 * *what changed* in the last few hours.
 *
 * Why not WebSocket: the existing audit feed is HTTP-only, polling
 * is sufficient for the dashboard refresh cadence (clinicians look
 * at the dashboard between patients, not constantly), and adding a
 * second long-lived connection alongside the Stage 2 progress
 * WebSocket invites idempotency issues. 30s poll is fine — if a
 * physician approves Stage 1 on their iOS device while looking at
 * the portal, they see the new "Approved" row within half a minute.
 *
 * Noise filter: we surface events that change the physician's todo
 * list (failures, ready-for-review, EMR retries needed) and major
 * milestones (approvals, exports). We hide low-noise events
 * (frame uploads, masking confirmations) — they're audit-trail
 * material, not dashboard signal.
 *
 * Empty state: rather than a sad "no activity" line, show a
 * reassuring "All caught up" with an icon. Same vertical rhythm
 * as the dashboard's other empty states.
 *
 * Failed-load handling: if the audit endpoint errors, render an
 * inline retry button. We don't surface the error in the panel
 * border (avoids alarming the physician for a transient hiccup).
 */

/** Events worth surfacing on the dashboard. Tight allowlist — we'd
 *  rather skip a borderline event than overload the feed. New event
 *  types are opted in here on a case-by-case basis. */
const NOTEWORTHY_EVENTS: ReadonlySet<string> = new Set([
  // Notes
  "stage1_delivered",
  "stage1_failed",
  "stage2_complete",
  "stage2_failed",
  "stage1_approved",
  "note_exported",
  "bulk_note_export",
  "conflict_resolved",
  // EMR
  "emr_write_back_sent",
  "emr_write_back_failed",
  // Lifecycle (terminal)
  "session_purged",
  "session_discarded",
]);

const POLL_INTERVAL_MS = 30_000;
const MAX_ROWS = 8;

export default function ActivityFeed() {
  const t = useTranslations("Dashboard.activity");
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  // Tracks the most recent event_timestamp we've seen so we can
  // skip re-rendering when polling returns no new rows.
  const lastSeenRef = useRef<string | null>(null);

  const load = useCallback(async (showSkeleton: boolean) => {
    if (showSkeleton) setLoading(true);
    setFailed(false);
    try {
      // Pull 25 to give the noteworthy filter enough headroom to
      // land 8 surfaceable rows even when low-noise events dominate.
      const resp = (await getMyAuditLog({ page_size: 25 })) as PaginatedResponse<AuditEvent>;
      const noteworthy = (resp.items ?? []).filter((e) =>
        NOTEWORTHY_EVENTS.has(e.event_type),
      );
      // Skip the state update when the head event hasn't moved —
      // avoids unnecessary re-renders during the 30s poll.
      const newest = noteworthy[0]?.event_timestamp ?? null;
      if (newest && newest !== lastSeenRef.current) {
        lastSeenRef.current = newest;
        setEvents(noteworthy.slice(0, MAX_ROWS));
      } else if (lastSeenRef.current === null) {
        // First load, even if empty
        setEvents(noteworthy.slice(0, MAX_ROWS));
      }
    } catch {
      setFailed(true);
    } finally {
      if (showSkeleton) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(true);
    const id = window.setInterval(() => void load(false), POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [load]);

  return (
    <Card>
      <div className="mb-3 flex items-center gap-2">
        <Activity className="h-4 w-4 text-aurion-secondary" />
        <h2 className="text-sm font-semibold text-aurion-primary">
          {t("title")}
        </h2>
        <span className="ml-auto inline-flex items-center gap-1 text-[10px] uppercase tracking-wide text-aurion-tertiary">
          {/* Tiny "live" indicator — pulses to suggest the feed is
              self-refreshing without needing the user to act. */}
          <span className="relative inline-flex h-1.5 w-1.5">
            <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" />
            <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-500" />
          </span>
          {t("live")}
        </span>
      </div>

      {loading ? (
        <LoadingSkeleton lines={4} />
      ) : failed ? (
        <FailedState onRetry={() => void load(true)} />
      ) : events.length === 0 ? (
        <EmptyState />
      ) : (
        <ul className="-mx-1 divide-y divide-aurion-hairline">
          {events.map((event) => (
            <ActivityRow key={uniqueKey(event)} event={event} />
          ))}
        </ul>
      )}
    </Card>
  );
}

/* ── Row ────────────────────────────────────────────────────────────────── */

function ActivityRow({ event }: { event: AuditEvent }) {
  // Event display strings live in the shared `AuditEvents.*` namespace
  // so /portal/audit (the full self-audit page) and this dashboard
  // feed render the same human label for any given event type.
  const t = useTranslations("AuditEvents");
  const tBtn = useTranslations("Dashboard.activity");
  const meta = visualFor(event.event_type);

  const tooltip = sessionTooltip(event);
  const label = t(meta.labelKey, {
    // Most labels don't take vars; passing an empty default keeps
    // next-intl happy for the ones that need {target} (e.g. EMR).
    target: extractTarget(event),
  });

  // Click-target for the row: drop into the session note review
  // (most events are session-scoped). Bulk export events go to
  // the notes inbox instead since they don't bind to one session.
  const href =
    event.event_type === "bulk_note_export"
      ? "/portal/notes"
      : `/portal/notes/${event.session_id}`;

  return (
    <li className="px-1">
      <Link
        href={href}
        className="group flex items-start gap-3 py-2.5 transition-colors hover:bg-aurion-muted rounded-md -mx-1 px-1"
      >
        <span
          className={
            "mt-0.5 inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-full " +
            meta.iconBg
          }
        >
          {meta.icon}
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm text-aurion-primary leading-snug">
            {label}
          </p>
          <p className="mt-0.5 text-[11px] text-aurion-tertiary">
            <span className="font-mono">{tooltip}</span>
            <span aria-hidden> · </span>
            {formatRelative(event.event_timestamp)}
          </p>
        </div>
        {event.event_type === "emr_write_back_failed" && (
          <span className="shrink-0 self-center rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-red-700 group-hover:bg-red-100 transition-colors">
            {tBtn("retry")}
          </span>
        )}
      </Link>
    </li>
  );
}

/* ── Empty + failed states ──────────────────────────────────────────────── */

function EmptyState() {
  const t = useTranslations("Dashboard.activity");
  return (
    <div className="flex flex-col items-center justify-center py-6 text-center">
      <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-full bg-gold-50 text-gold-600">
        <Sparkles className="h-7 w-7" />
      </div>
      <p className="aurion-callout font-medium text-aurion-primary">
        {t("allCaughtUp")}
      </p>
      <p className="mt-1 max-w-[28ch] text-xs text-aurion-secondary leading-relaxed">
        {t("allCaughtUpHint")}
      </p>
    </div>
  );
}

function FailedState({ onRetry }: { onRetry: () => void }) {
  const t = useTranslations("Dashboard.activity");
  return (
    <div className="flex items-center gap-3 py-4">
      <AlertTriangle className="h-5 w-5 shrink-0 text-amber-600" />
      <p className="flex-1 text-sm text-aurion-primary">
        {t("loadFailed")}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="rounded-aurion-md bg-gold-50 px-3 py-1.5 text-xs font-semibold text-gold-700 transition-colors hover:bg-gold-100"
      >
        {t("retry")}
      </button>
    </div>
  );
}

/* ── Visual + label mapping ─────────────────────────────────────────────── */

/** Mapping from event type to icon + bg tint + i18n label key. Tints
 *  are kept calm; only failures use red. The hierarchy: success
 *  (emerald) > info (navy) > warning (amber) > danger (red). */
interface RowVisual {
  icon: React.ReactNode;
  iconBg: string;
  labelKey: string;
}

function visualFor(eventType: string): RowVisual {
  switch (eventType) {
    case "stage1_delivered":
      return {
        icon: <FileText className="h-3.5 w-3.5 text-amber-700" />,
        iconBg: "bg-amber-50",
        labelKey: "stage1Delivered",
      };
    case "stage1_failed":
      return {
        icon: <XCircle className="h-3.5 w-3.5 text-red-600" />,
        iconBg: "bg-red-50",
        labelKey: "stage1Failed",
      };
    case "stage2_complete":
      return {
        icon: <Sparkles className="h-3.5 w-3.5 text-navy-600" />,
        iconBg: "bg-navy-50",
        labelKey: "stage2Complete",
      };
    case "stage2_failed":
      return {
        icon: <XCircle className="h-3.5 w-3.5 text-red-600" />,
        iconBg: "bg-red-50",
        labelKey: "stage2Failed",
      };
    case "stage1_approved":
      return {
        icon: <BadgeCheck className="h-3.5 w-3.5 text-emerald-600" />,
        iconBg: "bg-emerald-50",
        labelKey: "stage1Approved",
      };
    case "note_exported":
      return {
        icon: <Download className="h-3.5 w-3.5 text-emerald-700" />,
        iconBg: "bg-emerald-50",
        labelKey: "noteExported",
      };
    case "bulk_note_export":
      return {
        icon: <Download className="h-3.5 w-3.5 text-emerald-700" />,
        iconBg: "bg-emerald-50",
        labelKey: "bulkNoteExport",
      };
    case "conflict_resolved":
      return {
        icon: <FileCheck className="h-3.5 w-3.5 text-navy-600" />,
        iconBg: "bg-navy-50",
        labelKey: "conflictResolved",
      };
    case "emr_write_back_sent":
      return {
        icon: <Send className="h-3.5 w-3.5 text-emerald-700" />,
        iconBg: "bg-emerald-50",
        labelKey: "emrSent",
      };
    case "emr_write_back_failed":
      return {
        icon: <AlertTriangle className="h-3.5 w-3.5 text-red-600" />,
        iconBg: "bg-red-50",
        labelKey: "emrFailed",
      };
    case "session_purged":
      return {
        icon: <Trash2 className="h-3.5 w-3.5 text-aurion-tertiary" />,
        iconBg: "bg-aurion-muted",
        labelKey: "sessionPurged",
      };
    case "session_discarded":
      return {
        icon: <Trash2 className="h-3.5 w-3.5 text-aurion-tertiary" />,
        iconBg: "bg-aurion-muted",
        labelKey: "sessionDiscarded",
      };
    default:
      // Fallback — should never hit due to NOTEWORTHY_EVENTS gate
      return {
        icon: <Eye className="h-3.5 w-3.5 text-aurion-secondary" />,
        iconBg: "bg-aurion-muted",
        labelKey: "generic",
      };
  }
}

/** Targeted snippet for EMR-flavored labels — pulls the EMR system
 *  name out of details so the label can read "Epic write-back
 *  failed" instead of just "Write-back failed". Falls back to an
 *  empty string when no target is available. */
function extractTarget(event: AuditEvent): string {
  if (
    event.event_type === "emr_write_back_sent" ||
    event.event_type === "emr_write_back_failed"
  ) {
    const sys = event.details?.emr_system;
    if (typeof sys === "string" && sys.length > 0) return sys;
  }
  return "";
}

/** Short session reference (8-char id prefix) — no PHI. */
function sessionTooltip(event: AuditEvent): string {
  return event.session_id.slice(0, 8);
}

/** Stable React key for events: event_id when the row carries one
 *  (most do post-#189), otherwise compose from session_id + timestamp
 *  which is unique per event. */
function uniqueKey(e: AuditEvent): string {
  if (e.event_id) return e.event_id;
  return `${e.session_id}:${e.event_timestamp}`;
}

